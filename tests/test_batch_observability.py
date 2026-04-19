"""tests/test_batch_observability.py — v0.11.0 monitor health + zombie detection.

Fixes SRE HIGH findings:
  - No observability: daemon could die at 3am, user sees nothing
  - API key rotation zombie: job stuck PENDING forever
  - Per-job vs whole-monitor backoff attribution
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from modules.batch_monitor import BatchMonitor, MAX_POLL_FAILURES
from modules.result_store import ResultStore


@pytest.fixture
def store(tmp_path):
    s = ResultStore(tmp_path / "r.db")
    yield s
    s.close()


# ---------------- record_poll_attempt ----------------

def test_record_poll_attempt_success_resets_failure_counter(store):
    store.create_batch_job(
        job_id="batches/a", folder="/tmp", model="lite",
        items=[("p0", "/tmp/a.jpg")], input_file_id="files/x", payload_bytes=1,
    )
    # First, rack up 5 failures.
    for _ in range(5):
        n = store.record_poll_attempt("batches/a", error="boom")
    assert n == 5
    # Successful poll must reset to 0.
    n = store.record_poll_attempt("batches/a", error=None)
    assert n == 0
    job = store.get_batch_job("batches/a")
    assert job["consecutive_poll_failures"] == 0
    assert job["last_poll_error"] is None
    assert job["last_polled_at"] is not None


def test_record_poll_attempt_truncates_long_errors(store):
    store.create_batch_job(
        job_id="batches/long", folder="/tmp", model="lite",
        items=[("p0", "/tmp/a.jpg")], input_file_id="files/x", payload_bytes=1,
    )
    store.record_poll_attempt("batches/long", error="x" * 5000)
    job = store.get_batch_job("batches/long")
    assert len(job["last_poll_error"]) == 500  # clamped per result_store


# ---------------- zombie detection in _poll_one ----------------

def test_poll_marks_job_failed_after_max_consecutive_failures(store):
    store.create_batch_job(
        job_id="batches/zombie", folder="/tmp", model="lite",
        items=[("p0", "/tmp/a.jpg"), ("p1", "/tmp/b.jpg")],
        input_file_id="files/x", payload_bytes=1,
        initial_status="JOB_STATE_RUNNING",
    )
    # Pre-populate with MAX_POLL_FAILURES - 1 prior failures.
    for _ in range(MAX_POLL_FAILURES - 1):
        store.record_poll_attempt("batches/zombie", error="PERMISSION_DENIED")

    monitor = BatchMonitor()
    emitted = []
    monitor._event_sink = lambda p: emitted.append(p)

    job_row = store.get_batch_job("batches/zombie")
    with patch("modules.batch_monitor.gemini_batch.get_job_state") as mock_get:
        mock_get.side_effect = Exception("PERMISSION_DENIED: revoked")
        monitor._poll_one(store, job_row, api_key="stub")

    job = store.get_batch_job("batches/zombie")
    assert job["status"] == "JOB_STATE_FAILED"
    assert "poll_failures_exceeded" in job["error_message"] or str(MAX_POLL_FAILURES) in job["error_message"]
    # Pending items rolled to failed.
    items = store.get_batch_items("batches/zombie")
    assert all(i["status"] == "failed" for i in items)
    # UI got notified.
    states = [e.get("state") for e in emitted if e.get("type") == "batch_state"]
    assert "JOB_STATE_FAILED" in states


def test_poll_tolerates_single_failure_without_marking_failed(store):
    store.create_batch_job(
        job_id="batches/flap", folder="/tmp", model="lite",
        items=[("p0", "/tmp/a.jpg")],
        input_file_id="files/x", payload_bytes=1,
        initial_status="JOB_STATE_RUNNING",
    )

    monitor = BatchMonitor()
    job_row = store.get_batch_job("batches/flap")
    with patch("modules.batch_monitor.gemini_batch.get_job_state") as mock_get:
        mock_get.side_effect = Exception("transient 503")
        monitor._poll_one(store, job_row, api_key="stub")

    job = store.get_batch_job("batches/flap")
    assert job["status"] == "JOB_STATE_RUNNING"  # still running
    assert job["consecutive_poll_failures"] == 1
    assert job["last_poll_error"] == "transient 503"


def test_poll_success_resets_prior_failures(store):
    store.create_batch_job(
        job_id="batches/recover", folder="/tmp", model="lite",
        items=[("p0", "/tmp/a.jpg")],
        input_file_id="files/x", payload_bytes=1,
        initial_status="JOB_STATE_RUNNING",
    )
    # Simulate 5 prior failures.
    for _ in range(5):
        store.record_poll_attempt("batches/recover", error="503")

    monitor = BatchMonitor()
    job_row = store.get_batch_job("batches/recover")
    with patch("modules.batch_monitor.gemini_batch.get_job_state") as mock_get:
        mock_get.return_value = {"state": "JOB_STATE_RUNNING", "output_file": None, "error": None}
        monitor._poll_one(store, job_row, api_key="stub")

    job = store.get_batch_job("batches/recover")
    assert job["consecutive_poll_failures"] == 0
    assert job["last_poll_error"] is None


# ---------------- health snapshot + /api/batch/health ----------------

def test_health_snapshot_returns_expected_fields():
    monitor = BatchMonitor()
    snap = monitor.health_snapshot()
    assert set(snap.keys()) >= {
        "alive", "last_tick_at", "last_tick_error",
        "active_jobs", "consecutive_errors",
    }
    assert snap["alive"] is False  # thread not started


def test_health_endpoint_returns_not_started_when_monitor_missing():
    import web_ui
    # Ensure no monitor is running
    from modules import batch_monitor as bm
    original = bm._monitor_instance
    bm._monitor_instance = None
    try:
        client = web_ui.app.test_client()
        r = client.get("/api/batch/health")
        assert r.status_code == 200
        body = r.get_json()
        assert body["alive"] is False
        assert body["reason"] == "monitor_not_started"
    finally:
        bm._monitor_instance = original


def test_health_endpoint_returns_live_data_when_running():
    import web_ui
    from modules import batch_monitor as bm
    monitor = BatchMonitor()
    # Fake a recent tick without starting the thread.
    monitor._last_tick_at = "2026-04-19T14:00:00"
    monitor._active_job_count = 3
    monitor._consecutive_errors = 0
    original = bm._monitor_instance
    bm._monitor_instance = monitor
    try:
        client = web_ui.app.test_client()
        r = client.get("/api/batch/health")
        body = r.get_json()
        assert body["last_tick_at"] == "2026-04-19T14:00:00"
        assert body["active_jobs"] == 3
        assert body["consecutive_errors"] == 0
    finally:
        bm._monitor_instance = original


# ---------------- tier error now uses 403 not 402 ----------------

def test_batch_submit_tier_required_returns_403(tmp_path, monkeypatch):
    """Code review: 402 → 403 to dodge proxy / client misinterpretation."""
    import web_ui
    from modules import gemini_batch, secret_store
    secret_store.set_key("AIzaStub")
    # Register folder so path allowlist passes.
    web_ui.register_allowed_root(tmp_path)
    # Actual JPG so scan_photos finds something
    from PIL import Image
    Image.new("RGB", (50, 50)).save(tmp_path / "p.jpg")
    monkeypatch.setattr(
        "modules.pipeline.submit_batch_run",
        lambda *a, **kw: (_ for _ in ()).throw(gemini_batch.TierRequiredError()),
    )
    client = web_ui.app.test_client()
    r = client.post("/api/batch/submit", json={"folder": str(tmp_path)})
    assert r.status_code == 403
    body = r.get_json()
    assert body["error"] == "tier_required"
    assert body["billing_url"].startswith("https://aistudio.google.com")
