"""api/settings.py — Config API"""

from flask import Blueprint, request, jsonify

from modules.config import load_config, save_config

settings_bp = Blueprint("settings", __name__, url_prefix="/api/settings")


@settings_bp.route("", methods=["GET"])
def get_settings():
    config = load_config()
    safe = dict(config)
    key = safe.get("gemini_api_key", "")
    safe["gemini_api_key_set"] = bool(key)
    safe["gemini_api_key"] = f"...{key[-4:]}" if len(key) > 4 else ""
    return jsonify(safe)


@settings_bp.route("", methods=["PUT"])
def update_settings():
    data = request.get_json()
    config = load_config()
    for key in ["model", "concurrency", "write_metadata", "skip_existing"]:
        if key in data:
            config[key] = data[key]
    if "gemini_api_key" in data and not data["gemini_api_key"].startswith("..."):
        config["gemini_api_key"] = data["gemini_api_key"]
    save_config(config)
    return jsonify({"status": "ok"})
