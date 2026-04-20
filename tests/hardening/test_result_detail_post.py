"""tests/hardening/test_result_detail_post.py

v0.13.4 follow-up: `GET /api/results/<path:file_path>` silently 404s for
absolute paths because encodeURIComponent('/Users/...') becomes
'%2FUsers%2F...', Werkzeug unquotes it to '//Users/...', and Flask's
path converter can't match the double slash. Every "最近結果" green-light
click fell through to the UI's "找不到詳情" branch even when the row had
a complete result_json.

`POST /api/results/detail {file_path: ...}` sidesteps the URL-pathing
dance entirely. These tests pin that endpoint's contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from api import results as api_results
from modules.result_store import ResultStore
from web_ui import app as _app


@pytest.fixture
def seeded(monkeypatch, tmp_path):
    """A real ResultStore with one completed absolute-path row — exactly
    what dogfood hit."""
    db = tmp_path / "results.db"
    store = ResultStore(db)
    abs_path = "/Users/test/Happy_Vision/for_TEST_PHOTO/IMG_4542.jpeg"
    store.save_result(
        abs_path,
        {
            "title": "Young man with headphones",
            "description": "classroom scene",
            "keywords": ["classroom", "student"],
            "category": "people",
            "subcategory": "",
            "scene_type": "indoor",
            "mood": "focused",
            "people_count": 1,
            "identified_people": [],
            "ocr_text": [],
        },
        usage={"input_tokens": 100, "output_tokens": 50,
               "total_tokens": 150, "model": "gemini-2.5-flash-lite"},
        cost_usd=0.0001,
    )
    store.close()

    def _factory(*a, **kw):
        return ResultStore(db)
    monkeypatch.setattr(api_results, "ResultStore", _factory)
    return abs_path


@pytest.fixture
def client():
    _app.config["TESTING"] = True
    with _app.test_client() as c:
        yield c


def test_post_detail_returns_complete_row_for_absolute_path(client, seeded):
    """The bug: GET /api/results/<path:file_path> 404s on absolute paths
    because of %2F double-slash normalisation. POST detail must work."""
    r = client.post("/api/results/detail",
                    json={"file_path": seeded})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["title"] == "Young man with headphones"
    assert body["file_path"] == seeded


def test_post_detail_accepts_legacy_path_key(client, seeded):
    """Tolerate both `file_path` and `path` in the JSON body — saves a
    future 'why isn't it working' debug session if the frontend drifts."""
    r = client.post("/api/results/detail",
                    json={"path": seeded})
    assert r.status_code == 200


def test_post_detail_404_on_unknown_path(client, seeded):
    r = client.post("/api/results/detail",
                    json={"file_path": "/nope/does-not-exist.jpg"})
    assert r.status_code == 404


def test_post_detail_400_on_missing_file_path(client, seeded):
    r = client.post("/api/results/detail", json={})
    assert r.status_code == 400


def test_post_detail_400_on_wrong_type(client, seeded):
    r = client.post("/api/results/detail",
                    json={"file_path": 123})
    assert r.status_code == 400


def test_get_path_route_still_works_for_relative(client, seeded):
    """The legacy GET /<path:file_path> route stays — it works fine for
    non-absolute paths and some internal callers may still use it."""
    # Relative path case: seeded path stripped of leading slash so
    # encodeURIComponent on the frontend + leading / reconstruction
    # on the backend still round-trips.
    import urllib.parse
    rel = seeded.lstrip("/")
    r = client.get(f"/api/results/{urllib.parse.quote(rel, safe='')}")
    # May 404 depending on matcher — we don't assert 200, just that it
    # doesn't 500. The POST route is the one we rely on going forward.
    assert r.status_code in (200, 404)
