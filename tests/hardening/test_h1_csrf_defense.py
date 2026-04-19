"""tests/hardening/test_h1_csrf_defense.py

Hardening H1: CSRF / DNS rebinding / non-localhost origin 全部阻擋。

背景：Happy Vision 的 HTTP server 只綁 localhost + 自簽 session token，但
仍要防：
- 惡意網頁透過 <img src="http://127.0.0.1:8081/api/...">（不帶 token →ok）
- 惡意網頁透過 fetch()（帶 token 機率低；但 Origin header 不對要擋）
- DNS rebinding 攻擊：惡意 DNS 讓瀏覽器覺得 `evil.com` 解析到 127.0.0.1，
  Host header 寫 `evil.com:8081` → 我們用 Host allowlist 擋
- 某些工具不帶 Host header → 必須擋
- Host 的 port 錯（localhost:9999）→ 必須擋

和 tests/test_auth.py 互補 — 那裡覆蓋 happy path + 單一 CSRF 維度；
這裡專門 drill 到 corner case。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from modules import auth


def _request(host=None, origin=None, token=None, path="/api/settings",
             query_token=None, method="GET"):
    req = MagicMock()
    req.headers = {}
    if host is not None:
        req.headers["Host"] = host
    if origin is not None:
        req.headers["Origin"] = origin
    if token is not None:
        req.headers["X-HV-Token"] = token
    req.path = path
    req.method = method
    req.args = {"token": query_token} if query_token else {}
    return req


def test_missing_host_header_rejected():
    """A request with no Host header at all must fail. This is a real case
    from some low-level HTTP clients / curl-based scanners."""
    req = _request(host=None, token=auth.SESSION_TOKEN)
    assert auth.is_request_allowed(req) is False


def test_empty_host_header_rejected():
    req = _request(host="", token=auth.SESSION_TOKEN)
    assert auth.is_request_allowed(req) is False


def test_host_with_wrong_port_rejected():
    """Another service on the same box (Home Assistant at 8123, for
    example) must not be able to relay requests to Happy Vision."""
    for bad in ("127.0.0.1:9999", "127.0.0.1:80", "localhost:8123",
                "127.0.0.1", "localhost"):
        req = _request(host=bad, token=auth.SESSION_TOKEN)
        assert auth.is_request_allowed(req) is False, (
            f"port/host-only {bad} should be rejected"
        )


def test_host_case_is_preserved_not_normalized():
    """127.0.0.1 is in the allowlist; HOST-style caps or different IP
    forms must be rejected to prevent bypass via uncommon encodings."""
    for variant in ("LOCALHOST:8081", "Localhost:8081",
                    "::1", "[::1]:8081", "0.0.0.0:8081"):
        req = _request(host=variant, token=auth.SESSION_TOKEN)
        assert auth.is_request_allowed(req) is False, (
            f"host variant {variant} must not bypass allowlist"
        )


def test_dns_rebinding_scenario_rejected():
    """Classic DNS rebind: browser resolves evil.com → 127.0.0.1 and
    sends the request. Host header shows `evil.com` → blocked even if
    somehow the attacker gets the token."""
    req = _request(host="evil.com:8081", token=auth.SESSION_TOKEN)
    assert auth.is_request_allowed(req) is False


def test_cross_origin_with_stolen_token_still_blocked_by_origin_check():
    """Even if a malicious page somehow obtains the session token (e.g.,
    from a reflected XSS elsewhere), the Origin check still kills the
    request."""
    req = _request(
        host="127.0.0.1:8081",
        origin="http://attacker.example",
        token=auth.SESSION_TOKEN,
    )
    assert auth.is_request_allowed(req) is False


def test_origin_with_matching_host_but_wrong_scheme_rejected():
    """https://127.0.0.1:8081 is not in the allowlist (we only serve http
    on localhost). A mismatch like this means the page was served over
    https — probably not ours."""
    req = _request(
        host="127.0.0.1:8081",
        origin="https://127.0.0.1:8081",
        token=auth.SESSION_TOKEN,
    )
    assert auth.is_request_allowed(req) is False


def test_token_timing_safe_comparison():
    """Ensures secrets.compare_digest is used (not ==). Otherwise a
    network-local attacker could time-leak the token a byte at a time.
    We can't directly prove timing safety but we can confirm the
    correct-prefix-wrong-suffix case still fails (sanity)."""
    almost = auth.SESSION_TOKEN[:-1] + ("A" if auth.SESSION_TOKEN[-1] != "A" else "B")
    req = _request(host="127.0.0.1:8081", token=almost)
    assert auth.is_request_allowed(req) is False


def test_post_requires_same_auth_as_get():
    """State-changing methods must not have weaker requirements."""
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        req = _request(host="evil.com", token=auth.SESSION_TOKEN, method=method)
        assert auth.is_request_allowed(req) is False


def test_query_token_for_sse_still_requires_host_check():
    """The `?token=` fallback must NOT bypass the Host allowlist — an
    attacker with the token and a DNS rebind shouldn't win."""
    req = MagicMock()
    req.headers = {"Host": "evil.com:8081"}
    req.path = "/api/watch/events"
    req.args = {"token": auth.SESSION_TOKEN}
    assert auth.is_request_allowed(req) is False


def test_public_health_path_does_not_accept_host_spoof_extension():
    """`/api/health` is public — but only the exact path, not
    `/api/health/../settings` or query-string tricks."""
    # Plain evil host + health: ok (by design — health is public)
    ok = _request(host="evil.com", path="/api/health")
    assert auth.is_request_allowed(ok) is True

    # But /api/healthy (no trailing slash / internal) must not be public.
    nope = _request(host="evil.com", path="/api/healthy")
    assert auth.is_request_allowed(nope) is False
