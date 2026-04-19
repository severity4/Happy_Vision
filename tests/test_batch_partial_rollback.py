"""tests/test_batch_partial_rollback.py — v0.12.0 partial-chunk failure handling.

Code review MEDIUM: if chunk 5 of 50 hits TierRequiredError, chunks 1-4
are already live at Gemini and cost money. Must surface this to the caller
instead of propagating a raw exception or silently losing the fact.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from modules import gemini_batch, pipeline
from modules.gemini_batch import BatchSubmitResult
from modules.result_store import ResultStore


def _make_folder_with_photos(tmp_path: Path, n: int) -> Path:
    for i in range(n):
        Image.new("RGB", (40, 30), (i, 100, 200)).save(tmp_path / f"p{i:05d}.jpg")
    return tmp_path


@pytest.fixture
def small_folder(tmp_path):
    return _make_folder_with_photos(tmp_path, 10)


@pytest.fixture
def store(tmp_path):
    s = ResultStore(tmp_path / "r.db")
    yield s
    s.close()


# Force submit_batch_run to chunk at 3 per job for fast tests.
@pytest.fixture
def tiny_chunks(monkeypatch):
    monkeypatch.setattr(gemini_batch, "MAX_PHOTOS_PER_BATCH", 3)


# ---------------- happy path: all chunks succeed ----------------

def test_submit_batch_run_summary_has_no_partial_flag_on_success(small_folder, store, tiny_chunks, monkeypatch):
    """9 photos / chunk=3 → 3 chunks. All succeed → partial_failure=False."""
    monkeypatch.setattr("modules.pipeline.ResultStore", lambda *_a, **_kw: store)

    counter = {"i": 0}
    def fake_submit(*a, **kw):
        counter["i"] += 1
        return BatchSubmitResult(
            job_id=f"batches/ok-{counter['i']}",
            input_file_id=f"files/{counter['i']}",
            photo_count=0,
            payload_bytes=100,
        )

    with patch.object(gemini_batch, "submit_batch", side_effect=fake_submit):
        summary = pipeline.submit_batch_run(
            folder=str(small_folder),
            api_key="stub",
            skip_existing=False,
        )
    assert summary["partial_failure"] is False
    assert summary["error"] is None
    assert summary["chunks"] == 4  # 10 photos / 3 per chunk = 4 chunks (3+3+3+1)
    assert summary["planned_chunks"] == 4
    assert len(summary["jobs"]) == 4


# ---------------- tier error mid-run ----------------

def test_tier_error_halts_submission_and_surfaces_partial_summary(small_folder, store, tiny_chunks, monkeypatch):
    """Chunk 2 raises TierRequiredError → chunk 1 stays live, chunks 3-4
    never submitted, caller gets partial_summary attached to the exception."""
    monkeypatch.setattr("modules.pipeline.ResultStore", lambda *_a, **_kw: store)

    call_count = {"n": 0}
    def fake_submit(*a, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return BatchSubmitResult(
                job_id="batches/ok-1", input_file_id="files/1",
                photo_count=0, payload_bytes=100,
            )
        raise gemini_batch.TierRequiredError()

    with patch.object(gemini_batch, "submit_batch", side_effect=fake_submit):
        with pytest.raises(gemini_batch.TierRequiredError) as exc_info:
            pipeline.submit_batch_run(
                folder=str(small_folder),
                api_key="stub",
                skip_existing=False,
            )
    err = exc_info.value
    assert hasattr(err, "partial_summary")
    ps = err.partial_summary
    assert ps["partial_failure"] is True
    assert ps["failed_chunk_index"] == 2
    assert ps["chunks"] == 1  # only chunk 1 made it
    assert ps["planned_chunks"] == 4
    assert len(ps["jobs"]) == 1
    assert ps["jobs"][0]["job_id"] == "batches/ok-1"
    # And only 2 submits were attempted — didn't waste budget on chunks 3-4
    assert call_count["n"] == 2


def test_transient_chunk_failure_halts_and_returns_summary(small_folder, store, tiny_chunks, monkeypatch):
    """Non-tier exception also halts submission so one network blip doesn't
    cascade into 49 uploads. Returns a summary with partial_failure instead
    of raising."""
    monkeypatch.setattr("modules.pipeline.ResultStore", lambda *_a, **_kw: store)

    call_count = {"n": 0}
    def fake_submit(*a, **kw):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return BatchSubmitResult(
                job_id=f"batches/ok-{call_count['n']}",
                input_file_id=f"files/{call_count['n']}",
                photo_count=0, payload_bytes=100,
            )
        raise RuntimeError("upstream timeout")

    with patch.object(gemini_batch, "submit_batch", side_effect=fake_submit):
        summary = pipeline.submit_batch_run(
            folder=str(small_folder),
            api_key="stub",
            skip_existing=False,
        )
    assert summary["partial_failure"] is True
    assert summary["failed_chunk_index"] == 3
    assert summary["chunks"] == 2  # 2 chunks submitted before chunk 3 failed
    assert summary["planned_chunks"] == 4
    assert "upstream timeout" in summary["error"]
