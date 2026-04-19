"""tests/test_hermetic.py — verify the test suite isolates filesystem state.

External review 2026-04-19 flagged that settings API tests were touching
the developer's real ~/.happy-vision/config.json. These tests confirm the
autouse conftest fixture `_isolate_happy_vision_home` does its job."""
from __future__ import annotations

import json
import os
from pathlib import Path

from modules.config import get_config_dir, load_config, save_config


def test_happy_vision_home_is_sandboxed():
    """HAPPY_VISION_HOME must be set to a tmp path by the autouse fixture."""
    home_env = os.environ.get("HAPPY_VISION_HOME")
    assert home_env, "HAPPY_VISION_HOME not set — hermetic fixture missing"
    home_path = Path(home_env)
    # Must be under /var/folders (macOS tmp), /tmp, or pytest-basetemp, never home.
    real_home = Path.home().resolve()
    assert real_home not in home_path.resolve().parents, (
        f"HAPPY_VISION_HOME {home_path} resolves inside real home {real_home}"
    )


def test_config_writes_stay_in_sandbox(tmp_path):
    """save_config must write into the sandbox, not the user's real home."""
    cfg_dir = get_config_dir()
    assert cfg_dir == Path(os.environ["HAPPY_VISION_HOME"])
    # Writing a canary value should land in the sandbox only.
    save_config({"tester_name": "sandbox_canary"})
    config_json = cfg_dir / "config.json"
    assert config_json.exists()
    data = json.loads(config_json.read_text())
    assert data.get("tester_name") == "sandbox_canary"
    # And re-loading must bring it back — proves round-trip within sandbox.
    loaded = load_config()
    assert loaded.get("tester_name") == "sandbox_canary"


def test_real_home_config_untouched():
    """Belt-and-braces: even if our sandbox fixture somehow failed, the
    real ~/.happy-vision/config.json must not contain our test canary."""
    real_path = Path.home() / ".happy-vision" / "config.json"
    if not real_path.exists():
        return  # nothing to check
    try:
        data = json.loads(real_path.read_text())
    except (json.JSONDecodeError, OSError):
        return
    assert data.get("tester_name") != "sandbox_canary", (
        f"Real user config at {real_path} was polluted by the test suite!"
    )
