"""api/update.py — Update check & download API endpoints"""

import threading

from flask import Blueprint, jsonify

from modules.updater import (
    check_for_update,
    download_and_install,
    get_current_version,
    get_state,
    restart_app,
)

update_bp = Blueprint("update", __name__, url_prefix="/api/update")
_download_lock = threading.Lock()


@update_bp.route("/check", methods=["POST"])
def check():
    """Check GitHub for a newer release."""
    state = check_for_update()
    state["current_version"] = get_current_version()
    return jsonify(state)


@update_bp.route("/status")
def status():
    """Get current update state (for polling during download)."""
    state = get_state()
    state["current_version"] = get_current_version()
    return jsonify(state)


@update_bp.route("/download", methods=["POST"])
def download():
    """Start downloading and installing the update in background."""
    state = get_state()
    if state["status"] != "available":
        return jsonify({"error": "沒有可用的更新"}), 400

    # Try to acquire the lock without blocking; if someone else already
    # triggered a download, return 409 instead of spawning a second thread.
    if not _download_lock.acquire(blocking=False):
        return jsonify({"error": "更新下載已在進行中"}), 409

    def _run():
        try:
            download_and_install()
        finally:
            _download_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "downloading"})


@update_bp.route("/restart", methods=["POST"])
def restart():
    """Restart the app after update is applied."""
    state = get_state()
    if state["status"] != "ready":
        return jsonify({"error": "更新尚未就緒"}), 400
    restart_app()
    return jsonify({"status": "restarting"})
