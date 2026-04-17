"""tests/test_export_api.py — /api/export/{csv,json}"""
import pytest

from web_ui import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_export_csv_404_when_empty(client, monkeypatch, tmp_path):
    """CSV export returns 404 if no results exist."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    r = client.get("/api/export/csv")
    assert r.status_code == 404


def test_export_json_404_when_empty(client, monkeypatch, tmp_path):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    r = client.get("/api/export/json")
    assert r.status_code == 404


def test_export_unknown_format_400(client, monkeypatch, tmp_path):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    # Seed one result so we skip the 404 path
    from modules.result_store import ResultStore
    with ResultStore() as store:
        store.save_result("/p.jpg", {"title": "T", "keywords": [],
                                      "description": "", "category": "other",
                                      "scene_type": "indoor", "mood": "neutral",
                                      "people_count": 0})
    r = client.get("/api/export/xml")
    assert r.status_code == 400


def test_export_csv_returns_attachment(client, monkeypatch, tmp_path):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    from modules.result_store import ResultStore
    with ResultStore() as store:
        store.save_result("/p.jpg", {"title": "T", "keywords": ["a"],
                                      "description": "d", "category": "other",
                                      "scene_type": "indoor", "mood": "neutral",
                                      "people_count": 1})
    r = client.get("/api/export/csv")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    assert "happy_vision_report.csv" in r.headers.get("Content-Disposition", "")
    assert b"T" in r.data  # title appears in CSV


def test_export_json_returns_attachment(client, monkeypatch, tmp_path):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    from modules.result_store import ResultStore
    with ResultStore() as store:
        store.save_result("/p.jpg", {"title": "JsonTitle", "keywords": [],
                                      "description": "", "category": "other",
                                      "scene_type": "indoor", "mood": "neutral",
                                      "people_count": 0})
    r = client.get("/api/export/json")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    import json as _json
    data = _json.loads(r.data)
    assert any(item.get("title") == "JsonTitle" for item in data)
