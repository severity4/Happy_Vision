"""tests/hardening/test_e2_corrupt_config.py

Hardening E2: config.json 損壞 / 格式錯誤 → fallback 到預設值 + 清楚警告，
不能讓 app 開不起來。

現實情境：同事某次編輯 config.json 手動改 key 後打錯 JSON 格式（多一個逗號、
引號沒封、改成 `.json5` 結果誤存成 .json）。下次啟動 load_config 如果直接
`json.load(f)` 會丟 JSONDecodeError，整個 pywebview 視窗啟動失敗 —
對同事來說變成「軟體壞了」，但其實只是設定檔一個錯字。
"""

from __future__ import annotations

import json
from pathlib import Path

from modules import config as cfg
from modules.config import DEFAULT_CONFIG, load_config


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_load_config_falls_back_on_invalid_json(tmp_path, monkeypatch):
    """Garbage in config.json must not crash app startup."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    _write(tmp_path / "config.json", "{ not valid json at all")

    result = load_config()

    # Must not have raised. Must include all default keys.
    for key in DEFAULT_CONFIG:
        assert key in result, f"default key {key!r} missing after fallback"


def test_load_config_falls_back_on_trailing_comma(tmp_path, monkeypatch):
    """JSON5 habit: trailing commas break strict JSON."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    _write(tmp_path / "config.json", '{"model": "flash", "concurrency": 3,}')

    result = load_config()

    # Fell back to defaults completely — we'd rather be safe than load
    # partial state from a file we can't fully trust.
    assert result["model"] == DEFAULT_CONFIG["model"]
    assert result["concurrency"] == DEFAULT_CONFIG["concurrency"]


def test_load_config_falls_back_on_empty_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    _write(tmp_path / "config.json", "")

    result = load_config()

    for key in DEFAULT_CONFIG:
        assert key in result


def test_load_config_falls_back_on_non_object_root(tmp_path, monkeypatch):
    """JSON parses but root is a list — config.update(list) would raise
    TypeError. Must be caught."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    _write(tmp_path / "config.json", '[1, 2, 3]')

    result = load_config()

    for key in DEFAULT_CONFIG:
        assert key in result


def test_load_config_quarantines_bad_file_for_user_inspection(tmp_path, monkeypatch):
    """When we fall back, the bad file must NOT be silently deleted — the
    user (or us debugging later) might want to see what they typed wrong.
    Reasonable UX: rename to `config.json.bad` so next save doesn't
    clobber it, and the user has one shot at pasting a credential back."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    original = '{"model": "flash",}'  # trailing comma
    _write(tmp_path / "config.json", original)

    load_config()

    # Either the quarantine file exists OR the original stays put. Both
    # are acceptable behaviors; we just forbid "silent delete".
    quarantine = tmp_path / "config.json.bad"
    assert quarantine.exists() or (tmp_path / "config.json").exists()


def test_load_config_happy_path_still_loads_known_values(tmp_path, monkeypatch):
    """Regression guard: fixing corrupt-config handling must not break the
    common case where config.json is valid."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    data = {"model": "flash", "concurrency": 7, "watch_enabled": True}
    _write(tmp_path / "config.json", json.dumps(data))

    result = load_config()

    assert result["model"] == "flash"
    assert result["concurrency"] == 7
    assert result["watch_enabled"] is True
    # Unspecified keys should still get defaults.
    assert result["phash_threshold"] == DEFAULT_CONFIG["phash_threshold"]


def test_load_config_then_save_round_trips_after_corruption_recovery(
    tmp_path, monkeypatch,
):
    """After fallback, save_config writes a CLEAN config.json so the next
    load sees valid JSON (no more fallback loop)."""
    monkeypatch.setenv("HAPPY_VISION_HOME", str(tmp_path))
    _write(tmp_path / "config.json", "INVALID")

    loaded = load_config()
    loaded["model"] = "flash"
    cfg.save_config(loaded)

    # Next load: must succeed cleanly without falling back.
    # File must be valid JSON.
    raw = (tmp_path / "config.json").read_text()
    parsed = json.loads(raw)  # would raise if we still wrote garbage
    assert parsed["model"] == "flash"
