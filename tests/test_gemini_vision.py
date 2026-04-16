"""tests/test_gemini_vision.py"""

import io
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from PIL import Image

from modules.gemini_vision import (
    build_prompt,
    parse_response,
    analyze_photo,
    resize_for_api,
    ANALYSIS_SCHEMA,
    MODEL_MAP,
    CATEGORY_ENUM,
    MOOD_ENUM,
)


def test_model_map_has_lite_and_flash():
    assert "lite" in MODEL_MAP
    assert "flash" in MODEL_MAP
    assert "gemini" in MODEL_MAP["lite"]
    assert "gemini" in MODEL_MAP["flash"]


def test_analysis_schema_has_required_fields():
    required = ["title", "description", "keywords", "category", "subcategory",
                 "scene_type", "mood", "people_count", "identified_people", "ocr_text"]
    for field in required:
        assert field in ANALYSIS_SCHEMA["properties"]


def test_build_prompt_returns_string():
    prompt = build_prompt()
    assert isinstance(prompt, str)
    assert "title" in prompt
    assert "keywords" in prompt
    assert "public figure" in prompt.lower() or "identified_people" in prompt


def test_parse_response_valid_json():
    raw = json.dumps({
        "title": "Test",
        "description": "A test photo",
        "keywords": ["test"],
        "category": "other",
        "subcategory": "",
        "scene_type": "indoor",
        "mood": "neutral",
        "people_count": 0,
        "identified_people": [],
        "ocr_text": [],
    })
    result = parse_response(raw)
    assert result["title"] == "Test"
    assert result["keywords"] == ["test"]


def test_parse_response_handles_missing_fields():
    raw = json.dumps({"title": "Only title"})
    result = parse_response(raw)
    assert result["title"] == "Only title"
    assert result["keywords"] == []
    assert result["identified_people"] == []


def test_parse_response_handles_garbage():
    result = parse_response("not json at all")
    assert result is None


def _create_test_jpg(path, width=100, height=100):
    """Create a valid JPEG file for testing."""
    img = Image.new("RGB", (width, height), color="red")
    img.save(path, format="JPEG")


def test_resize_for_api_small_image():
    """Images smaller than MAX_IMAGE_SIZE should not be resized."""
    img = Image.new("RGB", (1000, 800), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    original = buf.getvalue()
    result = resize_for_api(original)
    assert result == original


def test_resize_for_api_large_image():
    """Images larger than MAX_IMAGE_SIZE should be resized."""
    img = Image.new("RGB", (6000, 4000), color="green")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    result = resize_for_api(buf.getvalue(), max_size=3072)
    resized = Image.open(io.BytesIO(result))
    assert max(resized.size) == 3072
    assert resized.size == (3072, 2048)


def test_category_and_mood_enums():
    assert "ceremony" in CATEGORY_ENUM
    assert "other" in CATEGORY_ENUM
    assert "formal" in MOOD_ENUM
    assert "neutral" in MOOD_ENUM


def test_analyze_photo_calls_gemini(tmp_path):
    img_path = tmp_path / "test.jpg"
    _create_test_jpg(img_path)

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "title": "Test photo",
        "description": "A test",
        "keywords": ["test"],
        "category": "other",
        "subcategory": "",
        "scene_type": "indoor",
        "mood": "neutral",
        "people_count": 0,
        "identified_people": [],
        "ocr_text": [],
    })

    with patch("modules.gemini_vision.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.models.generate_content.return_value = mock_response

        result = analyze_photo(str(img_path), api_key="fake-key", model="lite")

    assert result["title"] == "Test photo"


def test_client_cache_reuses_instance(monkeypatch):
    """Calling _get_client twice with same key returns same instance."""
    from modules import gemini_vision

    created = []

    class FakeClient:
        def __init__(self, api_key):
            created.append(api_key)

    monkeypatch.setattr(gemini_vision.genai, "Client", FakeClient)
    gemini_vision._client_cache.clear()

    c1 = gemini_vision._get_client("key-abc")
    c2 = gemini_vision._get_client("key-abc")
    c3 = gemini_vision._get_client("key-xyz")

    assert c1 is c2
    assert c1 is not c3
    assert created == ["key-abc", "key-xyz"]
