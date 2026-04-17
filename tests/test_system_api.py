"""tests/test_system_api.py — /api/system/open_external endpoint.

conftest auto-injects a valid auth token + Host header, so tests only need to
worry about body & URL validation."""

from unittest.mock import patch

import pytest

from web_ui import app


@pytest.fixture
def client():
    with app.test_client() as c:
        yield c


def test_open_external_https_ok(client):
    with patch("api.system.webbrowser.open") as m:
        res = client.post(
            "/api/system/open_external",
            json={"url": "https://aistudio.google.com/apikey"},
        )
    assert res.status_code == 200
    m.assert_called_once()
    assert m.call_args.args[0] == "https://aistudio.google.com/apikey"


def test_open_external_http_ok(client):
    with patch("api.system.webbrowser.open"):
        res = client.post(
            "/api/system/open_external",
            json={"url": "http://example.com"},
        )
    assert res.status_code == 200


def test_open_external_rejects_file_scheme(client):
    """file:// and other schemes must be rejected to prevent abuse."""
    with patch("api.system.webbrowser.open") as m:
        res = client.post(
            "/api/system/open_external",
            json={"url": "file:///etc/passwd"},
        )
    assert res.status_code == 400
    m.assert_not_called()


def test_open_external_rejects_javascript_scheme(client):
    with patch("api.system.webbrowser.open") as m:
        res = client.post(
            "/api/system/open_external",
            json={"url": "javascript:alert(1)"},
        )
    assert res.status_code == 400
    m.assert_not_called()


def test_open_external_rejects_empty_body(client):
    with patch("api.system.webbrowser.open") as m:
        res = client.post(
            "/api/system/open_external",
            data="",
            content_type="application/json",
        )
    assert res.status_code == 400
    m.assert_not_called()


def test_open_external_requires_auth_token(client):
    """With a wrong X-HV-Token the request must be 403.
    (conftest auto-injects a valid token; we explicitly override it here.)"""
    with patch("api.system.webbrowser.open") as m:
        res = client.post(
            "/api/system/open_external",
            json={"url": "https://example.com"},
            headers={"X-HV-Token": "not-the-real-token"},
        )
    assert res.status_code == 403
    m.assert_not_called()
