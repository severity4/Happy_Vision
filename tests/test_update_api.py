"""tests/test_update_api.py"""
from unittest.mock import patch

import pytest

from web_ui import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_download_rejected_if_no_update(client):
    with patch("api.update.get_state", return_value={"status": "idle"}):
        r = client.post("/api/update/download")
    assert r.status_code == 400


def test_download_rejected_if_already_downloading(client):
    """Second POST while first is in-flight must return 409, not spawn another thread."""
    state = {"status": "available"}

    # Make the background fn slow so the two requests overlap.
    # Keep state["status"] == "available" so the pre-lock status check
    # passes on r2; the *lock* is what must reject the second request.
    def slow(*_args, **_kwargs):
        import time
        time.sleep(0.5)

    with patch("api.update.get_state", side_effect=lambda: state):
        with patch("api.update.download_and_install", side_effect=slow):
            r1 = client.post("/api/update/download")
            # Second call arrives while first is still sleeping
            r2 = client.post("/api/update/download")

    assert r1.status_code == 200
    assert r2.status_code == 409


def test_status_returns_ready_when_pending_update_exists(client):
    with patch("api.update.get_state", return_value={"status": "ready", "progress": 100}):
        with patch("api.update.get_current_version", return_value="1.0.0"):
            r = client.get("/api/update/status")

    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ready"
    assert data["current_version"] == "1.0.0"
