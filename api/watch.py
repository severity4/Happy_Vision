"""api/watch.py — Watch folder control API + SSE events"""

import json
import queue
import threading

from flask import Blueprint, request, jsonify, Response

from modules.config import load_config, save_config
from modules.event_store import EventStore
from modules.folder_watcher import FolderWatcher, WatcherCallbacks
from modules.logger import setup_logger
from modules.result_store import ResultStore

log = setup_logger("api_watch")

watch_bp = Blueprint("watch", __name__, url_prefix="/api/watch")

_sse_queues: list[queue.Queue] = []
_sse_lock = threading.Lock()
_watcher: FolderWatcher | None = None

# Shared ResultStore for SSE-side stat queries. Previously every broadcast
# event opened + closed its own connection, which re-ran 6 ALTER TABLE
# statements each time and added ~10ms × N requests per photo. For a
# 150k-photo backlog that added 20-25 minutes of pure open/close time.
# One connection, one ADD COLUMN pass at boot, live updates thereafter.
_shared_store: ResultStore | None = None
_shared_store_lock = threading.Lock()


def _get_shared_store() -> ResultStore:
    global _shared_store
    if _shared_store is None:
        with _shared_store_lock:
            if _shared_store is None:
                _shared_store = ResultStore()
    return _shared_store


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


class WatchSSECallbacks(WatcherCallbacks):
    def on_processed(self, file_path, queue_size):
        stats = _get_shared_store().get_today_stats()
        _broadcast_sse("watch_progress", {
            "file": file_path,
            "queue_size": queue_size,
            **stats,
        })

    def on_error(self, file_path, error):
        stats = _get_shared_store().get_today_stats()
        _broadcast_sse("watch_error", {
            "file": file_path,
            "error": error,
            **stats,
        })

    def on_state_change(self, state):
        _broadcast_sse("watch_state", {"status": state})


def get_watcher() -> FolderWatcher:
    """Get or create the singleton watcher instance."""
    global _watcher
    if _watcher is None:
        _watcher = FolderWatcher(callbacks=WatchSSECallbacks())
    return _watcher


def auto_start_watcher():
    """Auto-start watcher on app startup if config says so."""
    config = load_config()
    if config.get("watch_enabled") and config.get("watch_folder"):
        try:
            from web_ui import register_allowed_root  # lazy to avoid circular
            register_allowed_root(config["watch_folder"])
            watcher = get_watcher()
            watcher.start(folder=config["watch_folder"])
            log.info("Auto-started watcher for: %s", config["watch_folder"])
        except Exception:
            log.exception("Failed to auto-start watcher")


@watch_bp.route("/start", methods=["POST"])
def start_watch():
    data = request.get_json() or {}
    folder = data.get("folder", "")

    watcher = get_watcher()
    if watcher.state == "watching":
        return jsonify({"error": "Already watching"}), 409

    config = load_config()
    if not folder:
        folder = config.get("watch_folder", "")
    if not folder:
        return jsonify({"error": "folder is required"}), 400

    if not config.get("gemini_api_key"):
        return jsonify({"error": "Gemini API key not configured"}), 400

    # Save watch config
    config["watch_folder"] = folder
    config["watch_enabled"] = True
    save_config(config)

    from web_ui import register_allowed_root  # lazy to avoid circular
    register_allowed_root(folder)

    try:
        watcher.start(folder=folder)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    with EventStore() as events:
        events.add_event("watch_api_start", folder=folder)

    return jsonify({"status": "watching", "folder": folder})


@watch_bp.route("/pause", methods=["POST"])
def pause_watch():
    watcher = get_watcher()
    if watcher.state != "watching":
        return jsonify({"error": "Not currently watching"}), 409
    watcher.pause()
    with EventStore() as events:
        events.add_event("watch_api_pause", folder=watcher.folder)
    return jsonify({"status": "paused"})


@watch_bp.route("/resume", methods=["POST"])
def resume_watch():
    watcher = get_watcher()
    if watcher.state != "paused":
        return jsonify({"error": "Not currently paused"}), 409
    watcher.start()
    with EventStore() as events:
        events.add_event("watch_api_resume", folder=watcher.folder)
    return jsonify({"status": "watching"})


@watch_bp.route("/stop", methods=["POST"])
def stop_watch():
    watcher = get_watcher()
    folder = watcher.folder
    watcher.stop()

    config = load_config()
    config["watch_enabled"] = False
    save_config(config)
    with EventStore() as events:
        events.add_event("watch_api_stop", folder=folder)

    return jsonify({"status": "stopped"})


@watch_bp.route("/status")
def watch_status():
    watcher = get_watcher()
    stats = _get_shared_store().get_today_stats()
    return jsonify({
        "status": watcher.state,
        "folder": watcher.folder,
        "queue_size": watcher.queue_size,
        "processing": watcher.processing_count,
        **stats,
    })


@watch_bp.route("/concurrency", methods=["POST"])
def update_concurrency():
    data = request.get_json() or {}
    value = data.get("concurrency")
    if value is None or not isinstance(value, int):
        return jsonify({"error": "concurrency (int) is required"}), 400

    value = max(1, min(10, value))
    watcher = get_watcher()
    watcher.set_concurrency(value)

    config = load_config()
    config["watch_concurrency"] = value
    save_config(config)

    return jsonify({"concurrency": value})


@watch_bp.route("/events")
def watch_events():
    q = queue.Queue(maxsize=100)
    with _sse_lock:
        _sse_queues.append(q)

    def stream():
        try:
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            with _sse_lock:
                if q in _sse_queues:
                    _sse_queues.remove(q)

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@watch_bp.route("/recent")
def watch_recent():
    limit = request.args.get("limit", 20, type=int)
    recent = _get_shared_store().get_recent(limit=limit)
    return jsonify(recent)


@watch_bp.route("/enqueue", methods=["POST"])
def enqueue_folder():
    """Manually enqueue a folder's unprocessed photos into the watch queue.

    If the watcher is stopped, it auto-starts using the configured watch folder
    (or the enqueued folder as a fallback) so the queue gets processed.
    """
    data = request.get_json() or {}
    folder = data.get("folder", "")
    if not folder:
        return jsonify({"error": "folder is required"}), 400

    from pathlib import Path
    if not Path(folder).is_dir():
        return jsonify({"error": "Folder not accessible"}), 400

    config = load_config()
    if not config.get("gemini_api_key"):
        return jsonify({"error": "Gemini API key not configured"}), 400

    from web_ui import register_allowed_root  # lazy to avoid circular
    register_allowed_root(folder)

    watcher = get_watcher()

    # Auto-start watcher if stopped — use configured watch_folder,
    # falling back to the enqueued folder itself.
    if watcher.state == "stopped":
        start_folder = config.get("watch_folder") or folder
        register_allowed_root(start_folder)
        try:
            watcher.start(folder=start_folder)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    try:
        enqueued, skipped = watcher.enqueue_folder(folder)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    with EventStore() as events:
        events.add_event(
            "watch_api_enqueue",
            folder=folder,
            details={"enqueued": enqueued, "skipped": skipped},
        )

    return jsonify({"enqueued": enqueued, "skipped": skipped})
