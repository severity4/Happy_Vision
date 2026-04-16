"""tests/conftest.py — shared fixtures for test suite."""
import pytest

from modules import auth


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
