"""tests/conftest.py — shared fixtures for test suite."""
import pytest

from modules import auth


@pytest.fixture(autouse=True)
def _isolate_happy_vision_home(monkeypatch, tmp_path_factory):
    """Redirect HAPPY_VISION_HOME so every test sandbox-reads/writes config
    under a per-test tmp directory instead of ~/.happy-vision.

    Without this the settings API tests (and anything that calls
    load_config / save_config) mutate the developer's real config.json — and
    fail outright in sandboxed CI environments where $HOME is unwritable.
    The hermetic guarantee matters more than test speed: tmp dirs are cheap.
    """
    sandbox = tmp_path_factory.mktemp("happyvision_home")
    monkeypatch.setenv("HAPPY_VISION_HOME", str(sandbox))
    yield sandbox


class _InMemoryKeyring:
    """Mimics the subset of the keyring module that secret_store uses."""
    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self._store.get((service, username))

    def set_password(self, service, username, password):
        self._store[(service, username)] = password

    def delete_password(self, service, username):
        import keyring.errors
        if (service, username) not in self._store:
            raise keyring.errors.PasswordDeleteError("missing")
        del self._store[(service, username)]


@pytest.fixture(autouse=True)
def _isolate_keychain(monkeypatch):
    """Replace the global _keyring module reference with an in-memory fake so
    tests NEVER touch the developer's real macOS Keychain. This guards the
    config-migration path (tests that write legacy config.json with
    gemini_api_key trigger secret_store.set_key during load_config).

    Also invalidates the in-process cache before and after each test, else
    a test that set a key would poison the next test's get_key."""
    from modules import secret_store
    monkeypatch.setattr(secret_store, "_keyring", _InMemoryKeyring())
    secret_store.invalidate_cache()
    yield
    secret_store.invalidate_cache()


@pytest.fixture(autouse=True)
def _authed_test_client(monkeypatch):
    """Make Flask test_client requests pass the auth middleware by default.

    The auth middleware requires a valid X-HV-Token and a Host header matching
    the localhost allowlist. Werkzeug's test client defaults Host to "localhost"
    (without port), which our allowlist rejects. This fixture wraps
    FlaskClient.open so every test call has both headers set.
    """
    from flask.testing import FlaskClient
    original_open = FlaskClient.open

    def open_with_auth(self, *args, **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("X-HV-Token", auth.SESSION_TOKEN)
        headers.setdefault("Host", "127.0.0.1:8081")
        kwargs["headers"] = headers
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(FlaskClient, "open", open_with_auth)
    yield
