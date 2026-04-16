"""tests/test_config.py"""

import json
from pathlib import Path

from modules.config import load_config, save_config, get_config_dir, DEFAULT_CONFIG


def test_default_config_has_required_keys():
    assert "gemini_api_key" in DEFAULT_CONFIG
    assert "model" in DEFAULT_CONFIG
    assert "concurrency" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["model"] == "lite"
    assert DEFAULT_CONFIG["concurrency"] == 5


def test_get_config_dir_creates_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".happy-vision"))
    config_dir = get_config_dir()
    assert config_dir.exists()
    assert config_dir.name == ".happy-vision"


def test_load_config_returns_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".happy-vision"))
    config = load_config()
    assert config["model"] == "lite"
    assert config["gemini_api_key"] == ""


def test_save_and_load_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".happy-vision"))
    config = load_config()
    config["gemini_api_key"] = "test-key-123"
    config["model"] = "flash"
    save_config(config)

    loaded = load_config()
    assert loaded["gemini_api_key"] == "test-key-123"
    assert loaded["model"] == "flash"


def test_load_config_merges_new_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".happy-vision"))
    config_dir = tmp_path / ".happy-vision"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(json.dumps({"gemini_api_key": "k", "model": "lite"}))

    config = load_config()
    assert config["concurrency"] == 5  # filled from defaults
    assert config["gemini_api_key"] == "k"  # preserved from file
