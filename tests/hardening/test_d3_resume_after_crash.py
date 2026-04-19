"""tests/hardening/test_d3_resume_after_crash.py

Hardening D3: pipeline crash / hard-kill 後 resume — 已完成照片必須跳過，
未完成的從中斷點繼續，failed 可在第二輪重試。

現實情境：dogfood 途中同事 Cmd-Q 了視窗；或 macOS 升級重開機；或 API 429
讓腳本自己中止。第二次跑 pipeline 在同一個資料夾時，必須：
- 不重新 call Gemini 算已完成的（省錢）
- 把未完成的 + failed 的繼續做
- SQLite 的 `status` 狀態機是唯一依據，不能被「`file_path` 寫入時格式化差異」騙到
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from modules import pipeline as pl
from modules.result_store import ResultStore


_MOCK_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


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


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (32, 32), color="gray").save(str(path), format="JPEG")


class _NoopBatch:
    def write(self, *_a, **_kw): return True
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_a): pass


def test_resume_skips_completed_photos(tmp_path, monkeypatch):
    """First run: cancel mid-batch after processing 2/5. Second run with
    skip_existing=True must only analyze the remaining 3."""
    for i in range(5):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    # First run — cancel after photo 2 completes.
    state1 = pl.PipelineState()
    round1_calls: list[str] = []
    counter = {"n": 0}
    lock = threading.Lock()

    def analyze_round_1(path, **_kw):
        with lock:
            counter["n"] += 1
            n = counter["n"]
            round1_calls.append(Path(path).name)
            if n >= 2:
                state1.cancel()
        return _mock_result(n), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", analyze_round_1)

    db_path = tmp_path / "r.db"
    r1 = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=db_path,
        state=state1,
    )
    # After cancel, 2 succeeded
    assert len(r1) == 2

    # Verify SQLite has exactly 2 completed rows.
    conn = sqlite3.connect(str(db_path))
    try:
        completed = conn.execute(
            "SELECT file_path FROM results WHERE status='completed'"
        ).fetchall()
    finally:
        conn.close()
    assert len(completed) == 2
    completed_names = {Path(r[0]).name for r in completed}

    # Second run — resume, skip_existing=True.
    round2_calls: list[str] = []

    def analyze_round_2(path, **_kw):
        round2_calls.append(Path(path).name)
        return _mock_result(99), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", analyze_round_2)

    r2 = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=db_path,
        skip_existing=True,
    )

    # Must only touch the 3 remaining; previously completed must be skipped.
    assert len(round2_calls) == 3
    assert not (completed_names & set(round2_calls)), (
        "resume re-analyzed a completed photo — wasting Gemini quota!"
    )
    assert len(r2) == 3


def test_resume_retries_previously_failed_photos(tmp_path, monkeypatch):
    """If a photo was marked failed in round 1 (e.g., transient 500 that
    exhausted retries), round 2 with skip_existing=True should still try
    it again — because failed != completed. Only 'completed' is terminal."""
    _write_jpg(tmp_path / "good.jpg")
    _write_jpg(tmp_path / "was_failed.jpg")

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    # Pre-seed the store: one completed, one failed.
    db_path = tmp_path / "r.db"
    store = ResultStore(db_path)
    try:
        store.save_result(str(tmp_path / "good.jpg"), _mock_result(1), usage=_MOCK_USAGE)
        store.mark_failed(str(tmp_path / "was_failed.jpg"), "transient 500")
    finally:
        store.close()

    # Second run — resume.
    analyzed: list[str] = []

    def analyze(path, **_kw):
        analyzed.append(Path(path).name)
        return _mock_result(2), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", analyze)

    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=db_path,
        skip_existing=True,
    )

    # good.jpg skipped; was_failed.jpg retried.
    assert analyzed == ["was_failed.jpg"]


def test_resume_uses_exact_path_as_key_not_normalized_form(tmp_path, monkeypatch):
    """Regression guard: if someone ever changes save_result to normalize
    the path (e.g., resolve symlinks or lowercase), is_processed() during
    resume would miss the row and re-bill Gemini. Lock in that the exact
    string we pass in is the exact string stored and checked."""
    _write_jpg(tmp_path / "P.jpg")  # note uppercase letter

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)
    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **_kw: (_mock_result(1), _MOCK_USAGE),
    )

    db_path = tmp_path / "r.db"
    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=db_path,
    )

    store = ResultStore(db_path)
    try:
        # The exact path scan_photos emits must round-trip.
        scanned = pl.scan_photos(str(tmp_path))
        assert len(scanned) == 1
        assert store.is_processed(scanned[0]) is True
    finally:
        store.close()


def test_resume_is_idempotent_across_three_runs(tmp_path, monkeypatch):
    """Paranoia: running the pipeline 3 times in a row on the same folder
    must analyze each photo exactly once total (first run), then skip all
    on runs 2 and 3. Past bugs where an ALTER TABLE migration wiped
    `status` would only surface as a regression here."""
    for i in range(3):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    totals = {"n": 0}
    lock = threading.Lock()

    def analyze(path, **_kw):
        with lock:
            totals["n"] += 1
        return _mock_result(1), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", analyze)

    db_path = tmp_path / "r.db"
    for _ in range(3):
        pl.run_pipeline(
            folder=str(tmp_path),
            api_key="test",
            concurrency=1,
            write_metadata=False,
            db_path=db_path,
            skip_existing=True,
        )

    assert totals["n"] == 3, f"idempotent resume broke: analyzed {totals['n']} times"
