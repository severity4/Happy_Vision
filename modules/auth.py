"""modules/auth.py — Per-session token + Host/Origin allowlist for localhost API.

Prevents other processes on the same machine and malicious web pages (DNS
rebinding) from calling Happy Vision's localhost API. The frontend reads the
token from a meta tag injected by web_ui at startup and sends it on every
fetch via the X-HV-Token header.

For EventSource / SSE requests, browsers do not allow setting custom headers,
so the token may also be supplied via the ?token=... query parameter.
"""

import secrets

SESSION_TOKEN = secrets.token_urlsafe(32)

_ALLOWED_HOSTS = {"127.0.0.1:8081", "localhost:8081"}
_ALLOWED_ORIGINS = {
    "http://127.0.0.1:8081",
    "http://localhost:8081",
    "null",  # pywebview file:// frames present Origin: null
}
_PUBLIC_PREFIXES = ("/api/health",)


def is_request_allowed(request) -> bool:
    """Return True if the request should be served.

    Public paths (health check, static frontend assets) always pass. API paths
    require: (1) Host header in allowlist, (2) Origin header — if present — in
    allowlist, (3) X-HV-Token header OR ?token=... query param equal to
    SESSION_TOKEN.
    """
    path = getattr(request, "path", "") or ""

    # Static frontend: anything not under /api/ is a Vue asset request
    if not path.startswith("/api/"):
        return True

    # Public API endpoints
    if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return True

    host = request.headers.get("Host", "")
    if host not in _ALLOWED_HOSTS:
        return False

    origin = request.headers.get("Origin")
    if origin is not None and origin not in _ALLOWED_ORIGINS:
        return False

    token = request.headers.get("X-HV-Token", "") or request.args.get("token", "")
    return secrets.compare_digest(token, SESSION_TOKEN)
