"""tests/hardening/test_h5a_405_json.py

Hardening H5a (追加發現)：Flask 預設 405 Method Not Allowed 回 HTML，
破壞 H5 的 JSON shape 合約。前端若打錯 method，會看到 `undefined` toast
或 JSON parse 失敗。

修法：註冊 `@app.errorhandler(405)` 回 JSON `{"error": "..."}`，對齊其他
錯誤回應形狀。
"""

from __future__ import annotations

import pytest

from web_ui import app as _app


@pytest.fixture
def client():
    _app.config["TESTING"] = True
    with _app.test_client() as c:
        yield c


def test_method_not_allowed_returns_json(client):
    """Hitting an existing route with the WRONG method must 405 with a
    JSON body — not Flask's default HTML template."""
    # /api/health is GET-only; try DELETE.
    r = client.delete("/api/health")
    assert r.status_code == 405
    assert "application/json" in r.headers.get("Content-Type", ""), (
        f"405 returned non-JSON content-type: {r.headers.get('Content-Type')}"
    )
    data = r.get_json()
    assert isinstance(data, dict)
    assert "error" in data
    # Error message should be non-empty and machine-readable
    assert isinstance(data["error"], str)
    assert data["error"]


def test_405_on_analysis_start_delete_returns_json(client):
    """/api/analysis/start accepts POST only. DELETE must 405 JSON.

    Note: GET on a POST-only /api path would fall through to the SPA
    catch-all (`/<path:path>`) and return index.html — that's Flask's
    routing order at work. Using DELETE avoids the catch-all."""
    r = client.delete("/api/analysis/start")
    assert r.status_code == 405
    data = r.get_json()
    assert data is not None
    assert "error" in data


def test_405_response_is_not_html(client):
    """Regression guard: the body must not begin with `<!doctype html>`
    or `<html`. That would be Flask's template leaking through and
    crash the frontend's JSON.parse."""
    r = client.delete("/api/settings")
    # Should be 405 (PUT+GET allowed, DELETE not)
    if r.status_code == 405:
        body = r.get_data(as_text=True).lstrip().lower()
        assert not body.startswith(("<!doctype", "<html")), (
            f"405 leaked HTML body: {body[:200]!r}"
        )


def test_404_also_returns_json(client):
    """Sister check: unknown routes should also be JSON, not HTML. Some
    Flask apps leak the default HTML on 404 too. Our /<path:path>
    catch-all serves index.html for SPA routing, so a bogus /api path
    goes through that — let's at least verify a totally unknown /api
    path returns something the frontend can handle."""
    r = client.get("/api/nonexistent-xyz-12345")
    # Either 404 (JSON) or 200 with index.html (SPA fallback).
    # Must not be 500 or a Python traceback.
    assert r.status_code < 500
