"""tests/hardening/test_d2_cancel_mid_batch.py

Hardening D2: 執行中按「取消」→ 已在處理的那張允許跑完（不強殺 thread），
但剩下的不會開始；ExiftoolBatch subprocess 乾淨關閉；DB 沒有半筆壞資料；
events 有 cancelled=True；on_complete 被呼叫。

UX 合約：同事按 Cancel 後 UI 必須能馬上解鎖（不要卡在讀條），要能立刻
跑下一次 pipeline 而不會踩到上次殘留的 exiftool process 或 SQLite lock。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from modules import pipeline as pl


_MOCK_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (64, 64), color=(100, 100, 100)).save(str(path), format="JPEG")


def _mock_result(n: int) -> dict:
    return {
        "title": f"t{n}",
        "description": "d",
        "keywords": [],
        "category": "other",
        "subcategory": "",
        "scene_type": "indoor",
        "mood": "neutral",
        "people_count": 0,
        "identified_people": [],
        "ocr_text": [],
    }


def test_cancel_before_any_photo_processed(tmp_path, monkeypatch):
    """Cancel before pipeline even starts executing. Expected: 0 analyses,
    on_complete fires with (total, 0)."""
    for i in range(5):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    state = pl.PipelineState()
    state.cancel()  # cancel BEFORE run_pipeline is called

    analyze_calls: list[str] = []

    def tracking(path, **_kw):
        analyze_calls.append(path)
        return _mock_result(1), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", tracking)

    class _NoopBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    completes: list[tuple[int, int]] = []

    class _CB(pl.PipelineCallbacks):
        def on_complete(self, total, failed):
            completes.append((total, failed))

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
        state=state,
        callbacks=_CB(),
    )

    assert results == []
    assert analyze_calls == []
    assert completes == [(5, 0)]  # on_complete still called so UI can reset


def test_cancel_mid_batch_closes_exiftool_batch(tmp_path, monkeypatch):
    """Key regression: the ExiftoolBatch subprocess MUST be closed even
    when user cancels. Leaking it means the next run finds leftover
    processes eating file handles."""
    for i in range(5):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    state = pl.PipelineState()
    call_count = {"n": 0}
    lock = threading.Lock()

    def analyze(path, **_kw):
        with lock:
            call_count["n"] += 1
            n = call_count["n"]
        if n == 2:
            state.cancel()
        return _mock_result(n), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", analyze)

    batch_state = {"closed": False, "created": 0}

    class _TrackedBatch:
        def __init__(self):
            batch_state["created"] += 1

        def write(self, *_a, **_kw):
            return True

        def close(self):
            batch_state["closed"] = True

        def __enter__(self): return self
        def __exit__(self, *_a): self.close()

    monkeypatch.setattr(pl, "ExiftoolBatch", _TrackedBatch)

    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=tmp_path / "r.db",
        state=state,
    )

    assert batch_state["created"] == 1
    assert batch_state["closed"] is True, (
        "ExiftoolBatch.close() was NOT called on cancel — subprocess will leak"
    )


def test_cancel_produces_consistent_db_state(tmp_path, monkeypatch):
    """DB must only contain rows for photos that were processed (completed
    or failed). Photos never touched must NOT appear — otherwise resume
    would re-process them and waste API."""
    for i in range(10):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    state = pl.PipelineState()
    call_count = {"n": 0}
    lock = threading.Lock()

    def analyze(path, **_kw):
        with lock:
            call_count["n"] += 1
            n = call_count["n"]
        if n == 3:
            state.cancel()
        return _mock_result(n), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", analyze)

    class _NoopBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    db_path = tmp_path / "r.db"
    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=db_path,
        state=state,
    )

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT file_path, status FROM results"
        ).fetchall()
    finally:
        conn.close()

    # With concurrency=1 and cancel on the 3rd analyze, exactly 3 rows.
    assert len(rows) == 3
    for _fp, status in rows:
        # All three rows must be "completed" (the cancel happened AFTER
        # the 3rd analyze returned, before the 4th started).
        assert status == "completed"


def test_cancel_is_idempotent(tmp_path, monkeypatch):
    """Multiple cancel() calls from different threads must not raise or
    leave state inconsistent."""
    for i in range(3):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    state = pl.PipelineState()
    # Call cancel many times from many threads.
    threads = [
        threading.Thread(target=state.cancel) for _ in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=1)

    assert state.cancelled is True

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **_kw: (_mock_result(1), _MOCK_USAGE),
    )

    class _NoopBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    # Run should exit immediately — cancelled before anything starts.
    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
        state=state,
    )
    assert results == []


def test_cancel_records_finish_event_with_cancelled_flag(tmp_path, monkeypatch):
    """Observability: the analysis_run_finished event must carry
    cancelled=True so the Monitor UI can distinguish 'user cancelled'
    from 'natural finish with some failures'."""
    for i in range(3):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    state = pl.PipelineState()
    call_count = {"n": 0}
    lock = threading.Lock()

    def analyze(path, **_kw):
        with lock:
            call_count["n"] += 1
            n = call_count["n"]
        if n == 1:
            state.cancel()
        return _mock_result(n), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", analyze)

    class _NoopBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
        state=state,
    )

    # Inspect the events DB. It lives in HAPPY_VISION_HOME (configured
    # by conftest to a temp dir), so find it and check.
    from modules.event_store import EventStore
    es = EventStore()
    try:
        events = es.get_recent(limit=50)
    finally:
        es.close()

    finished = [e for e in events if e["event_type"] == "analysis_run_finished"]
    assert finished, "analysis_run_finished event missing"
    details = finished[0]["details"]  # already parsed to dict
    assert details.get("cancelled") is True
