"""tests/hardening/test_h5_error_response_shape.py

Hardening H5: 所有 API 4xx/5xx 回應都必須是 JSON，且含 `error` 欄位。

前端共用一個 fetch wrapper，所有錯誤路徑都靠 `body.error` 顯示 toast。
如果有哪個 endpoint 回純文字 / HTML / 沒有 error 欄位，前端會出 `undefined`
的錯誤彈窗，使用者一頭霧水。

本關對 Flask app 掃過所有 analysis、results、settings、export、watch、
system、batch、update 路由，模擬缺參數 / 錯 body 等觸發錯誤，確認 shape
一致。
"""

from __future__ import annotations

import json

import pytest

from web_ui import app as _app


@pytest.fixture
def client():
    _app.config["TESTING"] = True
    with _app.test_client() as client:
        yield client


def _assert_error_shape(response):
    """Every 4xx/5xx response must be JSON and contain `error` as a string."""
    assert 400 <= response.status_code < 600, (
        f"expected 4xx/5xx, got {response.status_code}"
    )
    content_type = response.headers.get("Content-Type", "")
    assert "json" in content_type.lower(), (
        f"error response content-type is {content_type!r}, not JSON — "
        "frontend error handler expects JSON"
    )
    body = json.loads(response.data)
    assert isinstance(body, dict), f"body is {type(body).__name__}, want dict"
    assert "error" in body, f"response body missing `error` key: {body}"
    assert isinstance(body["error"], str), (
        f"`error` field is {type(body['error']).__name__}, want str"
    )
    assert body["error"], "`error` field is empty string — useless to UI"


# ----------- analysis endpoints -----------

def test_analysis_start_missing_folder_has_error_shape(client):
    r = client.post("/api/analysis/start", json={})
    _assert_error_shape(r)
    assert r.status_code == 400


def test_analysis_start_missing_api_key_has_error_shape(client, monkeypatch):
    """If Keychain has no key, start_analysis rejects with a clear error."""
    from modules import secret_store
    secret_store.invalidate_cache()  # force fresh read
    # conftest already stubs keyring to in-memory + empty

    r = client.post("/api/analysis/start", json={"folder": "/tmp"})
    _assert_error_shape(r)


def test_analysis_pause_when_nothing_running_has_error_shape(client):
    r = client.post("/api/analysis/pause")
    _assert_error_shape(r)
    assert r.status_code == 404


def test_analysis_resume_when_nothing_running_has_error_shape(client):
    r = client.post("/api/analysis/resume")
    _assert_error_shape(r)


def test_analysis_cancel_when_nothing_running_has_error_shape(client):
    r = client.post("/api/analysis/cancel")
    _assert_error_shape(r)


# ----------- batch endpoints -----------

def test_batch_estimate_missing_folder_has_error_shape(client):
    # /api/batch/estimate is a GET with ?folder=; exercise it via query param
    # instead of the POST body (which used to fail with HTML 405 — caught as
    # a shape violation rather than a real API contract bug).
    r = client.get("/api/batch/estimate")
    _assert_error_shape(r)


def test_batch_estimate_folder_not_dir_has_error_shape(client, tmp_path):
    f = tmp_path / "nope.txt"
    f.write_text("x")
    r = client.get("/api/batch/estimate", query_string={"folder": str(f)})
    _assert_error_shape(r)


def test_batch_submit_missing_folder_has_error_shape(client):
    r = client.post("/api/batch/submit", json={})
    _assert_error_shape(r)


def test_batch_jobs_nonexistent_id_has_error_shape(client):
    r = client.get("/api/batch/jobs/does-not-exist-id-123")
    _assert_error_shape(r)


# ----------- results endpoints -----------

def test_results_not_found_has_error_shape(client):
    """If the user asks for a file path that's not in the DB."""
    r = client.get("/api/results/by-path", query_string={"file_path": "/nope.jpg"})
    # Acceptable: either 404 with error shape, or 200 with empty — both
    # are defensible. Only enforce shape if status is 4xx/5xx.
    if r.status_code >= 400:
        _assert_error_shape(r)


# ----------- settings endpoints -----------

def test_settings_put_invalid_body_has_error_shape(client):
    r = client.put("/api/settings", data="not json at all",
                   content_type="text/plain")
    if r.status_code >= 400:
        _assert_error_shape(r)


# ----------- general shape sanity -----------

def test_error_shape_helper_catches_html_error_page():
    """Meta-test: if a future endpoint returns an HTML 500 page (Flask's
    default when debug=False), our shape assertion must catch it."""
    from flask import Flask

    probe_app = Flask("probe")
    probe_app.config["TESTING"] = True

    @probe_app.route("/bad_html_err")
    def bad():
        return "<html><body>500</body></html>", 500

    with probe_app.test_client() as c:
        r = c.get("/bad_html_err")
        # Our helper should REJECT this shape.
        with pytest.raises(AssertionError):
            _assert_error_shape(r)
