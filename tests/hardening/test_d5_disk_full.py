"""tests/hardening/test_d5_disk_full.py

Hardening D5: 磁碟滿 → SQLite 寫入失敗時優雅處理，使用者看得懂。

真實情境：跑一批 500 張照片到一半 Mac 磁碟滿了，SQLite 回
`OperationalError: database or disk is full`。我們需要：
- 清楚的錯誤訊息（不是 unhelpful stack trace）
- 先前已成功儲存的照片結果保留
- 資源（ExiftoolBatch, EventStore）被正確清理，不留殭屍 process

合約：
- `save_result` 遇到 OperationalError → 讓錯誤 propagate 到 pipeline 外層
- pipeline `finally` 區塊仍然關掉 ExiftoolBatch、EventStore
- 下次啟動仍能讀取先前已存的結果（WAL 沒有損壞）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from modules import pipeline as pl
from modules.result_store import ResultStore


_MOCK_USAGE = {
    "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


def _mock_result(title: str = "t") -> dict:
    return {
        "title": title, "description": "d", "keywords": ["k"],
        "category": "other", "scene_type": "indoor",
        "mood": "neutral", "people_count": 0,
        "identified_people": [], "ocr_text": [],
    }


def _write_jpg(path: Path) -> None:
    Image.new("RGB", (32, 32), color="white").save(str(path), format="JPEG")


class _NoopBatch:
    def write(self, *_a, **_kw): return True
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_a): pass


# ---------- save_result propagates disk-full error ----------

class _DiskFullConnection:
    """Wraps a real sqlite3.Connection but raises OperationalError on
    INSERT / UPDATE. Read queries still work, so schema setup succeeds."""

    def __init__(self, real_conn):
        self._conn = real_conn

    def execute(self, sql, *args, **kwargs):
        if sql.strip().upper().startswith(("INSERT", "UPDATE")):
            raise sqlite3.OperationalError("database or disk is full")
        return self._conn.execute(sql, *args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_result_store_save_result_propagates_operational_error(tmp_path):
    """If SQLite raises OperationalError on disk full, save_result must
    propagate — caller can react rather than silently drop results."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    store = ResultStore(tmp_path / "r.db")
    store.conn = _DiskFullConnection(store.conn)

    with pytest.raises(sqlite3.OperationalError, match="disk is full"):
        store.save_result(str(photo), _mock_result(), usage=_MOCK_USAGE, cost_usd=0.001)


def test_mark_failed_also_propagates_on_disk_full(tmp_path):
    """mark_failed writes a row via UPDATE / INSERT. On disk-full it must
    surface the error rather than silently no-op."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    store = ResultStore(tmp_path / "r.db")
    store.conn = _DiskFullConnection(store.conn)

    with pytest.raises(sqlite3.OperationalError):
        store.mark_failed(str(photo), "some error")


# ---------- pipeline: earlier successes preserved before disk fills ----------

def test_pipeline_preserves_earlier_successes_before_disk_fills(
    tmp_path, monkeypatch,
):
    """4 photos. First 2 saved OK, 3rd hits 'disk full'. The 2 already
    committed results must remain queryable — no rollback of prior work.
    The pipeline propagates the error to the caller."""
    for i in range(4):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    monkeypatch.setattr(pl, "analyze_photo",
                        lambda p, **kw: (_mock_result("ok"), _MOCK_USAGE))
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    # Patch ResultStore.save_result to fail after 2 successes
    original_save = ResultStore.save_result
    call_count = {"n": 0}

    def flaky_save(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] > 2:
            raise sqlite3.OperationalError("database or disk is full")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(ResultStore, "save_result", flaky_save)

    db_path = tmp_path / "r.db"
    with pytest.raises(sqlite3.OperationalError):
        pl.run_pipeline(
            folder=str(tmp_path), api_key="k", concurrency=1,
            write_metadata=False, db_path=db_path,
        )

    # Re-open store after the crash; first 2 saves should have committed.
    # (concurrency=1 means deterministic ordering — the first 2 commits win.)
    recovered = ResultStore(db_path)
    rows = recovered.conn.execute(
        "SELECT COUNT(*) as n FROM results WHERE status = 'completed'"
    ).fetchone()
    assert rows["n"] == 2, (
        f"expected 2 committed rows before disk-full, got {rows['n']} — "
        "disk-full rolled back earlier commits"
    )
    recovered.close()


def test_pipeline_releases_resources_on_disk_full(tmp_path, monkeypatch):
    """Regression guard: even when save_result raises, the `finally` block
    must still close the ExiftoolBatch and EventStore — else the next run
    inherits a leaked exiftool process."""
    _write_jpg(tmp_path / "p.jpg")

    monkeypatch.setattr(pl, "analyze_photo",
                        lambda p, **kw: (_mock_result(), _MOCK_USAGE))

    close_calls = {"batch": 0}

    class _TrackingBatch:
        def write(self, *_a, **_kw): return True
        def close(self): close_calls["batch"] += 1
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _TrackingBatch)

    def always_fail(self, *args, **kwargs):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(ResultStore, "save_result", always_fail)

    with pytest.raises(sqlite3.OperationalError):
        pl.run_pipeline(
            folder=str(tmp_path), api_key="k", concurrency=1,
            write_metadata=True,  # forces ExiftoolBatch creation
            db_path=tmp_path / "r.db",
        )

    assert close_calls["batch"] == 1, (
        "ExiftoolBatch.close() was skipped on disk-full — leaks a perl "
        "process on every failure"
    )


def test_result_store_reopens_after_disk_full(tmp_path):
    """Once the user frees space, re-opening the DB must work and previous
    saved rows must be intact (SQLite WAL handles partial writes)."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)
    db_path = tmp_path / "r.db"

    # Write 1 row
    s1 = ResultStore(db_path)
    s1.save_result(str(photo), _mock_result("first"),
                   usage=_MOCK_USAGE, cost_usd=0.001)
    s1.close()

    # Simulate a later session re-opening the DB — it should see the row
    s2 = ResultStore(db_path)
    rows = s2.conn.execute(
        "SELECT result_json FROM results WHERE status = 'completed'"
    ).fetchall()
    assert len(rows) == 1
    import json
    assert json.loads(rows[0]["result_json"])["title"] == "first"
    s2.close()
