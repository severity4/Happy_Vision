"""tests/test_secret_store.py"""
from modules import secret_store


class FakeKeyring:
    """In-memory fake that mimics the keyring module API."""
    def __init__(self):
        self._store = {}

    def get_password(self, service, username):
        return self._store.get((service, username))

    def set_password(self, service, username, password):
        self._store[(service, username)] = password

    def delete_password(self, service, username):
        self._store.pop((service, username), None)


def test_set_and_get_key(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(secret_store, "_keyring", fake)
    secret_store.set_key("abc123")
    assert secret_store.get_key() == "abc123"


def test_get_key_returns_empty_when_unset(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(secret_store, "_keyring", fake)
    assert secret_store.get_key() == ""


def test_clear_key(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(secret_store, "_keyring", fake)
    secret_store.set_key("abc")
    secret_store.clear_key()
    assert secret_store.get_key() == ""


def test_clear_key_idempotent(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(secret_store, "_keyring", fake)
    # Clearing an unset key must not raise
    secret_store.clear_key()
    assert secret_store.get_key() == ""


def test_set_empty_string_clears(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(secret_store, "_keyring", fake)
    secret_store.set_key("abc")
    secret_store.set_key("")
    assert secret_store.get_key() == ""
