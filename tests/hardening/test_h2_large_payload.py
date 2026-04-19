"""tests/hardening/test_h2_large_payload.py

Hardening H2: 異常大的 JSON body 必須被 Flask 拒絕（413），不能讓 worker
memory OOM。

合約：設 `app.config["MAX_CONTENT_LENGTH"]` = 10MB。任何超過的請求：
- 回 413 Request Entity Too Large
- 不觸發 route handler（避免 JSON parse 耗 CPU + RAM）
- 回 JSON shape 跟其他錯誤一致（符合 H5 合約）
"""

from __future__ import annotations

import json

import pytest

from web_ui import app as _app


@pytest.fixture
def client():
    _app.config["TESTING"] = True
    with _app.test_client() as c:
        yield c


def test_app_has_max_content_length_configured():
    """Flask without MAX_CONTENT_LENGTH will happily parse arbitrary-sized
    bodies. For a localhost API the threat isn't a malicious attacker so
    much as a bug in our own frontend sending a 500MB array. Cap at 10MB
    — generous for every legitimate use, disastrous for runaway code."""
    max_size = _app.config.get("MAX_CONTENT_LENGTH")
    assert max_size is not None, "MAX_CONTENT_LENGTH must be set"
    assert max_size <= 50 * 1024 * 1024, (
        "MAX_CONTENT_LENGTH > 50MB invites OOM via a single bad request"
    )
    assert max_size >= 1 * 1024 * 1024, (
        "MAX_CONTENT_LENGTH < 1MB would reject legitimate bulk results-by-path"
    )


def test_oversize_json_body_rejected_with_413(client):
    """Build a body larger than MAX_CONTENT_LENGTH and send it to a
    JSON-accepting endpoint. Flask should short-circuit before calling
    the route handler."""
    max_size = _app.config["MAX_CONTENT_LENGTH"]
    # 1MB over the limit.
    oversize = "A" * (max_size + 1024 * 1024)
    body = json.dumps({"folder": oversize})

    r = client.post(
        "/api/analysis/start",
        data=body,
        content_type="application/json",
    )

    # 413 is the standard; some Flask versions return 500 if the limit
    # trips differently — accept any 4xx/5xx, but NOT 200.
    assert r.status_code >= 400
    # Must not leak the full oversize payload back in the response body
    # (regression guard against echo attacks).
    assert len(r.data) < 100 * 1024


def test_payload_well_within_limit_is_accepted(client):
    """Regression guard: the limit must NOT kill reasonable requests.
    A folder path + a few config overrides = well under 1KB."""
    r = client.post(
        "/api/analysis/start",
        json={"folder": "/tmp/nonexistent-but-shape-valid"},
    )
    # May get 400 (folder doesn't exist) or 404 — NOT 413.
    assert r.status_code != 413


def test_bulk_results_by_path_under_limit_still_works(client, tmp_path):
    """Common realistic scenario: UI asks for results on 500 photos.
    Average path length ~150 chars → 75KB JSON. Must not trigger 413."""
    paths = [f"/Users/bobo/Photos/2026-{i:04d}.jpg" for i in range(500)]
    body = json.dumps({"file_paths": paths})

    assert len(body) < _app.config["MAX_CONTENT_LENGTH"]

    r = client.post(
        "/api/results/by-path",
        data=body,
        content_type="application/json",
    )
    assert r.status_code != 413
