"""tests/test_throughput.py — v0.5.1 throughput config (RPM + image_max_size)"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from modules import rate_limiter
from modules.config import DEFAULT_CONFIG


# ---------- rate_limiter.configure ----------

def test_configure_replaces_default_limiter():
    rate_limiter.configure(60)
    before = rate_limiter.default_limiter
    assert before.rate_per_minute == 60
    rate_limiter.configure(1500)
    after = rate_limiter.default_limiter
    assert after is not before
    assert after.rate_per_minute == 1500


def test_configure_is_idempotent_at_same_rate():
    rate_limiter.configure(1000)
    a = rate_limiter.default_limiter
    rate_limiter.configure(1000)
    assert rate_limiter.default_limiter is a, "same-rate configure should be a no-op"


def test_configure_clamps_low():
    rate_limiter.configure(0)
    assert rate_limiter.default_limiter.rate_per_minute == 1
    rate_limiter.configure(-100)
    assert rate_limiter.default_limiter.rate_per_minute == 1


def test_configure_clamps_high():
    rate_limiter.configure(50000)
    assert rate_limiter.default_limiter.rate_per_minute == 5000


def test_gemini_vision_reads_limiter_via_module():
    """gemini_vision must import the module, not the bound attribute, so
    runtime configure() swaps affect subsequent analyze_photo calls."""
    import modules.gemini_vision as gv
    # The source should reference `rate_limiter.default_limiter`, not a
    # directly bound `default_limiter` — confirm by checking the module dict.
    assert not hasattr(gv, "default_limiter"), (
        "gemini_vision bound `default_limiter` at import time; configure() "
        "swaps won't be visible to live workers"
    )


# ---------- DEFAULT_CONFIG ----------

def test_default_config_has_rate_limit_rpm():
    assert DEFAULT_CONFIG["rate_limit_rpm"] == 60


def test_default_config_has_image_max_size():
    assert DEFAULT_CONFIG["image_max_size"] == 3072


# ---------- analyze_photo accepts max_size ----------

def test_analyze_photo_accepts_max_size(tmp_path, monkeypatch):
    """analyze_photo(max_size=...) flows into resize_for_api."""
    from modules import gemini_vision
    from PIL import Image
    img_path = tmp_path / "test.jpg"
    Image.new("RGB", (100, 100), color="white").save(img_path, "JPEG")

    captured = {}
    orig_resize = gemini_vision.resize_for_api
    def _spy_resize(photo_bytes, max_size=gemini_vision.DEFAULT_MAX_IMAGE_SIZE):
        captured["max_size"] = max_size
        return orig_resize(photo_bytes, max_size=max_size)
    monkeypatch.setattr(gemini_vision, "resize_for_api", _spy_resize)
    monkeypatch.setattr(rate_limiter.default_limiter, "acquire",
                        lambda timeout=None: True)

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "title": "t", "description": "", "keywords": [],
        "category": "other", "scene_type": "indoor",
        "mood": "neutral", "people_count": 0,
    })
    mock_response.usage_metadata.prompt_token_count = 100
    mock_response.usage_metadata.candidates_token_count = 20
    mock_response.usage_metadata.total_token_count = 120

    with patch("modules.gemini_vision.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.models.generate_content.return_value = mock_response
        result, usage = gemini_vision.analyze_photo(
            str(img_path), api_key="fake", model="lite", max_size=1536,
        )

    assert result is not None
    assert captured["max_size"] == 1536


def test_analyze_photo_defaults_to_3072_when_max_size_omitted(tmp_path, monkeypatch):
    from modules import gemini_vision
    from PIL import Image
    img_path = tmp_path / "test.jpg"
    Image.new("RGB", (100, 100), color="white").save(img_path, "JPEG")

    captured = {}
    orig_resize = gemini_vision.resize_for_api
    def _spy_resize(photo_bytes, max_size=gemini_vision.DEFAULT_MAX_IMAGE_SIZE):
        captured["max_size"] = max_size
        return orig_resize(photo_bytes, max_size=max_size)
    monkeypatch.setattr(gemini_vision, "resize_for_api", _spy_resize)
    monkeypatch.setattr(rate_limiter.default_limiter, "acquire",
                        lambda timeout=None: True)

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "title": "t", "description": "", "keywords": [],
        "category": "other", "scene_type": "indoor",
        "mood": "neutral", "people_count": 0,
    })
    mock_response.usage_metadata.prompt_token_count = 100
    mock_response.usage_metadata.candidates_token_count = 20

    with patch("modules.gemini_vision.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.models.generate_content.return_value = mock_response
        gemini_vision.analyze_photo(str(img_path), api_key="fake", model="lite")

    assert captured["max_size"] == 3072


# ---------- /api/settings API ----------

def _mock_client():
    import web_ui
    web_ui.app.config["TESTING"] = True
    return web_ui.app.test_client()


def _with_token(app_client, path, **kwargs):
    """Attach the session auth token to a test-client call."""
    from modules.auth import SESSION_TOKEN
    headers = kwargs.pop("headers", {})
    headers["X-HV-Token"] = SESSION_TOKEN
    headers["Host"] = "127.0.0.1:8081"
    return app_client.open(path, headers=headers, **kwargs)


def test_settings_api_accepts_rate_limit_rpm(monkeypatch, tmp_path):
    """PUT /api/settings with rate_limit_rpm saves AND reconfigures the limiter."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    # Reset the limiter to a known value
    rate_limiter.configure(60)
    assert rate_limiter.default_limiter.rate_per_minute == 60

    client = _mock_client()
    res = _with_token(client, "/api/settings", method="PUT",
                      json={"rate_limit_rpm": 1500})
    assert res.status_code == 200
    assert rate_limiter.default_limiter.rate_per_minute == 1500


def test_settings_api_clamps_rate_limit_rpm(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    rate_limiter.configure(60)
    client = _mock_client()
    res = _with_token(client, "/api/settings", method="PUT",
                      json={"rate_limit_rpm": 999999})
    assert res.status_code == 200
    assert rate_limiter.default_limiter.rate_per_minute == 5000


def test_settings_api_rejects_invalid_image_max_size(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    client = _mock_client()
    res = _with_token(client, "/api/settings", method="PUT",
                      json={"image_max_size": 999})
    assert res.status_code == 400


def test_settings_api_accepts_valid_image_max_size(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    client = _mock_client()
    res = _with_token(client, "/api/settings", method="PUT",
                      json={"image_max_size": 1536})
    assert res.status_code == 200

    # And GET returns what we saved
    get_res = _with_token(client, "/api/settings")
    assert get_res.status_code == 200
    data = json.loads(get_res.data)
    assert data["image_max_size"] == 1536
