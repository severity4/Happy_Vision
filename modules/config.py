"""modules/config.py — Config load/save for Happy Vision

The Gemini API key is stored in macOS Keychain (via modules.secret_store);
never in config.json. load_config() returns a dict with `gemini_api_key`
populated from Keychain for backward compatibility with callers.
"""

import json
import os
from pathlib import Path

from modules import secret_store

DEFAULT_CONFIG = {
    "model": "lite",
    "concurrency": 5,
    "write_metadata": False,
    "skip_existing": False,
    "watch_folder": "",
    "watch_enabled": False,
    "watch_concurrency": 1,
    "watch_interval": 10,
}


def get_config_dir() -> Path:
    """Return (and create) the Happy Vision config directory."""
    base = os.environ.get("HAPPY_VISION_HOME", str(Path.home() / ".happy-vision"))
    config_dir = Path(base)
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def load_config() -> dict:
    """Load config; merge API key from Keychain. Migrates legacy plaintext
    key out of config.json on first encounter."""
    config_path = get_config_dir() / "config.json"
    config = dict(DEFAULT_CONFIG)
    legacy_key = None

    if config_path.exists():
        with open(config_path) as f:
            stored = json.load(f)
        legacy_key = stored.pop("gemini_api_key", None)
        config.update(stored)

    # Migration: if JSON had a plaintext key and Keychain is empty, move it
    keychain_key = secret_store.get_key()
    if legacy_key and not keychain_key:
        secret_store.set_key(legacy_key)
        keychain_key = legacy_key
        # Rewrite config.json without the key
        _save_raw(config_path, config)

    config["gemini_api_key"] = keychain_key
    return config


def save_config(config: dict) -> None:
    """Save config to disk. API key goes to Keychain; JSON gets everything else."""
    config_path = get_config_dir() / "config.json"
    if "gemini_api_key" in config:
        secret_store.set_key(config["gemini_api_key"])
    to_save = {k: v for k, v in config.items() if k != "gemini_api_key"}
    _save_raw(config_path, to_save)


def _save_raw(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
