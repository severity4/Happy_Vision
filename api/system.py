"""api/system.py — System helpers (open external URL in default browser).

pywebview doesn't open target="_blank" in the system browser by default, so
we expose a small endpoint the frontend can POST to. Scheme-validated so we
can't be turned into an arbitrary command proxy."""

import webbrowser
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

system_bp = Blueprint("system", __name__, url_prefix="/api/system")


@system_bp.route("/open_external", methods=["POST"])
def open_external():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", ""))
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return jsonify({"error": "only http/https URLs allowed"}), 400
    try:
        webbrowser.open(url, new=2)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "ok"})
