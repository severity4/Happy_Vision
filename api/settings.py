"""api/settings.py — Config API"""

from flask import Blueprint, request, jsonify

from modules import rate_limiter
from modules.config import load_config, save_config

settings_bp = Blueprint("settings", __name__, url_prefix="/api/settings")

# Allowed image_max_size values — keep the UI honest and prevent bogus
# long-edge requests that would either crash PIL or silently eat budget.
ALLOWED_IMAGE_SIZES = {1024, 1536, 2048, 3072}


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
    rpm_changed = False
    for key in [
        "tester_name",
        "machine_name",
        "app_version",
        "model",
        "concurrency",
        "write_metadata",
        "skip_existing",
        "watch_folder",
        "watch_concurrency",
        "watch_interval",
        "rate_limit_rpm",
        "image_max_size",
    ]:
        if key in data:
            if key == "rate_limit_rpm":
                rpm = max(1, min(5000, int(data[key])))
                if rpm != config.get("rate_limit_rpm"):
                    rpm_changed = True
                config[key] = rpm
            elif key == "image_max_size":
                size = int(data[key])
                if size not in ALLOWED_IMAGE_SIZES:
                    return jsonify({
                        "error": f"image_max_size must be one of {sorted(ALLOWED_IMAGE_SIZES)}"
                    }), 400
                config[key] = size
            else:
                config[key] = data[key]
    if "gemini_api_key" in data and not data["gemini_api_key"].startswith("..."):
        config["gemini_api_key"] = data["gemini_api_key"]
    save_config(config)
    # Apply live — runtime throughput tuning shouldn't need a restart.
    if rpm_changed:
        rate_limiter.configure(int(config["rate_limit_rpm"]))
    return jsonify({"status": "ok"})
