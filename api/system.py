"""api/system.py — System helpers (open external URL in default browser).

pywebview doesn't open target="_blank" in the system browser by default, so
we expose a small endpoint the frontend can POST to. Defense in depth:
  - scheme must be http/https (blocks file://, javascript:, smb://, etc.)
  - host must be in the allowlist below — it's only there for the few
    domains the UI actually links to; prevents the endpoint being turned
    into a phishing-overlay launcher if an attacker somehow acquires the
    session token.
"""

import webbrowser
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

system_bp = Blueprint("system", __name__, url_prefix="/api/system")

# External domains the app legitimately links to. Keep minimal — expand
# only when a new UI surface genuinely needs to punch out to the browser.
ALLOWED_HOSTS = {
    "aistudio.google.com",          # Settings page — where users get API keys
    "ai.google.dev",                # Gemini docs / pricing page
    "console.cloud.google.com",     # Quota / billing
    "github.com",                   # Release / issue tracker
}


@system_bp.route("/open_external", methods=["POST"])
def open_external():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", ""))
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return jsonify({"error": "only http/https URLs allowed"}), 400
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        return jsonify({"error": f"host {host!r} not in allowlist"}), 400
    try:
        webbrowser.open(url, new=2)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "ok"})
