"""tests/hardening/test_export_save_to_downloads.py

Hardening: POST /api/export/save/<kind> writes report to ~/Downloads
and returns the absolute path. Required because pywebview's WKWebView
doesn't reliably trigger the <a download> blob-download flow — the
click either silently fails or navigates away with no back button.

This endpoint sidesteps WKWebView entirely: backend does the file
write; frontend just shows a toast with the saved path.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from api import export as api_export
from modules.result_store import ResultStore
from web_ui import app as _app


_RESULT = {
    "file_path": "/tmp/x.jpg",
    "title": "t", "description": "d",
    "keywords": ["k"], "category": "other",
    "subcategory": "", "scene_type": "indoor",
    "mood": "neutral", "people_count": 0,
    "identified_people": [], "ocr_text": [],
}


@pytest.fixture
def fake_downloads(monkeypatch, tmp_path):
    """Redirect _downloads_dir to a tmp path so tests don't pollute the
    real ~/Downloads folder."""
    d = tmp_path / "Downloads"
    d.mkdir()
    monkeypatch.setattr(api_export, "_downloads_dir", lambda: d)
    return d


@pytest.fixture
def seeded_store(monkeypatch, tmp_path):
    """Put one completed result in the store the endpoints will read."""
    db_path = tmp_path / "results.db"
    store = ResultStore(db_path)
    store.save_result(
        "/tmp/x.jpg",
        {k: v for k, v in _RESULT.items() if k != "file_path"},
        usage={"input_tokens": 10, "output_tokens": 5,
               "total_tokens": 15, "model": "gemini-2.5-flash-lite"},
        cost_usd=0.001,
    )
    store.close()

    # Point ResultStore() (zero-arg) at our seeded DB
    def _factory(*args, **kwargs):
        return ResultStore(db_path)
    monkeypatch.setattr(api_export, "ResultStore", _factory)
    return db_path


@pytest.fixture
def client():
    _app.config["TESTING"] = True
    with _app.test_client() as c:
        yield c


# ---------- core: each kind saves to Downloads with correct shape ----------

def test_save_csv_writes_file_and_returns_path(
    client, fake_downloads, seeded_store,
):
    r = client.post("/api/export/save/csv")
    assert r.status_code == 200
    body = r.get_json()
    assert "saved" in body
    saved = Path(body["saved"])
    assert saved.exists()
    assert saved.parent == fake_downloads
    assert saved.suffix == ".csv"
    # Must actually contain the seeded row
    assert "/tmp/x.jpg" in saved.read_text(encoding="utf-8")


def test_save_json_produces_valid_json(
    client, fake_downloads, seeded_store,
):
    r = client.post("/api/export/save/json")
    assert r.status_code == 200
    saved = Path(r.get_json()["saved"])
    assert saved.exists()
    assert saved.suffix == ".json"
    import json
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert any(row.get("title") == "t" for row in data)


def test_save_pdf_produces_valid_pdf(
    client, fake_downloads, seeded_store,
):
    r = client.post("/api/export/save/pdf")
    assert r.status_code == 200
    saved = Path(r.get_json()["saved"])
    assert saved.exists()
    assert saved.suffix == ".pdf"
    assert saved.read_bytes().startswith(b"%PDF")


def test_save_diagnostics_produces_valid_zip(
    client, fake_downloads, seeded_store,
):
    r = client.post("/api/export/save/diagnostics")
    assert r.status_code == 200
    saved = Path(r.get_json()["saved"])
    assert saved.exists()
    assert saved.suffix == ".zip"
    # Must be a valid zip containing at least config.json + events.json
    with zipfile.ZipFile(saved) as zf:
        names = zf.namelist()
        assert "config.json" in names
        assert "events.json" in names


# ---------- 404 when there's no data ----------

def test_save_csv_returns_404_on_empty_store(
    client, fake_downloads, monkeypatch, tmp_path,
):
    empty_db = tmp_path / "empty.db"
    def _factory(*args, **kwargs):
        return ResultStore(empty_db)
    monkeypatch.setattr(api_export, "ResultStore", _factory)

    r = client.post("/api/export/save/csv")
    assert r.status_code == 404
    body = r.get_json()
    assert "error" in body


def test_save_pdf_returns_404_on_empty_store(
    client, fake_downloads, monkeypatch, tmp_path,
):
    empty_db = tmp_path / "empty.db"
    def _factory(*args, **kwargs):
        return ResultStore(empty_db)
    monkeypatch.setattr(api_export, "ResultStore", _factory)

    r = client.post("/api/export/save/pdf")
    assert r.status_code == 404


def test_save_unknown_format_returns_400(client, fake_downloads):
    r = client.post("/api/export/save/docx")
    assert r.status_code == 400


# ---------- filename collision handling ----------

def test_save_avoids_overwriting_existing_file(
    client, fake_downloads, seeded_store,
):
    """Two quick saves in the same second must produce two files, not
    clobber the first. The `-1` / `-2` suffix logic ensures this."""
    r1 = client.post("/api/export/save/csv")
    r2 = client.post("/api/export/save/csv")
    assert r1.status_code == 200
    assert r2.status_code == 200
    saved1 = Path(r1.get_json()["saved"])
    saved2 = Path(r2.get_json()["saved"])
    # Different paths even if timestamp happened to be identical
    if saved1.name == saved2.name:
        # Same timestamp — the second should have a suffix
        pytest.fail("save_bytes did not dedupe: both files collided on name")
    # Both files present
    assert saved1.exists()
    assert saved2.exists()
