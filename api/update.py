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

    # Run download in background thread
    threading.Thread(target=download_and_install, daemon=True).start()
    return jsonify({"status": "downloading"})


@update_bp.route("/restart", methods=["POST"])
def restart():
    """Restart the app after update is applied."""
    state = get_state()
    if state["status"] != "ready":
        return jsonify({"error": "更新尚未就緒"}), 400
    restart_app()
    return jsonify({"status": "restarting"})
