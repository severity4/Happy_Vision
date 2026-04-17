"""api/analysis.py — Analysis start/pause/cancel + SSE progress"""

import json
import queue
import threading

from flask import Blueprint, request, jsonify, Response

from modules.config import load_config
from modules.event_store import EventStore
from modules.pipeline import run_pipeline, PipelineCallbacks, PipelineState
from modules.logger import setup_logger

log = setup_logger("api_analysis")

analysis_bp = Blueprint("analysis", __name__, url_prefix="/api/analysis")

_sse_queues: list[queue.Queue] = []
_sse_lock = threading.Lock()
_pipeline_thread: threading.Thread | None = None
_pipeline_state: PipelineState | None = None


def _broadcast_sse(event: str, data: dict):
    msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_queues:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_queues.remove(q)


class SSECallbacks(PipelineCallbacks):
    def on_progress(self, done, total, file_path):
        _broadcast_sse("progress", {"done": done, "total": total, "file": file_path})

    def on_error(self, file_path, error):
        _broadcast_sse("error", {"file": file_path, "error": error})

    def on_complete(self, total, failed):
        _broadcast_sse("complete", {"total": total, "failed": failed})


@analysis_bp.route("/start", methods=["POST"])
def start_analysis():
    global _pipeline_thread, _pipeline_state
    if _pipeline_thread and _pipeline_thread.is_alive():
        return jsonify({"error": "Analysis already running"}), 409

    data = request.get_json()
    folder = data.get("folder", "")
    if not folder:
        return jsonify({"error": "folder is required"}), 400

    config = load_config()
    api_key = config.get("gemini_api_key", "")
    if not api_key:
        return jsonify({"error": "Gemini API key not configured"}), 400

    model = data.get("model", config.get("model", "lite"))
    concurrency = data.get("concurrency", config.get("concurrency", 5))
    skip_existing = data.get("skip_existing", config.get("skip_existing", False))
    write_metadata = data.get("write_metadata", config.get("write_metadata", False))
    with EventStore() as events:
        events.add_event(
            "analysis_api_start",
            folder=folder,
            details={
                "model": model,
                "concurrency": concurrency,
                "skip_existing": skip_existing,
                "write_metadata": write_metadata,
            },
        )

    # Create state before starting thread so pause/cancel work immediately
    _pipeline_state = PipelineState()

    def run():
        global _pipeline_state
        run_pipeline(
            folder=folder,
            api_key=api_key,
            model=model,
            concurrency=concurrency,
            skip_existing=skip_existing,
            write_metadata=write_metadata,
            callbacks=SSECallbacks(),
            state=_pipeline_state,
        )
        _pipeline_state = None

    _pipeline_thread = threading.Thread(target=run, daemon=True)
    _pipeline_thread.start()

    return jsonify({"status": "started"})


@analysis_bp.route("/pause", methods=["POST"])
def pause_analysis():
    if _pipeline_state:
        _pipeline_state.pause()
        with EventStore() as events:
            events.add_event("analysis_api_pause")
        return jsonify({"status": "paused"})
    return jsonify({"error": "No analysis running"}), 404


@analysis_bp.route("/resume", methods=["POST"])
def resume_analysis():
    if _pipeline_state:
        _pipeline_state.resume()
        with EventStore() as events:
            events.add_event("analysis_api_resume")
        return jsonify({"status": "resumed"})
    return jsonify({"error": "No analysis running"}), 404


@analysis_bp.route("/cancel", methods=["POST"])
def cancel_analysis():
    if _pipeline_state:
        _pipeline_state.cancel()
        with EventStore() as events:
            events.add_event("analysis_api_cancel")
        return jsonify({"status": "cancelled"})
    return jsonify({"error": "No analysis running"}), 404


@analysis_bp.route("/stream")
def sse_stream():
    q = queue.Queue(maxsize=100)
    with _sse_lock:
        _sse_queues.append(q)

    def generate():
        try:
            yield ": keepalive\n\n"
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            with _sse_lock:
                if q in _sse_queues:
                    _sse_queues.remove(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
