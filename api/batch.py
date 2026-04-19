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


def _require_allowed_folder(folder: str) -> tuple[Path | None, tuple[dict, int] | None]:
    """Validate `folder` is a real directory AND inside the user's path
    allowlist (home + anything registered via register_allowed_root).

    v0.10.0 security review flagged that the batch endpoints trusted any
    absolute path — an attacker with the session token could point at
    ~/.ssh or /private/etc and base64-exfiltrate every JPG via the JSONL
    upload to Google. Fix mirrors /api/browse + /api/photo which have used
    _path_is_allowed since v0.3.4.

    Returns (resolved_path, None) on success OR (None, (error_json, status))."""
    if not folder:
        return None, ({"error": "folder is required"}, 400)
    raw = Path(folder)
    if not raw.is_dir():
        return None, ({"error": f"not a directory: {folder}"}, 400)
    # Lazy-import to avoid circular (web_ui imports batch_bp).
    from web_ui import _path_is_allowed, register_allowed_root
    if not _path_is_allowed(raw):
        return None, ({
            "error": "folder_not_allowed",
            "message": (
                "此資料夾不在允許清單。請先到「設定」或「監控」頁面明確"
                "開啟這個資料夾,再送出批次。"
            ),
        }, 403)
    resolved = raw.expanduser().resolve()
    # Re-register so future requests under this root pass the check even
    # if the user rebooted the app (allowlist is in-memory only).
    register_allowed_root(resolved)
    return resolved, None


def _coerce_int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


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
    folder_raw = (request.args.get("folder") or "").strip()
    folder, err = _require_allowed_folder(folder_raw)
    if err is not None:
        body, status = err
        return jsonify(body), status

    config = load_config()
    model = request.args.get("model") or config.get("model", "lite")
    image_max_size = _coerce_int(
        request.args.get("image_max_size"),
        int(config.get("image_max_size", 3072)),
    )
    skip_existing_arg = request.args.get("skip_existing")
    skip_existing = (
        skip_existing_arg.lower() in ("1", "true", "yes")
        if skip_existing_arg is not None
        else bool(config.get("skip_existing", True))
    )
    min_rating = _coerce_int(
        request.args.get("min_rating"),
        int(config.get("min_rating", 0)),
    )

    try:
        est = estimate_batch_cost(
            folder=str(folder),
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
    folder_raw = (data.get("folder") or "").strip()
    folder, err = _require_allowed_folder(folder_raw)
    if err is not None:
        body, status = err
        return jsonify(body), status

    config = load_config()
    api_key = (config.get("gemini_api_key") or "").strip()
    if not api_key:
        return jsonify({"error": "Gemini API key not configured"}), 400

    model = data.get("model") or config.get("model", "lite")
    image_max_size = _coerce_int(
        data.get("image_max_size"),
        int(config.get("image_max_size", 3072)),
    )
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
            folder=str(folder),
            details={
                "model": model,
                "image_max_size": image_max_size,
                "write_metadata": write_metadata,
            },
        )

    try:
        summary = pipeline.submit_batch_run(
            folder=str(folder),
            api_key=api_key,
            model=model,
            image_max_size=image_max_size,
            write_metadata=write_metadata,
            skip_existing=skip_existing,
        )
    except gemini_batch.TierRequiredError as e:
        # Code review: 402 Payment Required is historically unused and many
        # proxies/clients mishandle it. Use 403 with a stable error_code
        # the frontend branches on.
        # v0.12.0 partial_summary: if earlier chunks succeeded before the
        # tier wall hit, surface them so the UI can show "4 chunks already
        # live — cancel them or fix billing and resubmit the rest".
        body = {
            "error": "tier_required",
            "message": str(e),
            "billing_url": gemini_batch.BILLING_URL,
        }
        if hasattr(e, "partial_summary"):
            body["partial_summary"] = e.partial_summary
        return jsonify(body), 403
    except Exception as e:  # noqa: BLE001
        log.exception("Batch submit failed")
        return jsonify({"error": "submit_failed", "message": str(e)}), 500

    broadcast_batch_event({
        "type": "batch_submitted",
        "folder": str(folder),
        "chunks": summary["chunks"],
        "total_photos": summary["total_photos"],
        "skipped": summary["skipped"],
        "jobs": summary["jobs"],
    })
    # mode: "batch" harmonises with /api/analysis/start's routed response,
    # so the client branches on one field.
    return jsonify({"status": "submitted", "mode": "batch", **summary})


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
    # v0.10.1 security: verify the job exists locally before forwarding the
    # cancel to Gemini. Prevents a token-holding caller from cancelling
    # unrelated Gemini jobs on the user's API key (e.g. from other apps
    # sharing the same Google Cloud project).
    store = ResultStore()
    try:
        if store.get_batch_job(job_id) is None:
            return jsonify({"error": "not_found"}), 404
    finally:
        store.close()

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
    # v0.10.1 security: 404 when the job isn't known locally, so callers
    # can't use DELETE as an oracle for arbitrary job IDs. Also avoids
    # silently "succeeding" on typo'd IDs.
    store = ResultStore()
    try:
        if store.get_batch_job(job_id) is None:
            return jsonify({"error": "not_found"}), 404
        store.delete_batch_job(job_id)
    finally:
        store.close()
    return jsonify({"deleted": True})


@batch_bp.route("/health", methods=["GET"])
def health():
    """Monitor heartbeat + active job snapshot for UI health indicator.

    v0.11.0 observability fix. SRE audit flagged that when the daemon dies
    at 3am the user sees nothing the next morning. This endpoint makes the
    monitor's state inspectable; frontend polls it + shows a "monitor
    stuck" badge if `last_tick_at` is >3min ago.
    """
    # Lazy-import to avoid circular (monitor is started from web_ui which
    # imports this blueprint).
    from modules.batch_monitor import _monitor_instance
    if _monitor_instance is None:
        return jsonify({
            "alive": False,
            "last_tick_at": None,
            "last_tick_error": None,
            "active_jobs": 0,
            "consecutive_errors": 0,
            "reason": "monitor_not_started",
        })
    return jsonify(_monitor_instance.health_snapshot())


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
