"""tests/test_retry_security.py — v0.12.1 closes the path-allowlist gap
between v0.10.1's batch-endpoint hardening and the new retry endpoints.

Self-review finding: /api/results/retry + /api/results/failed accepted any
folder or file_path string, mirroring the exact issue v0.10.1 fixed on the
batch endpoints. This verifies the 403 response path + the _coerce_int
crash-proofing on `limit`.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from modules.result_store import ResultStore


@pytest.fixture
def seed_failed_rows():
    """Insert two failed rows under two different paths so tests can
    check that folder filtering + allowlist block work correctly."""
    store = ResultStore()
    try:
        store.mark_failed("/Users/bobo_m3/photos/a.jpg", "under home")
        store.mark_failed("/tmp/outside/b.jpg", "outside home")
    finally:
        store.close()
    yield


# ---------------- GET /api/results/failed ----------------

def test_failed_list_rejects_folder_outside_allowlist(seed_failed_rows, monkeypatch):
    import web_ui
    web_ui._allowed_roots.clear()
    # Force home → a tmp path that doesn't include /Users/bobo_m3
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/nowhere-real")))
    client = web_ui.app.test_client()
    r = client.get("/api/results/failed?folder=/Users/bobo_m3/photos")
    assert r.status_code == 403
    assert r.get_json()["error"] == "folder_not_allowed"


def test_failed_list_accepts_registered_folder(seed_failed_rows, tmp_path, monkeypatch):
    import web_ui
    web_ui._allowed_roots.clear()
    # Seed an extra failed row under tmp_path and register it
    store = ResultStore()
    try:
        store.mark_failed(str(tmp_path / "c.jpg"), "err")
    finally:
        store.close()
    web_ui.register_allowed_root(tmp_path)
    client = web_ui.app.test_client()
    r = client.get(f"/api/results/failed?folder={tmp_path}")
    assert r.status_code == 200
    paths = [i["file_path"] for i in r.get_json()["items"]]
    assert str(tmp_path / "c.jpg") in paths


def test_failed_list_bad_limit_does_not_500():
    """Before v0.12.1, `int(request.args.get('limit', 1000))` crashed
    on 'abc'. Now _coerce_int falls back to default 1000."""
    import web_ui
    client = web_ui.app.test_client()
    r = client.get("/api/results/failed?limit=abc")
    assert r.status_code == 200


# ---------------- POST /api/results/retry ----------------

def test_retry_rejects_folder_outside_allowlist(seed_failed_rows, monkeypatch):
    import web_ui
    web_ui._allowed_roots.clear()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/nowhere-real")))
    client = web_ui.app.test_client()
    r = client.post("/api/results/retry", json={"folder": "/Users/bobo_m3/photos"})
    assert r.status_code == 403
    assert r.get_json()["error"] == "folder_not_allowed"


def test_retry_rejects_file_paths_outside_allowlist(seed_failed_rows, monkeypatch):
    """Even when folder is None, individual file_paths must be within
    the allowlist. Otherwise caller with the session token can clear
    failure markers anywhere on disk (leaking existence info)."""
    import web_ui
    web_ui._allowed_roots.clear()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/nowhere-real")))
    client = web_ui.app.test_client()
    r = client.post("/api/results/retry", json={
        "file_paths": ["/Users/bobo_m3/photos/a.jpg"],
    })
    assert r.status_code == 403
    assert r.get_json()["error"] == "path_not_allowed"


def test_retry_rejects_non_array_file_paths():
    """Defensive: `file_paths: "not_a_list"` was silently iterated as
    characters in older JS clients; force 400 instead."""
    import web_ui
    client = web_ui.app.test_client()
    r = client.post("/api/results/retry", json={"file_paths": "single_string"})
    assert r.status_code == 400
    assert "must be an array" in r.get_json()["error"]


def test_retry_allows_registered_paths(tmp_path):
    import web_ui
    web_ui._allowed_roots.clear()
    web_ui.register_allowed_root(tmp_path)
    store = ResultStore()
    try:
        store.mark_failed(str(tmp_path / "ok.jpg"), "x")
    finally:
        store.close()
    client = web_ui.app.test_client()
    r = client.post("/api/results/retry", json={
        "file_paths": [str(tmp_path / "ok.jpg")],
    })
    assert r.status_code == 200
    assert r.get_json()["cleared"] == 1
