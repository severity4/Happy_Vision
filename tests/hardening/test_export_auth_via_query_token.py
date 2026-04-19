"""tests/hardening/test_export_auth_via_query_token.py

Regression guard: the export links on the Monitor page are plain
`<a href>` navigations. Those bypass the fetch() interceptor that
injects `X-HV-Token`, so they need the `?token=` query-string path
instead (same as SSE).

Real bug observed on 2026-04-20: clicking PDF 報告 / CSV / JSON / 診斷
opened a new tab showing `{"error":"Forbidden"}` because no token was
attached. Fix: frontend now builds `/api/export/<fmt>?token=...`.

This test locks in the backend contract (query token works) so the
frontend fix can't silently regress if someone drops the token later.
"""

from __future__ import annotations

import pytest

from modules import auth
from web_ui import app as _app


@pytest.fixture
def raw_client(monkeypatch):
    """Test client WITHOUT the conftest auth auto-injection, so we can
    verify the raw backend behavior on missing / valid / bogus tokens."""
    _app.config["TESTING"] = True
    # Undo the conftest fixture that injects X-HV-Token + Host — we
    # re-apply only a Host header (required by auth allowlist) so we
    # test token logic in isolation.
    from flask.testing import FlaskClient

    def _raw_open(self, *args, **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Host", "127.0.0.1:8081")
        kwargs["headers"] = headers
        # Call whatever Flask provides underneath
        from werkzeug.test import Client as _WerkzeugClient
        return _WerkzeugClient.open(self, *args, **kwargs)

    monkeypatch.setattr(FlaskClient, "open", _raw_open)

    with _app.test_client() as c:
        yield c


def test_export_without_token_returns_403(raw_client):
    """Pristine <a href='/api/export/pdf'> with no token and no header
    must be rejected. This is the broken-before-fix baseline."""
    r = raw_client.get("/api/export/pdf")
    assert r.status_code == 403
    data = r.get_json()
    assert data == {"error": "Forbidden"}


def test_export_with_valid_query_token_passes_auth(raw_client):
    """With `?token=<SESSION_TOKEN>` the request is authorised (may 500
    internally if there are no results, but must not be 403)."""
    token = auth.SESSION_TOKEN
    r = raw_client.get(f"/api/export/csv?token={token}")
    assert r.status_code != 403, (
        f"valid query token rejected: got {r.status_code} {r.get_data(as_text=True)[:200]}"
    )


def test_export_with_bogus_query_token_returns_403(raw_client):
    """Wrong token in query string — still forbidden."""
    r = raw_client.get("/api/export/pdf?token=not-the-real-token")
    assert r.status_code == 403


def test_all_four_export_kinds_accept_query_token(raw_client):
    """PDF / CSV / JSON / diagnostics — all four MonitorView buttons
    must honour the ?token=... auth path consistently."""
    token = auth.SESSION_TOKEN
    for kind in ("pdf", "csv", "json", "diagnostics"):
        r = raw_client.get(f"/api/export/{kind}?token={token}")
        assert r.status_code != 403, (
            f"/api/export/{kind} rejected valid query token "
            f"(status {r.status_code})"
        )
