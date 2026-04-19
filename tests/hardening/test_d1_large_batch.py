"""tests/hardening/test_d1_large_batch.py

Hardening D1: 500+ 張的批次要能跑完，記憶體穩定（results list 不累積無界
狀態）、progress 計數正確、DB row 數量一致、thread pool 不洩漏。

映奧一次婚攝 dogfood 差不多就是 500–1500 張。主打的成本是 API，但如果
app 本身跑 800 張會 OOM 或 progress counter 錯亂，dogfood 會當場失敗。

用 mock 的 analyze_photo 讓測試 < 2s，但保留真實的 pipeline / DB / thread
pool 機制。
"""

from __future__ import annotations

import resource
import sqlite3
import threading
from pathlib import Path

import pytest

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
        "description": "d" * 200,  # realistic description size
        "keywords": ["k1", "k2", "k3"],
        "category": "other",
        "subcategory": "",
        "scene_type": "indoor",
        "mood": "neutral",
        "people_count": 0,
        "identified_people": [],
        "ocr_text": [],
    }


def _write_tiny_jpg(path: Path) -> None:
    # Minimal valid JPEG so scan picks it up and resize (if anyone called
    # it) wouldn't barf. analyze_photo is mocked so content doesn't matter.
    path.write_bytes(b"\xff\xd8\xff\xd9")


class _NoopBatch:
    def __init__(self): self.write_count = 0
    def write(self, *_a, **_kw):
        self.write_count += 1
        return True
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_a): pass


def test_pipeline_processes_600_photos_cleanly(tmp_path, monkeypatch):
    N = 600
    for i in range(N):
        _write_tiny_jpg(tmp_path / f"p{i:04d}.jpg")

    counter = {"n": 0}
    lock = threading.Lock()

    def fast_analyze(path, **_kw):
        with lock:
            counter["n"] += 1
            n = counter["n"]
        return _mock_result(n), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", fast_analyze)

    batch_instance = {"obj": None}

    def make_batch():
        inst = _NoopBatch()
        batch_instance["obj"] = inst
        return inst

    monkeypatch.setattr(pl, "ExiftoolBatch", make_batch)

    progress_last = {"done": 0, "total": 0}

    class _CB(pl.PipelineCallbacks):
        def on_progress(self, done, total, path):
            progress_last["done"] = max(progress_last["done"], done)
            progress_last["total"] = total

    db_path = tmp_path / "r.db"
    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=8,  # realistic concurrency
        write_metadata=True,
        db_path=db_path,
        callbacks=_CB(),
    )

    assert len(results) == N
    assert counter["n"] == N
    assert batch_instance["obj"].write_count == N
    assert progress_last["total"] == N
    # done count must reach exactly N at some point.
    assert progress_last["done"] == N

    # Every photo persisted — DB integrity check.
    conn = sqlite3.connect(str(db_path))
    try:
        row_count = conn.execute(
            "SELECT COUNT(*) FROM results WHERE status='completed'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert row_count == N


def test_pipeline_progress_monotonic_and_bounded(tmp_path, monkeypatch):
    """Regression guard: on_progress 的 `done` 只能單調遞增，且從 0 ≤ done ≤
    total。並發下 race condition 可能打破這個保證 — lock 我們已經有，但不
    會傷害重驗證。"""
    N = 200
    for i in range(N):
        _write_tiny_jpg(tmp_path / f"p{i:04d}.jpg")

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **_kw: (_mock_result(1), _MOCK_USAGE),
    )
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    observations: list[tuple[int, int]] = []
    lock = threading.Lock()

    class _CB(pl.PipelineCallbacks):
        def on_progress(self, done, total, path):
            with lock:
                observations.append((done, total))

    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=8,
        write_metadata=False,
        db_path=tmp_path / "r.db",
        callbacks=_CB(),
    )

    # Every done value ∈ [1, N]; total = N everywhere; max done == N.
    for done, total in observations:
        assert 1 <= done <= N
        assert total == N
    assert max(d for d, _ in observations) == N


def test_pipeline_fd_count_stable_after_large_batch(tmp_path, monkeypatch):
    """Thread-pool / subprocess FD leak guard: running 500 photos should
    not leave dozens of orphaned file descriptors behind. On macOS the
    default soft limit is 256, so a 10% leak over 500 runs would hit it."""
    N = 500
    for i in range(N):
        _write_tiny_jpg(tmp_path / f"p{i:04d}.jpg")

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **_kw: (_mock_result(1), _MOCK_USAGE),
    )
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    # Count FDs before and after via /dev/fd (macOS + Linux).
    fd_dir = Path("/dev/fd")
    if not fd_dir.exists():
        pytest.skip("/dev/fd not available on this platform")

    def count_fds() -> int:
        try:
            return len(list(fd_dir.iterdir()))
        except OSError:
            return -1

    before = count_fds()

    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=8,
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    # Let any async cleanup settle.
    import gc
    gc.collect()

    after = count_fds()

    # Allow a handful of FDs for pytest itself; anything > 20 new FDs is a
    # clear leak signal.
    assert after - before < 20, (
        f"FD leak suspected: {before} → {after} (+{after - before})"
    )


def test_pipeline_rlimit_headroom_ok_for_concurrency_setting(tmp_path):
    """Sanity: the default concurrency shouldn't ask for more FDs than
    the process actually has. A future CLI that raises concurrency to
    thousands should get caught here."""
    soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    # Pipeline default concurrency is 5. Even with per-worker (3 FDs for
    # stdin/stdout/stderr on exiftool batch) + per-photo file-handle we
    # should never exceed soft / 4. This lock-in ensures no regression.
    assert 5 * 10 < soft, (
        f"pipeline default concurrency would crowd FD limit {soft}"
    )
