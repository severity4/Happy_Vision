"""tests/test_batch_security.py — v0.10.1 hardening: path allowlist on batch
endpoints + job-ownership checks on cancel/delete/get.

Security-review findings:
  HIGH  — /api/batch/submit + /api/batch/estimate trusted any folder
  MED   — cancel_job / delete_job took any job_id and forwarded to Gemini
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def allowed_folder(tmp_path, monkeypatch):
    """Create a folder inside the user's home (auto-allowed by
    _path_is_allowed). We can't literally write to real home in tests, so
    monkeypatch Path.home() to the tmp root."""
    home = tmp_path / "home"
    home.mkdir()
    folder = home / "photos"
    folder.mkdir()
    for i in range(2):
        Image.new("RGB", (60, 40), (i * 80, 100, 200)).save(folder / f"p{i}.jpg")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return folder


@pytest.fixture
def disallowed_folder(tmp_path):
    """A folder outside home + outside any registered allowlist."""
    outside = tmp_path / "somewhere_else"
    outside.mkdir()
    (outside / "secret.jpg").write_bytes(b"pretend jpg")
    return outside


# ---------------- folder allowlist ----------------

def test_estimate_rejects_folder_outside_allowlist(disallowed_folder):
    import web_ui
    # Make sure nothing was registered for this tmp path.
    web_ui._allowed_roots.clear()
    client = web_ui.app.test_client()
    r = client.get(f"/api/batch/estimate?folder={disallowed_folder}")
    assert r.status_code == 403
    body = r.get_json()
    assert body["error"] == "folder_not_allowed"
    assert "允許清單" in body["message"]


def test_submit_rejects_folder_outside_allowlist(disallowed_folder):
    import web_ui
    web_ui._allowed_roots.clear()
    client = web_ui.app.test_client()
    r = client.post("/api/batch/submit", json={"folder": str(disallowed_folder)})
    assert r.status_code == 403
    assert r.get_json()["error"] == "folder_not_allowed"


def test_estimate_accepts_registered_folder(disallowed_folder):
    """After register_allowed_root is called (e.g. via /api/watch/start),
    the formerly-blocked path must pass."""
    import web_ui
    web_ui._allowed_roots.clear()
    web_ui.register_allowed_root(disallowed_folder)
    client = web_ui.app.test_client()
    r = client.get(f"/api/batch/estimate?folder={disallowed_folder}")
    # 200 with estimate payload, not 403.
    assert r.status_code == 200
    assert "photo_count" in r.get_json()


def test_estimate_path_traversal_dotdot_rejected(tmp_path):
    import web_ui
    web_ui._allowed_roots.clear()
    # Register a legit subdir; try to escape with ..
    legit = tmp_path / "legit"
    legit.mkdir()
    web_ui.register_allowed_root(legit)
    client = web_ui.app.test_client()
    # ../ would land outside `legit` — should be blocked
    r = client.get(f"/api/batch/estimate?folder={legit}/..")
    assert r.status_code == 403


# ---------------- int coercion ----------------

def test_estimate_bad_image_max_size_does_not_500(allowed_folder):
    """v0.10.1 wrapped int() with _coerce_int — garbage params fall back
    to config default instead of crashing."""
    import web_ui
    web_ui._allowed_roots.clear()
    web_ui.register_allowed_root(allowed_folder)
    client = web_ui.app.test_client()
    r = client.get(f"/api/batch/estimate?folder={allowed_folder}&image_max_size=abc")
    assert r.status_code == 200  # falls back, does NOT 500
    assert "photo_count" in r.get_json()


# ---------------- job ownership ----------------

def test_cancel_unknown_job_returns_404():
    import web_ui
    client = web_ui.app.test_client()
    r = client.post("/api/batch/jobs/batches/fake-id-no-such-thing/cancel")
    assert r.status_code == 404
    assert r.get_json()["error"] == "not_found"


def test_delete_unknown_job_returns_404():
    import web_ui
    client = web_ui.app.test_client()
    r = client.delete("/api/batch/jobs/batches/also-not-real")
    assert r.status_code == 404


def test_cancel_known_job_does_not_404(tmp_path, monkeypatch):
    """When the job exists locally, the 404 guard lets the request through
    (it still fails on the Gemini side with no real API key, but the
    endpoint doesn't short-circuit on ownership)."""
    import web_ui
    from modules.result_store import ResultStore
    # Point the store at a throwaway DB by setting HAPPY_VISION_HOME (conftest
    # already does this autouse).
    store = ResultStore()
    try:
        store.create_batch_job(
            job_id="batches/owned-by-me",
            folder="/tmp",
            model="lite",
            items=[("p0", "/tmp/a.jpg")],
            input_file_id="files/x",
            payload_bytes=1,
        )
    finally:
        store.close()
    # Stub out the real Gemini call so we don't hit the network.
    from modules import gemini_batch
    monkeypatch.setattr(gemini_batch, "cancel_job", lambda *_a, **_k: True)
    # Also stub the API key check — set a fake key in config
    from modules import config, secret_store
    secret_store.set_key("AIzaStub")
    client = web_ui.app.test_client()
    r = client.post("/api/batch/jobs/batches/owned-by-me/cancel")
    assert r.status_code == 200
    assert r.get_json()["cancelled"] is True
