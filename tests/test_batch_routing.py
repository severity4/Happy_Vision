"""tests/test_batch_routing.py — pipeline.route_mode decision matrix
and api/settings.py batch_mode validation."""
from __future__ import annotations

import pytest

from modules.pipeline import route_mode


@pytest.mark.parametrize("mode,count,threshold,expected", [
    ("off", 10, 5, "realtime"),
    ("off", 10_000, 5, "realtime"),
    ("always", 1, 500, "batch"),
    ("always", 0, 500, "batch"),
    ("auto", 500, 500, "batch"),
    ("auto", 499, 500, "realtime"),
    ("auto", 5_000, 500, "batch"),
    ("AUTO", 600, 500, "batch"),  # case insensitive
    ("", 10, 5, "realtime"),
    (None, 10, 5, "realtime"),
])
def test_route_mode_decision_matrix(mode, count, threshold, expected):
    assert route_mode(mode, count, threshold) == expected


def test_route_mode_defensive_threshold_zero():
    # threshold=0 would make auto fire on any count; we clamp to min=1.
    assert route_mode("auto", 1, 0) == "batch"


# ---------------- settings API -----------------

def test_settings_api_accepts_valid_batch_mode():
    import web_ui
    client = web_ui.app.test_client()
    r = client.put("/api/settings", json={"batch_mode": "auto"})
    assert r.status_code == 200
    r = client.get("/api/settings")
    assert r.get_json()["batch_mode"] == "auto"


def test_settings_api_rejects_invalid_batch_mode():
    import web_ui
    client = web_ui.app.test_client()
    r = client.put("/api/settings", json={"batch_mode": "aggressive"})
    assert r.status_code == 400
    assert "batch_mode" in r.get_json()["error"]


def test_settings_api_clamps_batch_threshold():
    import web_ui
    client = web_ui.app.test_client()
    r = client.put("/api/settings", json={"batch_threshold": 99_999_999})
    assert r.status_code == 200
    r = client.get("/api/settings")
    assert r.get_json()["batch_threshold"] == 50_000

    r = client.put("/api/settings", json={"batch_threshold": -5})
    assert r.status_code == 200
    r = client.get("/api/settings")
    assert r.get_json()["batch_threshold"] == 1
