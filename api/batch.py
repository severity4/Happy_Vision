"""api/batch.py — Gemini Batch API endpoints.

- POST /api/batch/submit       submit a folder as one-or-more batch jobs
- GET  /api/batch/jobs         list active + recently-completed jobs
- GET  /api/batch/jobs/<id>    job detail + per-item status
- POST /api/batch/jobs/<id>/cancel
- DELETE /api/batch/jobs/<id>  remove job row (does not call Gemini delete;
                                that's via cancel + TTL)
- GET  /api/batch/stream       SSE feed of batch state changes from the
                                background monitor

The monitor thread is started separately (web_ui) and feeds events through
an injected sink that calls _broadcast_sse here.
"""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

from modules import gemini_batch, pipeline
from modules.config import load_config
from modules.cost_estimator import estimate_batch_cost
from modules.event_store import EventStore
from modules.logger import setup_logger
from modules.result_store import ResultStore

log = setup_logger("api_batch")

batch_bp = Blueprint("batch", __name__, url_prefix="/api/batch")

_sse_queues: list[queue.Queue] = []
_sse_lock = threading.Lock()


def broadcast_batch_event(payload: dict) -> None:
    """Called by the background BatchMonitor to push a state change."""
    msg = f"event: {payload.get('type', 'batch')}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_queues:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_queues.remove(q)


@batch_bp.route("/estimate", methods=["GET"])
def estimate_submission():
    """Return projected cost + photo count + ETA for a prospective batch run.

    Query params:
      folder (required): absolute path of the folder to scan
      model, image_max_size, skip_existing, min_rating: override config

    Response is a CostEstimate.to_dict() — frontend renders this in the
    confirmation modal so users don't accidentally burn budget on 150k
    photos when they meant a test folder."""
    folder = (request.args.get("folder") or "").strip()
    if not folder:
        return jsonify({"error": "folder is required"}), 400
    if not Path(folder).is_dir():
        return jsonify({"error": f"not a directory: {folder}"}), 400

    config = load_config()
    model = request.args.get("model") or config.get("model", "lite")
    image_max_size = int(request.args.get("image_max_size") or config.get("image_max_size", 3072))
    skip_existing_arg = request.args.get("skip_existing")
    skip_existing = (
        skip_existing_arg.lower() in ("1", "true", "yes")
        if skip_existing_arg is not None
        else bool(config.get("skip_existing", True))
    )
    min_rating = int(request.args.get("min_rating") or config.get("min_rating", 0))

    try:
        est = estimate_batch_cost(
            folder=folder,
            model=model,
            image_max_size=image_max_size,
            skip_existing=skip_existing,
            min_rating=min_rating,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("estimate_batch_cost failed")
        return jsonify({"error": "estimate_failed", "message": str(e)}), 500
    return jsonify(est.to_dict())


@batch_bp.route("/submit", methods=["POST"])
def submit_batch():
    data = request.get_json(silent=True) or {}
    folder = (data.get("folder") or "").strip()
    if not folder:
        return jsonify({"error": "folder is required"}), 400
    if not Path(folder).is_dir():
        return jsonify({"error": f"not a directory: {folder}"}), 400

    config = load_config()
    api_key = (config.get("gemini_api_key") or "").strip()
    if not api_key:
        return jsonify({"error": "Gemini API key not configured"}), 400

    model = data.get("model") or config.get("model", "lite")
    image_max_size = int(data.get("image_max_size") or config.get("image_max_size", 3072))
    write_metadata = bool(
        data.get("write_metadata")
        if "write_metadata" in data
        else config.get("write_metadata", False)
    )
    skip_existing = bool(
        data.get("skip_existing")
        if "skip_existing" in data
        else config.get("skip_existing", True)
    )

    with EventStore() as events:
        events.add_event(
            "batch_api_submit",
            folder=folder,
            details={
                "model": model,
                "image_max_size": image_max_size,
                "write_metadata": write_metadata,
            },
        )

    try:
        summary = pipeline.submit_batch_run(
            folder=folder,
            api_key=api_key,
            model=model,
            image_max_size=image_max_size,
            write_metadata=write_metadata,
            skip_existing=skip_existing,
        )
    except gemini_batch.TierRequiredError as e:
        return jsonify({
            "error": "tier_required",
            "message": str(e),
            "billing_url": gemini_batch.BILLING_URL,
        }), 402
    except Exception as e:  # noqa: BLE001
        log.exception("Batch submit failed")
        return jsonify({"error": "submit_failed", "message": str(e)}), 500

    broadcast_batch_event({
        "type": "batch_submitted",
        "folder": folder,
        "chunks": summary["chunks"],
        "total_photos": summary["total_photos"],
        "skipped": summary["skipped"],
        "jobs": summary["jobs"],
    })
    return jsonify({"status": "submitted", **summary})


@batch_bp.route("/jobs", methods=["GET"])
def list_jobs():
    active_only = request.args.get("active") in ("1", "true", "yes")
    limit = max(1, min(500, int(request.args.get("limit", 100))))
    store = ResultStore()
    try:
        jobs = store.list_batch_jobs(active_only=active_only, limit=limit)
    finally:
        store.close()
    return jsonify({"jobs": jobs})


@batch_bp.route("/jobs/<path:job_id>", methods=["GET"])
def get_job(job_id: str):
    store = ResultStore()
    try:
        job = store.get_batch_job(job_id)
        if job is None:
            return jsonify({"error": "not_found"}), 404
        items = store.get_batch_items(job_id)
    finally:
        store.close()
    return jsonify({"job": job, "items": items})


@batch_bp.route("/jobs/<path:job_id>/cancel", methods=["POST"])
def cancel_job(job_id: str):
    config = load_config()
    api_key = (config.get("gemini_api_key") or "").strip()
    if not api_key:
        return jsonify({"error": "Gemini API key not configured"}), 400
    ok = gemini_batch.cancel_job(job_id, api_key)
    if ok:
        store = ResultStore()
        try:
            store.update_batch_job_status(job_id, "JOB_STATE_CANCELLED")
        finally:
            store.close()
        broadcast_batch_event({
            "type": "batch_state",
            "job_id": job_id,
            "state": "JOB_STATE_CANCELLED",
        })
    return jsonify({"cancelled": ok})


@batch_bp.route("/jobs/<path:job_id>", methods=["DELETE"])
def delete_job(job_id: str):
    store = ResultStore()
    try:
        store.delete_batch_job(job_id)
    finally:
        store.close()
    return jsonify({"deleted": True})


@batch_bp.route("/stream")
def stream():
    q: queue.Queue = queue.Queue(maxsize=200)
    with _sse_lock:
        _sse_queues.append(q)

    def generate():
        # Fire immediately so EventSource.onopen runs right away and the UI
        # can flip out of "connecting" state. (Same pattern as api/watch.py.)
        yield ": connected\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                if q in _sse_queues:
                    _sse_queues.remove(q)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
