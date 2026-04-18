"""tests/test_secret_store_cache.py — v0.7.0 in-process cache behavior.

The cache was introduced after Evidence Collector found Settings PUT hanging
for 4-6s on a fresh binary because every PUT hit Keychain 2-4 times (load_config
+ save_config × get_key + set_key), each 2s timeout on cold ACL. The cache
means the second PUT is free — critical for UX feel.
"""

from unittest.mock import MagicMock

import pytest

from modules import secret_store


def test_get_key_caches_after_first_call(monkeypatch):
    """Second get_key should not call _keyring.get_password again."""
    fake = MagicMock()
    fake.get_password.return_value = "abc123"
    monkeypatch.setattr(secret_store, "_keyring", fake)
    secret_store.invalidate_cache()

    v1 = secret_store.get_key()
    v2 = secret_store.get_key()
    v3 = secret_store.get_key()
    assert v1 == v2 == v3 == "abc123"
    # Only the first call should have hit the backend
    assert fake.get_password.call_count == 1, (
        f"Expected exactly 1 Keychain read; got {fake.get_password.call_count}. "
        "Cache isn't working — this will reintroduce the 4-6s PUT hang."
    )


def test_set_key_updates_cache_without_rereading(monkeypatch):
    """After set_key, get_key should serve the new value from cache (no
    get_password call needed)."""
    fake = MagicMock()
    fake.get_password.return_value = "old"
    monkeypatch.setattr(secret_store, "_keyring", fake)
    secret_store.invalidate_cache()

    # Prime cache with "old"
    assert secret_store.get_key() == "old"
    calls_before = fake.get_password.call_count

    # Now set a new value
    secret_store.set_key("new-value")

    # get_key should return "new-value" without another backend read
    assert secret_store.get_key() == "new-value"
    assert fake.get_password.call_count == calls_before, (
        "set_key should have updated the cache directly; get_key re-read the backend"
    )


def test_clear_key_updates_cache_to_empty(monkeypatch):
    fake = MagicMock()
    fake.get_password.return_value = "something"
    monkeypatch.setattr(secret_store, "_keyring", fake)
    secret_store.invalidate_cache()

    assert secret_store.get_key() == "something"
    secret_store.clear_key()
    # Cache now reflects cleared state; no extra backend read
    calls = fake.get_password.call_count
    assert secret_store.get_key() == ""
    assert fake.get_password.call_count == calls


def test_invalidate_cache_forces_refresh(monkeypatch):
    fake = MagicMock()
    fake.get_password.return_value = "v1"
    monkeypatch.setattr(secret_store, "_keyring", fake)
    secret_store.invalidate_cache()

    assert secret_store.get_key() == "v1"
    # Backend value changes under us; cache still has v1
    fake.get_password.return_value = "v2"
    assert secret_store.get_key() == "v1"  # still cached
    # Explicit invalidation forces refresh
    secret_store.invalidate_cache()
    assert secret_store.get_key() == "v2"


def test_cache_survives_keyring_error(monkeypatch):
    """If Keychain throws on first call, we return "" and cache "". Subsequent
    calls serve "" without re-trying (prevents a prompt storm)."""
    import keyring
    fake = MagicMock()
    fake.get_password.side_effect = keyring.errors.KeyringError("locked")
    monkeypatch.setattr(secret_store, "_keyring", fake)
    secret_store.invalidate_cache()

    v1 = secret_store.get_key()
    v2 = secret_store.get_key()
    assert v1 == v2 == ""
    # Only one attempt — subsequent reads are served from the negative cache
    assert fake.get_password.call_count == 1
