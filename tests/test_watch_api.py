"""tests/test_watch_api.py — Watch API integration tests"""

import json
from unittest.mock import patch, MagicMock

import pytest

from web_ui import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_watcher():
    """Reset the global watcher between tests."""
    import api.watch as watch_mod
    watch_mod._watcher = None
    yield
    if watch_mod._watcher and watch_mod._watcher.state != "stopped":
        watch_mod._watcher.stop()
    watch_mod._watcher = None


def test_status_returns_stopped(client):
    res = client.get("/api/watch/status")
    data = res.get_json()
    assert data["status"] == "stopped"


def test_start_requires_folder(client):
    with patch("api.watch.load_config", return_value={"gemini_api_key": "key", "watch_folder": ""}):
        res = client.post("/api/watch/start", json={})
        assert res.status_code == 400


def test_start_requires_api_key(client):
    with patch("api.watch.load_config", return_value={"gemini_api_key": "", "watch_folder": "/tmp"}):
        res = client.post("/api/watch/start", json={"folder": "/tmp"})
        assert res.status_code == 400
        assert "API key" in res.get_json()["error"]


def test_start_with_valid_folder(client, tmp_path):
    with patch("api.watch.load_config", return_value={
        "gemini_api_key": "test-key",
        "watch_folder": "",
        "watch_concurrency": 1,
        "watch_interval": 60,
        "model": "lite",
    }):
        with patch("api.watch.save_config"):
            with patch("modules.folder_watcher.load_config", return_value={
                "gemini_api_key": "test-key",
                "watch_concurrency": 1,
                "watch_interval": 60,
                "model": "lite",
            }):
                res = client.post("/api/watch/start", json={"folder": str(tmp_path)})
                data = res.get_json()
                assert res.status_code == 200
                assert data["status"] == "watching"


def test_start_already_watching_returns_409(client, tmp_path):
    with patch("api.watch.load_config", return_value={
        "gemini_api_key": "test-key",
        "watch_folder": "",
        "watch_concurrency": 1,
        "watch_interval": 60,
        "model": "lite",
    }):
        with patch("api.watch.save_config"):
            with patch("modules.folder_watcher.load_config", return_value={
                "gemini_api_key": "test-key",
                "watch_concurrency": 1,
                "watch_interval": 60,
                "model": "lite",
            }):
                client.post("/api/watch/start", json={"folder": str(tmp_path)})
                res = client.post("/api/watch/start", json={"folder": str(tmp_path)})
                assert res.status_code == 409


def test_pause_not_watching_returns_409(client):
    res = client.post("/api/watch/pause")
    assert res.status_code == 409


def test_resume_not_paused_returns_409(client):
    res = client.post("/api/watch/resume")
    assert res.status_code == 409


def test_stop_returns_stopped(client):
    with patch("api.watch.load_config", return_value={}):
        with patch("api.watch.save_config"):
            res = client.post("/api/watch/stop")
            assert res.get_json()["status"] == "stopped"


def test_update_concurrency(client):
    with patch("api.watch.load_config", return_value={"watch_concurrency": 1}):
        with patch("api.watch.save_config"):
            res = client.post("/api/watch/concurrency", json={"concurrency": 5})
            assert res.status_code == 200
            assert res.get_json()["concurrency"] == 5


def test_update_concurrency_clamped(client):
    with patch("api.watch.load_config", return_value={"watch_concurrency": 1}):
        with patch("api.watch.save_config"):
            res = client.post("/api/watch/concurrency", json={"concurrency": 99})
            assert res.get_json()["concurrency"] == 10


def test_recent_returns_list(client):
    res = client.get("/api/watch/recent?limit=5")
    assert res.status_code == 200
    assert isinstance(res.get_json(), list)
