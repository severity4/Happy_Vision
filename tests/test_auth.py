"""tests/test_auth.py"""
from unittest.mock import MagicMock

from modules import auth


def _mock_request(host="127.0.0.1:8081", origin=None, token=None, path="/api/settings", query_token=None):
    req = MagicMock()
    req.headers = {}
    if host is not None:
        req.headers["Host"] = host
    if origin is not None:
        req.headers["Origin"] = origin
    if token is not None:
        req.headers["X-HV-Token"] = token
    req.path = path
    req.args = {"token": query_token} if query_token else {}
    return req


def test_session_token_is_generated():
    assert auth.SESSION_TOKEN
    assert len(auth.SESSION_TOKEN) >= 32


def test_health_endpoint_is_always_allowed():
    req = _mock_request(host="evil.com", path="/api/health")
    assert auth.is_request_allowed(req) is True


def test_static_frontend_is_always_allowed():
    req = _mock_request(host="evil.com", path="/assets/index.js")
    assert auth.is_request_allowed(req) is True


def test_wrong_host_rejected():
    req = _mock_request(host="evil.com", token=auth.SESSION_TOKEN)
    assert auth.is_request_allowed(req) is False


def test_wrong_origin_rejected():
    req = _mock_request(origin="http://evil.com", token=auth.SESSION_TOKEN)
    assert auth.is_request_allowed(req) is False


def test_missing_token_rejected():
    req = _mock_request()
    assert auth.is_request_allowed(req) is False


def test_wrong_token_rejected():
    req = _mock_request(token="not-the-token")
    assert auth.is_request_allowed(req) is False


def test_correct_token_with_localhost_allowed():
    req = _mock_request(host="localhost:8081", token=auth.SESSION_TOKEN)
    assert auth.is_request_allowed(req) is True


def test_correct_token_with_127_allowed():
    req = _mock_request(host="127.0.0.1:8081", token=auth.SESSION_TOKEN)
    assert auth.is_request_allowed(req) is True


def test_null_origin_accepted():
    """pywebview embedded requests may have Origin: null."""
    req = _mock_request(origin="null", token=auth.SESSION_TOKEN)
    assert auth.is_request_allowed(req) is True


def test_correct_token_via_query_param_allowed():
    """SSE EventSource can't set custom headers; allow ?token=... fallback."""
    req = MagicMock()
    req.headers = {"Host": "127.0.0.1:8081"}
    req.path = "/api/watch/events"
    req.args = {"token": auth.SESSION_TOKEN}
    assert auth.is_request_allowed(req) is True
