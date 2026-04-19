"""tests/test_rating_filter.py — v0.8.0 Lightroom rating pre-filter"""

from unittest.mock import MagicMock

from modules.metadata_writer import read_rating_batch
from modules.config import DEFAULT_CONFIG


def test_default_config_has_min_rating_zero():
    assert DEFAULT_CONFIG["min_rating"] == 0


def test_read_rating_returns_int_for_lightroom_rated_photo():
    batch = MagicMock()
    batch.read_json.return_value = {"Rating": 4}
    assert read_rating_batch(batch, "/photos/a.jpg") == 4


def test_read_rating_handles_string_value():
    batch = MagicMock()
    batch.read_json.return_value = {"Rating": "3"}
    assert read_rating_batch(batch, "/photos/a.jpg") == 3


def test_read_rating_clamps_to_0_5():
    batch = MagicMock()
    batch.read_json.return_value = {"Rating": 7}
    assert read_rating_batch(batch, "/photos/a.jpg") == 5
    batch.read_json.return_value = {"Rating": -2}
    assert read_rating_batch(batch, "/photos/a.jpg") == 0


def test_read_rating_returns_0_when_absent():
    batch = MagicMock()
    batch.read_json.return_value = {}
    assert read_rating_batch(batch, "/photos/a.jpg") == 0


def test_read_rating_returns_0_when_null():
    batch = MagicMock()
    batch.read_json.return_value = {"Rating": None}
    assert read_rating_batch(batch, "/photos/a.jpg") == 0


def test_read_rating_returns_0_for_malformed_input():
    batch = MagicMock()
    batch.read_json.return_value = {"Rating": "four"}
    assert read_rating_batch(batch, "/photos/a.jpg") == 0


def test_read_rating_returns_0_when_batch_returns_non_dict():
    batch = MagicMock()
    batch.read_json.return_value = None
    assert read_rating_batch(batch, "/photos/a.jpg") == 0
    batch.read_json.return_value = "unexpected"
    assert read_rating_batch(batch, "/photos/a.jpg") == 0


# --- settings API integration ---

def test_settings_accepts_min_rating_0_to_5(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    import web_ui
    from modules.auth import SESSION_TOKEN
    c = web_ui.app.test_client()

    for r in [0, 1, 2, 3, 4, 5]:
        res = c.put("/api/settings", json={"min_rating": r},
                    headers={"X-HV-Token": SESSION_TOKEN, "Host": "127.0.0.1:8081"})
        assert res.status_code == 200, f"min_rating={r} should be accepted"


def test_settings_clamps_min_rating_out_of_range(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    import web_ui
    from modules.auth import SESSION_TOKEN
    c = web_ui.app.test_client()

    res = c.put("/api/settings", json={"min_rating": 99},
                headers={"X-HV-Token": SESSION_TOKEN, "Host": "127.0.0.1:8081"})
    assert res.status_code == 200
    get_res = c.get("/api/settings",
                    headers={"X-HV-Token": SESSION_TOKEN, "Host": "127.0.0.1:8081"})
    import json
    d = json.loads(get_res.data)
    assert d["min_rating"] == 5, "out-of-range should clamp to 5"

    res = c.put("/api/settings", json={"min_rating": -1},
                headers={"X-HV-Token": SESSION_TOKEN, "Host": "127.0.0.1:8081"})
    assert res.status_code == 200
    d = json.loads(c.get("/api/settings",
                         headers={"X-HV-Token": SESSION_TOKEN, "Host": "127.0.0.1:8081"}).data)
    assert d["min_rating"] == 0
