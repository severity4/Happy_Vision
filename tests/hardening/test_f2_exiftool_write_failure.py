"""tests/hardening/test_f2_exiftool_write_failure.py

Hardening F2: exiftool 寫入失敗（檔案權限 / 另一個程序鎖定 / 唯讀檔）→
錯誤記錄但不污染 result_store — 該張標記 failed 狀態，Gemini 分析結果
**不**寫 `completed` row（否則 resume 時會被跳過，使用者永遠得不到
metadata）。

真實情境：
- 同事把照片資料夾設為 Read Only（或 macOS 鎖定檔案）
- Lightroom 同時開著該照片
- 外接 NAS 掛載但權限是 read-only

合約：只有 analyze_photo 成功 **且** metadata write 成功才算 completed。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from modules import pipeline as pl


_MOCK_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


def _mock_result(name: str) -> dict:
    return {
        "title": f"t-{name}",
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
    Image.new("RGB", (32, 32), color="white").save(str(path), format="JPEG")


class _AlwaysFailBatch:
    """Simulates exiftool write always failing."""
    def write(self, *_a, **_kw): return False
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_a): pass


class _SelectiveFailBatch:
    """Fails for specific filenames only."""
    def __init__(self, fail_names=()):
        self.fail_names = set(fail_names)
        self.writes = []

    def write(self, photo_path, _args):
        self.writes.append(photo_path)
        return Path(photo_path).name not in self.fail_names

    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_a): pass


def test_metadata_write_failure_marks_photo_failed_not_completed(
    tmp_path, monkeypatch,
):
    _write_jpg(tmp_path / "p.jpg")

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **_kw: (_mock_result("ok"), _MOCK_USAGE),
    )
    monkeypatch.setattr(pl, "ExiftoolBatch", _AlwaysFailBatch)

    db_path = tmp_path / "r.db"
    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=db_path,
    )

    # No successful results — metadata write failure = full failure.
    assert results == []

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT status FROM results").fetchall()
    finally:
        conn.close()

    # One row, status=failed (NOT completed).
    assert len(rows) == 1
    assert rows[0][0] == "failed"


def test_metadata_write_failure_does_not_save_completed_row(
    tmp_path, monkeypatch,
):
    """Critical for resume semantics: if we saved the row as completed
    despite the metadata not being on disk, next run's skip_existing
    would skip this photo forever. The user would never get IPTC tags."""
    _write_jpg(tmp_path / "p.jpg")

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **_kw: (_mock_result("ok"), _MOCK_USAGE),
    )
    monkeypatch.setattr(pl, "ExiftoolBatch", _AlwaysFailBatch)

    db_path = tmp_path / "r.db"
    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=db_path,
    )

    conn = sqlite3.connect(str(db_path))
    try:
        completed = conn.execute(
            "SELECT COUNT(*) FROM results WHERE status='completed'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert completed == 0, (
        "metadata write failed but row saved as 'completed' — future "
        "skip_existing will never retry, user will never get IPTC tags"
    )


def test_mixed_batch_write_failures_do_not_halt_good_photos(
    tmp_path, monkeypatch,
):
    """Photo A: write fails. Photo B: write succeeds. Batch must
    process both; A=failed, B=completed."""
    _write_jpg(tmp_path / "a.jpg")
    _write_jpg(tmp_path / "b.jpg")

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **_kw: (_mock_result(Path(path).name), _MOCK_USAGE),
    )

    fail_batch = _SelectiveFailBatch(fail_names={"a.jpg"})
    monkeypatch.setattr(pl, "ExiftoolBatch", lambda: fail_batch)

    db_path = tmp_path / "r.db"
    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=db_path,
    )

    assert len(results) == 1
    assert results[0]["title"] == "t-b.jpg"

    conn = sqlite3.connect(str(db_path))
    try:
        rows = dict(conn.execute(
            "SELECT file_path, status FROM results"
        ).fetchall())
    finally:
        conn.close()

    statuses = {Path(fp).name: st for fp, st in rows.items()}
    assert statuses["a.jpg"] == "failed"
    assert statuses["b.jpg"] == "completed"


def test_write_failure_can_be_retried_on_resume(tmp_path, monkeypatch):
    """A photo that failed due to metadata write can be retried on the
    next pipeline run. Verifies the failure is not terminal in the DB
    sense — re-run with fixed permissions and it should complete."""
    _write_jpg(tmp_path / "p.jpg")

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **_kw: (_mock_result("ok"), _MOCK_USAGE),
    )

    # Round 1: writes all fail → photo marked failed.
    monkeypatch.setattr(pl, "ExiftoolBatch", _AlwaysFailBatch)
    db_path = tmp_path / "r.db"
    pl.run_pipeline(
        folder=str(tmp_path), api_key="test", concurrency=1,
        write_metadata=True, db_path=db_path,
    )

    conn = sqlite3.connect(str(db_path))
    try:
        status_r1 = conn.execute(
            "SELECT status FROM results"
        ).fetchone()[0]
    finally:
        conn.close()
    assert status_r1 == "failed"

    # Round 2: writes succeed (simulated "user fixed permissions").
    class _OKBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _OKBatch)
    results = pl.run_pipeline(
        folder=str(tmp_path), api_key="test", concurrency=1,
        write_metadata=True, db_path=db_path, skip_existing=True,
    )

    # Previously failed photo should be retried (failed != completed).
    assert len(results) == 1

    conn = sqlite3.connect(str(db_path))
    try:
        status_r2 = conn.execute(
            "SELECT status FROM results"
        ).fetchone()[0]
    finally:
        conn.close()
    assert status_r2 == "completed"
