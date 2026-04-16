"""tests/test_gemini_vision.py"""

import base64
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from modules.gemini_vision import (
    build_prompt,
    parse_response,
    analyze_photo,
    ANALYSIS_SCHEMA,
    MODEL_MAP,
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


def test_analyze_photo_calls_gemini(tmp_path):
    # Create a tiny test JPG (1x1 pixel)
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(
        b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
        b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t'
        b'\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a'
        b'\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342'
        b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00'
        b'\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00'
        b'\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b'
        b'\xff\xda\x00\x08\x01\x01\x00\x00?\x00T\xdb\x9e\xa7\xa8\xa4'
        b'\xff\xd9'
    )

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
