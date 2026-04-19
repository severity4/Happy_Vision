"""tests/hardening/test_d4_parallel_runs.py

Hardening D4: 兩個 pipeline 同時跑在同一個 folder / DB 時不會產生衝突狀態
（SQLite WAL + busy_timeout 是核心防護），前端 /api/analysis/start 的 409
guard 在單機 UI 情境下擋第二次點擊。

真實情境：
- 同事按了「分析」按鈕後 UI 沒即時反應，手指停不下來再按一次 → 409 擋下
- CLI 還在跑，同事不知情打開 GUI 再跑一次 → API 那邊 409 擋不到，只能
  靠 SQLite 併發正確性

合約：
- 兩個並行 run_pipeline 對同一 DB path 跑，SQLite 不 lock-out crash
- 最終每張照片恰好一筆 completed row（不是 2 筆、不是 0 筆）
- pHash prefix index 不重複寫（應該 ok，因為 PRIMARY KEY 在 file_path）
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from modules import pipeline as pl


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


def _write_tiny_jpg(path: Path) -> None:
    path.write_bytes(b"\xff\xd8\xff\xd9")


class _NoopBatch:
    def write(self, *_a, **_kw): return True
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_a): pass


def test_two_parallel_pipelines_same_folder_converge_to_same_db_state(
    tmp_path, monkeypatch,
):
    """Two threads run the pipeline on the same folder with the same DB.
    End state: exactly N completed rows, no duplicates, no crashes."""
    N = 20
    for i in range(N):
        _write_tiny_jpg(tmp_path / f"p{i:02d}.jpg")

    # Mock analyze_photo with a tiny sleep to make the threads actually
    # overlap (otherwise one might finish before the other starts).
    def slow_analyze(path, **_kw):
        time.sleep(0.01)
        return _mock_result(1), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", slow_analyze)
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    db_path = tmp_path / "r.db"
    errors: list[Exception] = []

    def worker():
        try:
            pl.run_pipeline(
                folder=str(tmp_path),
                api_key="test",
                concurrency=2,
                write_metadata=False,
                db_path=db_path,
                skip_existing=True,  # second thread should skip what first did
            )
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    t1 = threading.Thread(target=worker, daemon=True)
    t2 = threading.Thread(target=worker, daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, f"parallel pipelines raised: {errors}"
    assert not t1.is_alive() and not t2.is_alive(), "thread did not finish"

    # Exactly N completed rows (PRIMARY KEY prevents duplicates).
    conn = sqlite3.connect(str(db_path))
    try:
        completed = conn.execute(
            "SELECT COUNT(*) FROM results WHERE status='completed'"
        ).fetchone()[0]
        distinct = conn.execute(
            "SELECT COUNT(DISTINCT file_path) FROM results"
        ).fetchone()[0]
    finally:
        conn.close()

    assert completed == N
    assert distinct == N


def test_concurrent_writes_do_not_trigger_sqlite_lock_error(
    tmp_path, monkeypatch,
):
    """Many threads writing simultaneously: WAL journaling + busy_timeout
    should swallow SQLITE_BUSY and retry. Locking up is a regression."""
    N = 40
    for i in range(N):
        _write_tiny_jpg(tmp_path / f"p{i:03d}.jpg")

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **_kw: (_mock_result(1), _MOCK_USAGE),
    )
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    db_path = tmp_path / "r.db"
    errors: list[Exception] = []

    def worker():
        try:
            pl.run_pipeline(
                folder=str(tmp_path),
                api_key="test",
                concurrency=4,
                write_metadata=False,
                db_path=db_path,
                skip_existing=False,  # force contention
            )
        except sqlite3.OperationalError as e:
            # Specifically the "database is locked" error we're guarding
            # against — elevate to a test failure.
            errors.append(e)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"SQLite lock contention surfaced: {errors}"


def test_api_rejects_second_start_with_409(monkeypatch, tmp_path):
    """When pipeline is already running, /api/analysis/start returns 409
    rather than stomping on the in-flight run. This is the UI-level
    defense (double-click guard)."""
    # Make sure no global pipeline state is left over from other tests.
    from api import analysis as analysis_mod
    analysis_mod._pipeline_thread = None
    analysis_mod._pipeline_state = None

    # Simulate an in-flight pipeline by planting an alive thread.
    keep_running = threading.Event()

    def stay_alive():
        keep_running.wait(timeout=5)

    fake_thread = threading.Thread(target=stay_alive, daemon=True)
    fake_thread.start()
    analysis_mod._pipeline_thread = fake_thread

    try:
        from web_ui import app as _app
        _app.config["TESTING"] = True
        with _app.test_client() as c:
            r = c.post("/api/analysis/start", json={"folder": str(tmp_path)})
        assert r.status_code == 409
        body = r.get_json()
        assert "error" in body
        assert "running" in body["error"].lower() or "already" in body["error"].lower()
    finally:
        keep_running.set()
        fake_thread.join(timeout=1)
        analysis_mod._pipeline_thread = None


def test_completed_row_is_idempotent_under_parallel_double_save(tmp_path):
    """If two threads both call save_result on the same file_path (can
    happen if a race slips past the skip_existing check), the second
    save must update, not duplicate. PRIMARY KEY on file_path already
    enforces this — this test pins it."""
    from modules.result_store import ResultStore

    db_path = tmp_path / "r.db"
    photo_path = "/tmp/p.jpg"

    def saver(title: str):
        store = ResultStore(db_path)
        try:
            store.save_result(photo_path, _mock_result(1) | {"title": title})
        finally:
            store.close()

    t1 = threading.Thread(target=saver, args=("first",), daemon=True)
    t2 = threading.Thread(target=saver, args=("second",), daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT COUNT(*) FROM results WHERE file_path=?", (photo_path,),
        ).fetchone()
    finally:
        conn.close()

    assert rows[0] == 1
