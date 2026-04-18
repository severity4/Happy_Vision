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


def test_enqueue_requires_folder(client):
    res = client.post("/api/watch/enqueue", json={})
    assert res.status_code == 400
    assert "folder" in res.get_json()["error"]


def test_enqueue_rejects_invalid_folder(client):
    res = client.post("/api/watch/enqueue", json={"folder": "/nonexistent/xyz"})
    assert res.status_code == 400
    assert "not accessible" in res.get_json()["error"]


def test_enqueue_requires_api_key(client, tmp_path):
    with patch("api.watch.load_config", return_value={"gemini_api_key": ""}):
        res = client.post("/api/watch/enqueue", json={"folder": str(tmp_path)})
        assert res.status_code == 400
        assert "API key" in res.get_json()["error"]


def test_enqueue_autostarts_watcher_when_stopped(client, tmp_path):
    """If watcher is stopped, enqueue should auto-start it using configured folder."""
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    enqueue_dir = tmp_path / "enqueue"
    enqueue_dir.mkdir()
    (enqueue_dir / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    with patch("api.watch.load_config", return_value={
        "gemini_api_key": "test-key",
        "watch_folder": str(watch_dir),
        "watch_concurrency": 1,
        "watch_interval": 3600,
        "model": "lite",
    }):
        with patch("modules.folder_watcher.load_config", return_value={
            "gemini_api_key": "test-key",
            "watch_concurrency": 1,
            "watch_interval": 3600,
            "model": "lite",
        }):
            with patch("modules.folder_watcher.has_happy_vision_tag", return_value=False):
                with patch("modules.folder_watcher.file_size_stable", return_value=True):
                    with patch("modules.folder_watcher.analyze_photo", return_value=({"title": "t"}, {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "model": "gemini-2.5-flash-lite"})):
                        fake_batch = MagicMock()
                        fake_batch.write.return_value = True
                        with patch("modules.folder_watcher.ExiftoolBatch", return_value=fake_batch):
                            res = client.post("/api/watch/enqueue", json={"folder": str(enqueue_dir)})
                            assert res.status_code == 200
                            data = res.get_json()
                            assert "enqueued" in data
                            assert "skipped" in data
                            # Watcher should be running now
                            import api.watch as watch_mod
                            assert watch_mod._watcher.state == "watching"


def test_enqueue_returns_counts(client, tmp_path):
    """Enqueue should report enqueued + skipped counts from the specified folder."""
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    enqueue_dir = tmp_path / "enqueue"
    enqueue_dir.mkdir()
    (enqueue_dir / "new.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    with patch("api.watch.load_config", return_value={
        "gemini_api_key": "test-key",
        "watch_folder": str(watch_dir),
        "watch_concurrency": 1,
        "watch_interval": 3600,
        "model": "lite",
    }):
        with patch("modules.folder_watcher.load_config", return_value={
            "gemini_api_key": "test-key",
            "watch_concurrency": 1,
            "watch_interval": 3600,
            "model": "lite",
        }):
            with patch("modules.folder_watcher.has_happy_vision_tag", return_value=False):
                with patch("modules.folder_watcher.file_size_stable", return_value=True):
                    with patch("modules.folder_watcher.analyze_photo", return_value=({"title": "t"}, {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "model": "gemini-2.5-flash-lite"})):
                        fake_batch = MagicMock()
                        fake_batch.write.return_value = True
                        with patch("modules.folder_watcher.ExiftoolBatch", return_value=fake_batch):
                            res = client.post("/api/watch/enqueue", json={"folder": str(enqueue_dir)})
                            assert res.status_code == 200
                            data = res.get_json()
                            assert data["enqueued"] == 1
                            assert data["skipped"] == 0
