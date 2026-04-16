"""modules/config.py — Config load/save for Happy Vision"""

import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "model": "lite",
    "concurrency": 5,
    "write_metadata": False,
    "skip_existing": False,
}


def get_config_dir() -> Path:
    """Return (and create) the Happy Vision config directory."""
    base = os.environ.get("HAPPY_VISION_HOME", str(Path.home() / ".happy-vision"))
    config_dir = Path(base)
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def load_config() -> dict:
    """Load config from disk, merging with defaults for any missing keys."""
    config_path = get_config_dir() / "config.json"
    config = dict(DEFAULT_CONFIG)
    if config_path.exists():
        with open(config_path) as f:
            stored = json.load(f)
        config.update(stored)
    return config


def save_config(config: dict) -> None:
    """Save config to disk."""
    config_path = get_config_dir() / "config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
