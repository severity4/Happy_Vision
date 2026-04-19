"""tests/test_result_store_batch.py — batch_jobs + batch_items persistence."""
from __future__ import annotations

import pytest

from modules.result_store import ResultStore


@pytest.fixture
def store(tmp_path):
    s = ResultStore(tmp_path / "r.db")
    yield s
    s.close()


def test_create_batch_job_persists_items(store):
    items = [("p00000", "/tmp/a.jpg"), ("p00001", "/tmp/b.jpg")]
    store.create_batch_job(
        job_id="batches/abc",
        folder="/tmp",
        model="lite",
        items=items,
        input_file_id="files/x",
        payload_bytes=123456,
        display_name="test",
    )
    job = store.get_batch_job("batches/abc")
    assert job["photo_count"] == 2
    assert job["status"] == "JOB_STATE_PENDING"
    assert job["model"] == "lite"
    assert job["input_file_id"] == "files/x"
    saved_items = store.get_batch_items("batches/abc")
    assert {i["file_path"] for i in saved_items} == {"/tmp/a.jpg", "/tmp/b.jpg"}
    assert all(i["status"] == "pending" for i in saved_items)


def test_update_batch_job_status_end_state_sets_completed_at(store):
    store.create_batch_job(
        job_id="batches/end",
        folder="/tmp",
        model="lite",
        items=[("p00000", "/tmp/a.jpg")],
        input_file_id="files/x",
        payload_bytes=100,
    )
    store.update_batch_job_status(
        "batches/end", "JOB_STATE_SUCCEEDED",
        output_file_id="files/out",
        completed_count=1,
    )
    job = store.get_batch_job("batches/end")
    assert job["status"] == "JOB_STATE_SUCCEEDED"
    assert job["output_file_id"] == "files/out"
    assert job["completed_count"] == 1
    assert job["completed_at"] is not None


def test_update_batch_job_status_active_keeps_completed_at_null(store):
    store.create_batch_job(
        job_id="batches/active",
        folder="/tmp",
        model="lite",
        items=[("p00000", "/tmp/a.jpg")],
        input_file_id="files/x",
        payload_bytes=100,
    )
    store.update_batch_job_status("batches/active", "JOB_STATE_RUNNING")
    job = store.get_batch_job("batches/active")
    assert job["status"] == "JOB_STATE_RUNNING"
    assert job["completed_at"] is None


def test_list_batch_jobs_active_only_filters_ended(store):
    for jid, state in [
        ("batches/a", "JOB_STATE_PENDING"),
        ("batches/b", "JOB_STATE_RUNNING"),
        ("batches/c", "JOB_STATE_SUCCEEDED"),
        ("batches/d", "JOB_STATE_FAILED"),
    ]:
        store.create_batch_job(
            job_id=jid, folder="/tmp", model="lite",
            items=[("k", "/tmp/x.jpg")], input_file_id="files/x",
            payload_bytes=1, initial_status=state,
        )
    all_jobs = store.list_batch_jobs(active_only=False)
    assert {j["job_id"] for j in all_jobs} == {"batches/a", "batches/b", "batches/c", "batches/d"}
    active = store.list_batch_jobs(active_only=True)
    assert {j["job_id"] for j in active} == {"batches/a", "batches/b"}


def test_mark_batch_item_updates_only_target(store):
    items = [("p00000", "/tmp/a.jpg"), ("p00001", "/tmp/b.jpg")]
    store.create_batch_job(
        job_id="batches/z", folder="/tmp", model="lite",
        items=items, input_file_id="files/x", payload_bytes=1,
    )
    store.mark_batch_item("batches/z", "p00000", "completed")
    rows = store.get_batch_items("batches/z")
    by_key = {r["request_key"]: r["status"] for r in rows}
    assert by_key["p00000"] == "completed"
    assert by_key["p00001"] == "pending"


def test_delete_batch_job_removes_items_too(store):
    store.create_batch_job(
        job_id="batches/del", folder="/tmp", model="lite",
        items=[("p00000", "/tmp/a.jpg")], input_file_id="files/x",
        payload_bytes=1,
    )
    store.delete_batch_job("batches/del")
    assert store.get_batch_job("batches/del") is None
    assert store.get_batch_items("batches/del") == []
