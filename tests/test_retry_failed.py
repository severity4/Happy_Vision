"""tests/test_retry_failed.py — v0.12.0 retry-failed-photos API + DB.

User-facing: the Monitor 'FAIL · 今日失敗' card is now clickable, opening a
modal that lists failed photos with their error messages, with a single
'retry all' button. The backend just needs to:
  - list failures (optionally scoped by folder)
  - clear the 'failed' marker on a set of file_paths so skip_existing
    logic re-picks them up on the next run
"""
from __future__ import annotations

import pytest

from modules.result_store import ResultStore


@pytest.fixture
def store(tmp_path):
    s = ResultStore(tmp_path / "r.db")
    yield s
    s.close()


# ---------------- get_failed_results ----------------

def test_get_failed_results_returns_only_failed(store):
    store.save_result("/tmp/ok.jpg", {"title": "ok", "keywords": []})
    store.mark_failed("/tmp/fail1.jpg", "429 rate limit")
    store.mark_failed("/tmp/fail2.jpg", "metadata write failed")
    items = store.get_failed_results()
    paths = {i["file_path"] for i in items}
    assert paths == {"/tmp/fail1.jpg", "/tmp/fail2.jpg"}
    assert all("error_message" in i for i in items)


def test_get_failed_results_filters_by_folder(store):
    store.mark_failed("/project/a/fail.jpg", "err1")
    store.mark_failed("/project/b/fail.jpg", "err2")
    in_a = store.get_failed_results(folder="/project/a")
    assert len(in_a) == 1
    assert in_a[0]["file_path"] == "/project/a/fail.jpg"


# ---------------- clear_failed ----------------

def test_clear_failed_removes_only_specified(store):
    store.mark_failed("/tmp/a.jpg", "x")
    store.mark_failed("/tmp/b.jpg", "y")
    store.mark_failed("/tmp/c.jpg", "z")
    cleared = store.clear_failed(["/tmp/a.jpg", "/tmp/c.jpg"])
    assert cleared == 2
    remaining = store.get_failed_results()
    assert [i["file_path"] for i in remaining] == ["/tmp/b.jpg"]


def test_clear_failed_doesnt_touch_completed_rows(store):
    store.save_result("/tmp/done.jpg", {"title": "t", "keywords": []})
    store.mark_failed("/tmp/fail.jpg", "x")
    store.clear_failed(["/tmp/done.jpg", "/tmp/fail.jpg"])
    # Completed row survives (clear_failed only DELETEs WHERE status='failed')
    assert store.is_processed("/tmp/done.jpg")
    assert not store.is_processed("/tmp/fail.jpg")


def test_clear_failed_empty_list_is_noop(store):
    store.mark_failed("/tmp/a.jpg", "x")
    assert store.clear_failed([]) == 0
    assert len(store.get_failed_results()) == 1


# ---------------- /api/results/failed endpoint ----------------

def test_api_failed_list_returns_count_and_items():
    """Real Flask test client. Autouse conftest isolates HAPPY_VISION_HOME
    so this doesn't hit the user's real DB."""
    import web_ui
    store = ResultStore()
    try:
        store.mark_failed("/tmp/fail1.jpg", "reason A")
        store.mark_failed("/tmp/fail2.jpg", "reason B")
    finally:
        store.close()
    client = web_ui.app.test_client()
    r = client.get("/api/results/failed")
    assert r.status_code == 200
    body = r.get_json()
    assert body["count"] == 2
    paths = {i["file_path"] for i in body["items"]}
    assert paths == {"/tmp/fail1.jpg", "/tmp/fail2.jpg"}


def test_api_retry_clears_failures():
    import web_ui
    store = ResultStore()
    try:
        store.mark_failed("/tmp/fail1.jpg", "reason")
    finally:
        store.close()
    client = web_ui.app.test_client()
    r = client.post("/api/results/retry", json={"file_paths": ["/tmp/fail1.jpg"]})
    assert r.status_code == 200
    body = r.get_json()
    assert body["cleared"] == 1
    # And now the row is gone.
    store = ResultStore()
    try:
        assert len(store.get_failed_results()) == 0
    finally:
        store.close()


def test_api_retry_without_files_or_folder_returns_400():
    import web_ui
    client = web_ui.app.test_client()
    r = client.post("/api/results/retry", json={})
    assert r.status_code == 400
    assert "no failures" in r.get_json()["error"]


def test_api_retry_with_folder_batch_clears_all_under_it():
    import web_ui
    store = ResultStore()
    try:
        store.mark_failed("/project/a/fail1.jpg", "x")
        store.mark_failed("/project/a/fail2.jpg", "y")
        store.mark_failed("/project/b/fail3.jpg", "z")
    finally:
        store.close()
    client = web_ui.app.test_client()
    r = client.post("/api/results/retry", json={"folder": "/project/a"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["cleared"] == 2
    # /project/b survives
    store = ResultStore()
    try:
        left = store.get_failed_results()
        assert [i["file_path"] for i in left] == ["/project/b/fail3.jpg"]
    finally:
        store.close()
