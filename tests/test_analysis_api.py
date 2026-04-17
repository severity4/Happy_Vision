"""tests/test_analysis_api.py — /api/analysis/* endpoints"""
from unittest.mock import patch

import pytest

from web_ui import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_start_rejects_missing_folder(client):
    r = client.post("/api/analysis/start", json={})
    assert r.status_code == 400
    assert b"folder" in r.data.lower()


def test_start_rejects_missing_api_key(client, monkeypatch):
    """If Gemini API key not configured, /start returns 400."""
    monkeypatch.setattr("api.analysis.load_config",
                        lambda: {"gemini_api_key": "", "model": "lite"})
    r = client.post("/api/analysis/start", json={"folder": "/tmp"})
    assert r.status_code == 400
    assert b"api key" in r.data.lower() or b"API key" in r.data


def test_start_returns_409_if_already_running(client, monkeypatch):
    """Second /start while first is running returns 409."""
    import api.analysis as api_a

    class FakeThread:
        def is_alive(self): return True

    monkeypatch.setattr(api_a, "_pipeline_thread", FakeThread())
    r = client.post("/api/analysis/start", json={"folder": "/tmp"})
    assert r.status_code == 409


def test_pause_without_running_returns_404(client, monkeypatch):
    import api.analysis as api_a
    monkeypatch.setattr(api_a, "_pipeline_state", None)
    r = client.post("/api/analysis/pause")
    assert r.status_code == 404


def test_resume_without_running_returns_404(client, monkeypatch):
    import api.analysis as api_a
    monkeypatch.setattr(api_a, "_pipeline_state", None)
    r = client.post("/api/analysis/resume")
    assert r.status_code == 404


def test_cancel_without_running_returns_404(client, monkeypatch):
    import api.analysis as api_a
    monkeypatch.setattr(api_a, "_pipeline_state", None)
    r = client.post("/api/analysis/cancel")
    assert r.status_code == 404


def test_pause_calls_state_pause(client, monkeypatch):
    import api.analysis as api_a

    calls = {"pause": 0}

    class FakeState:
        def pause(self): calls["pause"] += 1
        def resume(self): pass
        def cancel(self): pass

    monkeypatch.setattr(api_a, "_pipeline_state", FakeState())
    r = client.post("/api/analysis/pause")
    assert r.status_code == 200
    assert calls["pause"] == 1


def test_sse_stream_returns_event_stream_mimetype(client):
    """SSE endpoint must advertise text/event-stream."""
    r = client.get("/api/analysis/stream", buffered=False)
    assert r.status_code == 200
    assert r.mimetype == "text/event-stream"
    r.close()
