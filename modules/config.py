"""modules/config.py — Config load/save for Happy Vision

The Gemini API key is stored in macOS Keychain (via modules.secret_store);
never in config.json. load_config() returns a dict with `gemini_api_key`
populated from Keychain for backward compatibility with callers.
"""

import json
import logging
import os
import platform
from pathlib import Path

from modules import secret_store

log = logging.getLogger(__name__)

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
    # Lightroom rating pre-filter (v0.8.0+). If > 0, photos with XMP:Rating
    # strictly less than this value are skipped — don't get analysed, don't
    # hit the API. Assumes the photographer has already culled in Lightroom.
    # 0 = disabled (tag everything, prior behaviour).
    # 3 = typical "keeper" threshold; filters out 1-2 star rejects + unrated.
    "min_rating": 0,
    # Gemini Batch API mode (v0.9.0+). Batch = 50% cost, 24h SLO, async.
    # REQUIRES a Tier-1 paid Google AI Studio account (credit card bound).
    # off    = always realtime
    # auto   = batch when photo count >= batch_threshold, else realtime
    # always = batch every run
    "batch_mode": "off",
    "batch_threshold": 500,
}


def get_config_dir() -> Path:
    """Return (and create) the Happy Vision config directory."""
    base = os.environ.get("HAPPY_VISION_HOME", str(Path.home() / ".happy-vision"))
    config_dir = Path(base)
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def load_config() -> dict:
    """Load config; merge API key from Keychain. Migrates legacy plaintext
    key out of config.json on first encounter.

    Corruption policy: if config.json exists but can't be parsed (invalid
    JSON, empty file, non-object root), we fall back to DEFAULT_CONFIG and
    quarantine the bad file to `config.json.bad` so the user can inspect
    what they typed wrong. This makes the app bulletproof against a single
    manual-edit typo — previous behaviour crashed the whole startup."""
    config_path = get_config_dir() / "config.json"
    config = dict(DEFAULT_CONFIG)
    legacy_key = None

    if config_path.exists():
        stored = _safe_load_json(config_path)
        if isinstance(stored, dict):
            legacy_key = stored.pop("gemini_api_key", None)
            config.update(stored)
        # If _safe_load_json returned None, we've already quarantined
        # the bad file and will proceed with defaults.

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


def _safe_load_json(path: Path) -> dict | None:
    """Return parsed JSON dict, or None on parse failure / non-dict root.

    On failure we rename the bad file to `<name>.bad` so (a) the user can
    recover hand-typed credentials, (b) the next save_config() writes a
    clean file instead of the caller wondering why their manually-edited
    entries disappeared. Never deletes data."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, ValueError) as e:
        _quarantine(path, reason=f"parse error: {e}")
        return None

    if not isinstance(data, dict):
        _quarantine(path, reason=f"root must be object, got {type(data).__name__}")
        return None

    return data


def _quarantine(path: Path, reason: str) -> None:
    """Rename a bad config file to `<name>.bad`. Idempotent: if a `.bad`
    already exists, overwrite it (the newest corruption is the most useful
    for debugging; older .bad files likely came from the same edit)."""
    bad = path.with_suffix(path.suffix + ".bad")
    try:
        if bad.exists():
            bad.unlink()
        path.rename(bad)
        log.warning("config.json unparseable (%s); quarantined to %s and "
                    "continuing with defaults.", reason, bad)
    except OSError as e:
        log.error("Could not quarantine bad config at %s: %s", path, e)


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
