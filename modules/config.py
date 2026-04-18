"""modules/config.py — Config load/save for Happy Vision

The Gemini API key is stored in macOS Keychain (via modules.secret_store);
never in config.json. load_config() returns a dict with `gemini_api_key`
populated from Keychain for backward compatibility with callers.
"""

import json
import os
import platform
from pathlib import Path

from modules import secret_store

DEFAULT_CONFIG = {
    "tester_name": "",
    "machine_name": platform.node(),
    "app_version": "dev",
    "model": "lite",
    "concurrency": 5,
    "write_metadata": False,
    "skip_existing": False,
    "watch_folder": "",
    "watch_enabled": False,
    "watch_concurrency": 1,
    "watch_interval": 10,
    # Throughput tuning (v0.5.1+) — both have safe defaults matching the
    # Gemini free-tier posture. Users on paid tiers can raise rate_limit_rpm
    # (up to 2000 for flash-lite) and drop image_max_size for faster, cheaper
    # runs at the cost of some description detail.
    "rate_limit_rpm": 60,
    "image_max_size": 3072,
    # Near-duplicate detection (v0.6.0+). Threshold is the max Hamming distance
    # between two 64-bit pHashes to be considered "the same photo" for dedup.
    # 0 = disables dedup entirely. 5 catches typical burst duplicates without
    # merging different moments. See modules/phash.py for tuning guidance.
    "phash_threshold": 5,
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

    # Migration: if JSON had a plaintext key, ensure Keychain has it and
    # scrub the JSON. If Keychain already has a (possibly different) key,
    # it wins — we still must scrub to avoid the plaintext sticking around.
    keychain_key = secret_store.get_key()
    if legacy_key:
        if not keychain_key:
            secret_store.set_key(legacy_key)
            keychain_key = legacy_key
        # Always rewrite JSON without the key when legacy_key was found
        _save_raw(config_path, config)

    config["gemini_api_key"] = keychain_key
    return config


def save_config(config: dict) -> None:
    """Save config to disk. API key goes to Keychain; JSON gets everything else.

    We only rewrite the Keychain when the key actually changed. A settings
    PUT that doesn't touch the key (user only changed `phash_threshold`,
    say) should NOT trigger a Keychain write — every write risks a 2s
    permission prompt timeout on a fresh binary and is pure waste."""
    config_path = get_config_dir() / "config.json"
    if "gemini_api_key" in config:
        new_key = config["gemini_api_key"] or ""
        current = secret_store.get_key()
        if new_key != current:
            secret_store.set_key(new_key)
    to_save = {k: v for k, v in config.items() if k != "gemini_api_key"}
    _save_raw(config_path, to_save)


def _save_raw(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
