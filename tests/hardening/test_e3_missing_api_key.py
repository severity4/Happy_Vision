"""tests/hardening/test_e3_missing_api_key.py

Hardening E3: API key 不在 Keychain → 必須在執行前就攔下（不要讓 500 張
照片每張都去 Gemini 然後各自回 401），並透過正常的 auth-halt 機制給清楚
訊息引導使用者去設定。

合約：
- secret_store.get_key() 在 key 不存在時回 "" 且不 raise
- load_config() 把 gemini_api_key 留 None / "" 而不是 crash
- 若 pipeline 被叫起但 api_key=""，analyze_photo 會被 Gemini 拒絕（401）
  → 透過 C3 的 auth halt 立即終止批次並回報 InvalidAPIKeyError
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from modules import config as cfg
from modules import gemini_vision
from modules import secret_store
from modules.gemini_vision import InvalidAPIKeyError, analyze_photo


_MOCK_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (64, 64), color="white").save(str(path), format="JPEG")


def test_get_key_returns_empty_when_absent(monkeypatch):
    """The conftest replaces the keyring backend with an in-memory fake;
    starting fresh (no set_key called) should read as empty, not raise."""
    # Cache might be populated from another test — invalidate first.
    secret_store.invalidate_cache()

    assert secret_store.get_key() == ""


def test_load_config_succeeds_when_keychain_has_no_key(tmp_path, monkeypatch):
    """Verified alongside E1 but specifically E3: even on a system where
    Keychain is fully healthy but just doesn't HAVE our key yet,
    load_config must not crash or block."""
    home = tmp_path / "fresh"
    monkeypatch.setenv("HAPPY_VISION_HOME", str(home))
    secret_store.invalidate_cache()

    config = cfg.load_config()

    assert config["gemini_api_key"] in (None, "")


def test_get_key_is_cached_after_first_read(monkeypatch):
    """Cache must suppress repeat Keychain calls to avoid the 2s prompt
    storm after first load — regression guard for a performance bug
    documented in the module docstring."""
    secret_store.invalidate_cache()
    call_count = {"n": 0}

    orig_get = secret_store._keyring.get_password

    def counting_get(service, username):
        call_count["n"] += 1
        return orig_get(service, username)

    monkeypatch.setattr(secret_store._keyring, "get_password", counting_get)

    secret_store.get_key()
    secret_store.get_key()
    secret_store.get_key()

    # Keychain called at most once per test — subsequent gets served from cache.
    assert call_count["n"] == 1


def test_set_key_updates_cache_immediately(monkeypatch):
    """Writing a new key via UI → next get_key() must return the new
    value without a Keychain re-read."""
    secret_store.invalidate_cache()

    secret_store.set_key("fresh-key-123")

    # Make subsequent keychain reads error out — cache should serve.
    def boom(*_a, **_kw):
        raise RuntimeError("must not be called when cache is warm")

    monkeypatch.setattr(secret_store._keyring, "get_password", boom)

    assert secret_store.get_key() == "fresh-key-123"


def test_clear_key_updates_cache_to_empty():
    secret_store.invalidate_cache()
    secret_store.set_key("something")
    assert secret_store.get_key() == "something"

    secret_store.clear_key()
    # Cache must reflect cleared state without hitting Keychain again.
    assert secret_store.get_key() == ""


def test_analyze_photo_with_empty_key_halts_via_invalid_key_error(
    tmp_path, monkeypatch,
):
    """End-to-end: if someone somehow calls analyze_photo with api_key=""
    (e.g., pipeline started before UI prompt completed), Gemini returns
    auth failure and our C3 path halts the batch instead of hanging 500
    photos on identical 401s."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    class _Models:
        def generate_content(self, **_kw):
            raise Exception("400 API_KEY_INVALID: API key not valid")

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    with pytest.raises(InvalidAPIKeyError):
        analyze_photo(str(photo), api_key="", model="lite", max_retries=1)
