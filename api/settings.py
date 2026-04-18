"""api/settings.py — Config API"""

from flask import Blueprint, request, jsonify

from modules import rate_limiter
from modules.config import load_config, save_config

settings_bp = Blueprint("settings", __name__, url_prefix="/api/settings")

# Allowed image_max_size values — keep the UI honest and prevent bogus
# long-edge requests that would either crash PIL or silently eat budget.
ALLOWED_IMAGE_SIZES = {1024, 1536, 2048, 3072}
ALLOWED_MODELS = {"lite", "flash"}


def _coerce_int(v, default: int) -> int:
    """Accept ints, numeric strings. Bad input → default, not a 500."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


@settings_bp.route("", methods=["GET"])
def get_settings():
    config = load_config()
    safe = dict(config)
    key = safe.get("gemini_api_key", "")
    safe["gemini_api_key_set"] = bool(key)
    # Never echo any part of the key back — even the last 4 chars narrow the
    # search space for anyone who scraped the token. UI drives its "activated"
    # state from `gemini_api_key_set` (bool) instead.
    safe["gemini_api_key"] = ""
    # Keep app_version aligned with /api/health so release audits don't see
    # two different strings. DEFAULT_CONFIG has "dev" which was never updated
    # at release time; the runtime truth is the bundled VERSION file.
    try:
        import web_ui
        safe["app_version"] = web_ui._get_version()
    except Exception:
        pass
    return jsonify(safe)


@settings_bp.route("", methods=["PUT"])
def update_settings():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "expected JSON object"}), 400

    config = load_config()
    rpm_changed = False

    # --- Validated numeric fields ---
    if "rate_limit_rpm" in data:
        rpm = max(1, min(5000, _coerce_int(data["rate_limit_rpm"], 60)))
        if rpm != config.get("rate_limit_rpm"):
            rpm_changed = True
        config["rate_limit_rpm"] = rpm

    if "image_max_size" in data:
        size = _coerce_int(data["image_max_size"], 3072)
        if size not in ALLOWED_IMAGE_SIZES:
            return jsonify({
                "error": f"image_max_size must be one of {sorted(ALLOWED_IMAGE_SIZES)}"
            }), 400
        config["image_max_size"] = size

    if "phash_threshold" in data:
        # 0 = disabled; above ~12 is basically "everything is a dup"
        config["phash_threshold"] = max(0, min(16, _coerce_int(data["phash_threshold"], 5)))

    if "concurrency" in data:
        config["concurrency"] = max(1, min(10, _coerce_int(data["concurrency"], 5)))

    if "watch_concurrency" in data:
        config["watch_concurrency"] = max(1, min(10, _coerce_int(data["watch_concurrency"], 1)))

    if "watch_interval" in data:
        # 1-3600 seconds. Below 1 spams disk; above 1h is silly for a watcher.
        config["watch_interval"] = max(1, min(3600, _coerce_int(data["watch_interval"], 10)))

    # --- Enum fields ---
    if "model" in data:
        m = str(data["model"])
        if m not in ALLOWED_MODELS:
            return jsonify({
                "error": f"model must be one of {sorted(ALLOWED_MODELS)}"
            }), 400
        config["model"] = m

    # --- Booleans ---
    for bkey in ("write_metadata", "skip_existing", "watch_enabled"):
        if bkey in data:
            config[bkey] = bool(data[bkey])

    # --- Free-form strings (length-capped to avoid misuse) ---
    for skey in ("tester_name", "machine_name", "app_version", "watch_folder"):
        if skey in data:
            v = data[skey]
            if not isinstance(v, str):
                return jsonify({"error": f"{skey} must be a string"}), 400
            config[skey] = v[:500]

    # --- API key (special-cased, see comment) ---
    # Empty string or a masked placeholder must NOT clear the stored key.
    # This prevented a bug where the frontend re-PUT the settings object it
    # got from GET (which returned "" for the key) and wiped the real
    # Keychain entry.
    if "gemini_api_key" in data:
        v = (data["gemini_api_key"] or "").strip()
        if v and not v.startswith("..."):
            config["gemini_api_key"] = v
        # else: don't touch the key — user didn't explicitly change it

    save_config(config)
    # Apply live — runtime throughput tuning shouldn't need a restart.
    if rpm_changed:
        rate_limiter.configure(int(config["rate_limit_rpm"]))
    return jsonify({"status": "ok"})
