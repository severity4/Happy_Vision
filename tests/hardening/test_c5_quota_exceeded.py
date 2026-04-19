"""tests/hardening/test_c5_quota_exceeded.py

Hardening C5: Gemini 回 403 / quota exhausted / billing required → 立即
halt 批次，**剩餘照片保持 pending 狀態**（沒有失敗紀錄弄髒 DB），使用者
解決帳單後重跑 pipeline 能從中斷點繼續。

和 C3 (invalid key) 共用 halt 機制。差別：
- C3 = 你輸錯 key，通常 3 秒內發現
- C5 = 付費 tier 過期 / 今日 quota 用完，可能在半小時後第 500 張才出現

C5 多了「剩餘照片必須 resume-able」這個要求：若我們把沒分析到的 400 張都
標成 `failed`，未來 resume 時它們會被當 retry 目標再次打 API，又再次 403 —
死循環。所以 halt 必須只 mark 當前這張 failed，不動其他。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from modules import gemini_vision
from modules import pipeline as pl
from modules.gemini_vision import InvalidAPIKeyError, analyze_photo


_MOCK_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (64, 64), color=(50, 50, 50)).save(str(path), format="JPEG")


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


class _NoopBatch:
    def write(self, *_a, **_kw): return True
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_a): pass


def test_analyze_photo_raises_on_permission_denied_403(tmp_path, monkeypatch):
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    class _Models:
        def generate_content(self, **_kw):
            raise Exception("403 PERMISSION_DENIED: Quota exceeded for project")

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    with pytest.raises(InvalidAPIKeyError):
        analyze_photo(str(photo), api_key="k", model="lite", max_retries=1)


def test_pipeline_halt_on_quota_leaves_remaining_photos_unstored(
    tmp_path, monkeypatch,
):
    """Crucial resume property: if photo 3/10 hits quota halt, photos 4–10
    must have NO row in the DB (not even a failed one), so a second-run
    resume will re-enqueue them as pristine work. Marking them all failed
    would create the death-loop described in the module docstring."""
    for i in range(10):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    counter = {"n": 0}
    lock = threading.Lock()

    def analyze(path, **_kw):
        with lock:
            counter["n"] += 1
            n = counter["n"]
        if n <= 2:
            return _mock_result(n), _MOCK_USAGE
        raise InvalidAPIKeyError("403 PERMISSION_DENIED: Quota exceeded")

    monkeypatch.setattr(pl, "analyze_photo", analyze)
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    db_path = tmp_path / "r.db"
    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=db_path,
    )

    assert len(results) == 2

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT file_path, status FROM results"
        ).fetchall()
    finally:
        conn.close()

    statuses = {Path(fp).name: status for fp, status in rows}
    # 2 completed (photos 0 and 1)
    assert statuses.get("p00.jpg") == "completed"
    assert statuses.get("p01.jpg") == "completed"
    # The photo that hit quota is marked failed with a clear reason
    assert statuses.get("p02.jpg") == "failed"
    # Critically: remaining 7 photos MUST NOT have any row. If they do,
    # resume will see them as "failed" and try again → same quota error.
    for i in range(3, 10):
        assert f"p{i:02d}.jpg" not in statuses, (
            f"pipeline prematurely stored p{i:02d}.jpg — breaks clean resume"
        )


def test_resume_after_quota_halt_picks_up_remaining_photos(tmp_path, monkeypatch):
    """End-to-end: batch 1 halts at photo 3 (quota). Next day, resume
    batch — the remaining photos must be analyzed now that quota is
    restored. The 1 photo that got marked failed also retries (that's
    baseline resume semantics from D3)."""
    for i in range(5):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    # Round 1: succeed twice, quota-halt on third.
    counter1 = {"n": 0}
    lock1 = threading.Lock()

    def analyze_r1(path, **_kw):
        with lock1:
            counter1["n"] += 1
            n = counter1["n"]
        if n <= 2:
            return _mock_result(n), _MOCK_USAGE
        raise InvalidAPIKeyError("403 PERMISSION_DENIED: Quota exceeded")

    monkeypatch.setattr(pl, "analyze_photo", analyze_r1)
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    db_path = tmp_path / "r.db"
    r1 = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=db_path,
    )
    assert len(r1) == 2

    # Round 2: quota restored, everything succeeds.
    round2_calls: list[str] = []

    def analyze_r2(path, **_kw):
        round2_calls.append(Path(path).name)
        return _mock_result(99), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", analyze_r2)

    r2 = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=db_path,
        skip_existing=True,
    )

    # The 2 completed photos skip. The 1 failed photo + 2 untouched
    # photos all analyze in round 2 → 3 new results.
    assert len(r2) == 3
    assert len(round2_calls) == 3
    # The two already-completed photos must NOT be re-analyzed.
    assert "p00.jpg" not in round2_calls
    assert "p01.jpg" not in round2_calls
