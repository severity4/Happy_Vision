"""tests/hardening/test_e1_first_launch_no_config.py

Hardening E1: 首次啟動 — HAPPY_VISION_HOME 不存在 / 不可寫 / 完全空白 →
app 仍能啟動，load_config 返回 DEFAULT_CONFIG，使用者不需手動建檔。

真實場景：同事第一次打開 .app，`~/.happy-vision/` 目錄還沒被建立。如果
load_config 在此情境下丟 FileNotFoundError / PermissionError，app 會開不
起來，同事看到的是死當。

合約：
- 首次啟動 config.json 不存在 → 返回 DEFAULT_CONFIG 的 copy，含 keychain
  merged 的 gemini_api_key
- 目錄不存在 → 自動建立
- save_config 能把 defaults 寫入，下次 load 拿得回來
"""

from __future__ import annotations

import json
from pathlib import Path

from modules import config as cfg
from modules.config import DEFAULT_CONFIG, get_config_dir, load_config


def test_load_config_on_pristine_home_returns_defaults(tmp_path, monkeypatch):
    """HAPPY_VISION_HOME points at a non-existent directory. load_config
    must auto-create the dir and return DEFAULT_CONFIG with the API key
    slot populated from Keychain (None in test)."""
    home = tmp_path / "fresh-install"
    # Crucial: do NOT mkdir — simulate truly first-time install.
    assert not home.exists()

    monkeypatch.setenv("HAPPY_VISION_HOME", str(home))

    config = load_config()

    # Directory got created as a side-effect.
    assert home.exists()
    assert home.is_dir()

    # Every default key is present.
    for key, default_value in DEFAULT_CONFIG.items():
        assert config[key] == default_value

    # API key slot populated (even if None).
    assert "gemini_api_key" in config


def test_load_config_on_empty_existing_home_returns_defaults(tmp_path, monkeypatch):
    """Home exists but is completely empty. No config.json yet."""
    home = tmp_path / "happy-vision"
    home.mkdir()
    monkeypatch.setenv("HAPPY_VISION_HOME", str(home))

    config = load_config()

    for key, default_value in DEFAULT_CONFIG.items():
        assert config[key] == default_value


def test_get_config_dir_creates_directory_atomically(tmp_path, monkeypatch):
    """Calling get_config_dir() on a non-existent path is idempotent
    and thread-safe in principle — mkdir(exist_ok=True) handles both."""
    home = tmp_path / "new-home"
    monkeypatch.setenv("HAPPY_VISION_HOME", str(home))

    dir1 = get_config_dir()
    dir2 = get_config_dir()  # second call on now-existing dir
    assert dir1 == dir2 == home


def test_first_launch_then_save_round_trip(tmp_path, monkeypatch):
    """First time: load defaults → user tweaks a setting → save → next
    load returns the tweak, not defaults. Proves startup is not
    stuck in a 'always fresh' loop."""
    home = tmp_path / "first-launch"
    monkeypatch.setenv("HAPPY_VISION_HOME", str(home))

    first = load_config()
    assert first["model"] == DEFAULT_CONFIG["model"]  # "lite"

    first["model"] = "flash"
    cfg.save_config(first)

    # config.json now exists and contains the tweak
    config_file = home / "config.json"
    assert config_file.exists()
    on_disk = json.loads(config_file.read_text())
    assert on_disk["model"] == "flash"
    # gemini_api_key should NOT appear in the JSON (it goes to Keychain)
    assert "gemini_api_key" not in on_disk

    # Second load sees the tweak.
    second = load_config()
    assert second["model"] == "flash"


def test_load_config_does_not_prompt_or_block_on_missing_key(tmp_path, monkeypatch):
    """The API key being absent must NOT make load_config raise or block.
    The UI is responsible for prompting; load_config just returns None
    for the key slot."""
    home = tmp_path / "no-key"
    monkeypatch.setenv("HAPPY_VISION_HOME", str(home))

    config = load_config()

    # No key yet — slot present but None (not missing).
    assert "gemini_api_key" in config
    assert config["gemini_api_key"] in (None, "")  # depending on keychain stub


def test_app_version_default_is_dev_before_any_save(tmp_path, monkeypatch):
    """app_version defaults to 'dev' until build_app overwrites it. A
    first-launch user sees 'dev' in the footer / about box — that's fine
    for now, but regression-guard the default so nobody accidentally
    leaks a real version string that doesn't match the running binary."""
    home = tmp_path / "fresh"
    monkeypatch.setenv("HAPPY_VISION_HOME", str(home))

    config = load_config()
    assert config["app_version"] == "dev"
