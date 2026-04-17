"""tests/test_config.py"""

import json
from pathlib import Path

from modules import secret_store
from modules.config import load_config, save_config, get_config_dir, DEFAULT_CONFIG


def _mock_secret_store(monkeypatch, initial=""):
    """Install in-memory fakes for secret_store so tests never touch real Keychain."""
    store = {"k": initial}
    monkeypatch.setattr(secret_store, "get_key", lambda: store["k"])
    monkeypatch.setattr(secret_store, "set_key", lambda k: store.update({"k": k}))
    monkeypatch.setattr(secret_store, "clear_key", lambda: store.update({"k": ""}))
    return store


def test_default_config_has_required_keys():
    # gemini_api_key intentionally NOT in DEFAULT_CONFIG — it lives in Keychain
    assert "gemini_api_key" not in DEFAULT_CONFIG
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
    _mock_secret_store(monkeypatch)
    config = load_config()
    assert config["model"] == "lite"
    assert config["gemini_api_key"] == ""


def test_save_and_load_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".happy-vision"))
    _mock_secret_store(monkeypatch)
    config = load_config()
    config["gemini_api_key"] = "test-key-123"
    config["model"] = "flash"
    save_config(config)

    loaded = load_config()
    assert loaded["gemini_api_key"] == "test-key-123"
    assert loaded["model"] == "flash"


def test_load_config_merges_new_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path / ".happy-vision"))
    _mock_secret_store(monkeypatch)
    config_dir = tmp_path / ".happy-vision"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(json.dumps({"gemini_api_key": "k", "model": "lite"}))

    config = load_config()
    assert config["concurrency"] == 5  # filled from defaults
    assert config["gemini_api_key"] == "k"  # preserved from file (migrated into mocked Keychain)


def test_load_config_pulls_api_key_from_secret_store(monkeypatch, tmp_path):
    from modules import config, secret_store

    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    monkeypatch.setattr(secret_store, "get_key", lambda: "key-from-keychain")

    cfg = config.load_config()
    assert cfg["gemini_api_key"] == "key-from-keychain"


def test_save_config_stores_key_to_secret_store_not_json(monkeypatch, tmp_path):
    from modules import config, secret_store

    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    saved = {}
    monkeypatch.setattr(secret_store, "set_key", lambda k: saved.update({"k": k}))
    monkeypatch.setattr(secret_store, "get_key", lambda: saved.get("k", ""))

    cfg = {"gemini_api_key": "new-key", "model": "lite"}
    config.save_config(cfg)

    # Check JSON on disk does NOT contain the key
    import json
    raw = json.loads((tmp_path / "config.json").read_text())
    assert "gemini_api_key" not in raw
    assert raw.get("model") == "lite"

    # Check key landed in secret_store
    assert saved["k"] == "new-key"


def test_migrate_plaintext_key_from_json_to_keychain(monkeypatch, tmp_path):
    """If config.json has a key and Keychain is empty, migrate and scrub JSON."""
    from modules import config, secret_store
    import json

    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    # Seed an old-style config.json with plaintext key
    (tmp_path / "config.json").write_text(json.dumps({
        "gemini_api_key": "legacy-key",
        "model": "lite",
    }))

    store = {"k": ""}
    monkeypatch.setattr(secret_store, "get_key", lambda: store["k"])
    monkeypatch.setattr(secret_store, "set_key", lambda k: store.update({"k": k}))

    cfg = config.load_config()

    assert cfg["gemini_api_key"] == "legacy-key"
    # Keychain now has it
    assert store["k"] == "legacy-key"
    # JSON no longer has it
    raw = json.loads((tmp_path / "config.json").read_text())
    assert "gemini_api_key" not in raw
