"""tests/test_batch_monitor_resumable.py — v0.10.1 item-level resumability.

Fixes three HIGH findings from code review + SRE audit:
  - mid-run crash left SUCCEEDED job with partial items, never retried
  - cold-boot re-applied IPTC over user-edited tags
  - ExiftoolBatch init failure crashed the tick and left job stuck
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from modules.batch_monitor import BatchMonitor
from modules.gemini_batch import BatchItemResult
from modules.result_store import ResultStore


@pytest.fixture
def store_with_succeeded_job(tmp_path):
    s = ResultStore(tmp_path / "r.db")
    s.create_batch_job(
        job_id="batches/partial",
        folder="/tmp",
        model="lite",
        items=[(f"p{i:05d}", f"/tmp/p{i}.jpg") for i in range(5)],
        input_file_id="files/x",
        payload_bytes=1,
        initial_status="JOB_STATE_RUNNING",
    )
    yield s
    s.close()


def _fake_results(key_prefix="p", n=5, good_result=None):
    """Yield BatchItemResult for n photos. If good_result is supplied, all
    photos share that result payload; else each gets a minimal unique one."""
    default = {
        "title": "t", "description": "d", "keywords": ["a"],
        "category": "other", "scene_type": "indoor", "mood": "neutral",
        "people_count": 1,
    }
    for i in range(n):
        yield BatchItemResult(
            key=f"{key_prefix}{i:05d}",
            result=good_result or default,
            usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "model": "gemini-2.5-flash-lite"},
            error=None,
        )


def test_materialise_skips_already_completed_items(store_with_succeeded_job, tmp_path, monkeypatch):
    """If 2 of 5 items were already 'completed' in a prior tick, the
    next materialise pass must not re-write their IPTC."""
    store = store_with_succeeded_job
    # Mark 2 items as already completed from a previous crashed run.
    store.mark_batch_item("batches/partial", "p00000", "completed")
    store.mark_batch_item("batches/partial", "p00001", "completed")

    monitor = BatchMonitor(db_path=None)
    monitor._db_path = str(tmp_path / "r.db")  # not used — we pass store directly

    job_row = store.get_batch_job("batches/partial")
    # Update status to SUCCEEDED so _materialise_results is what we test
    store.update_batch_job_status("batches/partial", "JOB_STATE_SUCCEEDED")
    job_row = store.get_batch_job("batches/partial")

    with patch("modules.batch_monitor.gemini_batch.fetch_results") as mock_fetch:
        mock_fetch.return_value = list(_fake_results(n=5))
        # write_metadata=False so we don't need exiftool in the test
        monitor._materialise_results(store, job_row, api_key="stub")

    # After materialise: all 5 items should be completed, but the 2 that
    # were pre-completed must not have been re-written (no duplicate save).
    items = store.get_batch_items("batches/partial")
    statuses = {i["request_key"]: i["status"] for i in items}
    assert all(v == "completed" for v in statuses.values())

    # Counters should reflect total: 5 completed, 0 failed.
    job = store.get_batch_job("batches/partial")
    assert job["completed_count"] == 5
    assert job["failed_count"] == 0


def test_materialise_handles_exiftool_init_failure_without_crash(tmp_path, store_with_succeeded_job):
    """ExiftoolBatch() raising at construction must not propagate. The
    job stays SUCCEEDED with items pending → next tick retries."""
    store = store_with_succeeded_job
    store.update_batch_job_status("batches/partial", "JOB_STATE_SUCCEEDED")
    # Fake the job needing metadata writes so ExiftoolBatch() gets called.
    store.conn.execute(
        "UPDATE batch_jobs SET write_metadata = 1 WHERE job_id = ?",
        ("batches/partial",),
    )
    store.conn.commit()
    job_row = store.get_batch_job("batches/partial")

    monitor = BatchMonitor()
    with patch("modules.batch_monitor.ExiftoolBatch") as mock_ctor:
        mock_ctor.side_effect = FileNotFoundError("exiftool not found")
        # Must NOT raise — should log and return cleanly.
        monitor._materialise_results(store, job_row, api_key="stub")

    # Job row untouched, items still all pending.
    job = store.get_batch_job("batches/partial")
    assert job["status"] == "JOB_STATE_SUCCEEDED"  # unchanged
    assert job["completed_count"] == 0  # never advanced
    items = store.get_batch_items("batches/partial")
    assert all(i["status"] == "pending" for i in items)


def test_poll_reenters_materialise_when_succeeded_but_counts_incomplete(tmp_path, store_with_succeeded_job):
    """The regression case: job is SUCCEEDED in DB, but only 2/5 items done.
    Previous behaviour: state == job_row['status'] → early return, stuck.
    Fixed: detect the mismatch and re-enter materialise."""
    store = store_with_succeeded_job
    # Put job into the stuck state: SUCCEEDED in DB, only 2 items marked done.
    store.update_batch_job_status("batches/partial", "JOB_STATE_SUCCEEDED", completed_count=2, failed_count=0)
    store.mark_batch_item("batches/partial", "p00000", "completed")
    store.mark_batch_item("batches/partial", "p00001", "completed")

    monitor = BatchMonitor()
    materialise_called = []

    def fake_materialise(self, store, job_row, api_key):
        materialise_called.append(job_row["job_id"])

    job_row = store.get_batch_job("batches/partial")
    # Simulate _poll_one reading the same state from Gemini (no transition).
    with patch("modules.batch_monitor.gemini_batch.get_job_state") as mock_get, \
         patch.object(BatchMonitor, "_materialise_results", fake_materialise):
        mock_get.return_value = {
            "state": "JOB_STATE_SUCCEEDED",
            "output_file": "files/out",
            "error": None,
        }
        monitor._poll_one(store, job_row, api_key="stub")

    # Before v0.10.1: materialise would be skipped. After: it re-enters.
    assert materialise_called == ["batches/partial"]


def test_poll_skips_materialise_when_all_items_done(tmp_path, store_with_succeeded_job):
    """If the job finished cleanly, subsequent polls must NOT re-materialise.
    Steady state = return early."""
    store = store_with_succeeded_job
    store.update_batch_job_status(
        "batches/partial", "JOB_STATE_SUCCEEDED",
        completed_count=5, failed_count=0,
    )

    monitor = BatchMonitor()
    materialise_called = []

    def fake_materialise(self, store, job_row, api_key):
        materialise_called.append(job_row["job_id"])

    job_row = store.get_batch_job("batches/partial")
    with patch("modules.batch_monitor.gemini_batch.get_job_state") as mock_get, \
         patch.object(BatchMonitor, "_materialise_results", fake_materialise):
        mock_get.return_value = {
            "state": "JOB_STATE_SUCCEEDED",
            "output_file": "files/out",
            "error": None,
        }
        monitor._poll_one(store, job_row, api_key="stub")

    assert materialise_called == []  # no re-entry
