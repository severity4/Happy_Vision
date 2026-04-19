"""tests/hardening/test_f6_dry_run.py

Hardening F6: dry-run 模式真的不寫入 photo 檔。

Happy Vision 沒有獨立 `--dry-run` flag；同等效果是 `write_metadata=False`
（CLI 的 `--write-metadata` 未帶即為 False）。這個路徑必須嚴格：
- 不 instantiate ExiftoolBatch（不 spawn perl 子 process，零污染風險）
- 不呼叫 metadata_writer 任何路徑
- 但結果仍存進 SQLite（讓使用者先 preview 分析結果、再決定要不要寫）
- photo 檔 bytes 完全不變

真實情境：同事第一次跑 dogfood 會 paranoid 地只用 dry-run（不想動照片），
要確定我們承諾的「不寫 metadata」是一個字節都不改。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from modules import pipeline as pl
from modules.result_store import ResultStore


_MOCK_USAGE = {
    "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


def _mock_result():
    return {
        "title": "t", "description": "d", "keywords": ["k"],
        "category": "other", "scene_type": "indoor",
        "mood": "neutral", "people_count": 0,
        "identified_people": [], "ocr_text": [],
    }


def _write_jpg(path: Path) -> None:
    Image.new("RGB", (64, 64), color="white").save(str(path), format="JPEG")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_dry_run_leaves_photo_bytes_unchanged(tmp_path, monkeypatch):
    """Core contract: write_metadata=False → SHA-256 of photo bytes is
    identical before and after the pipeline runs."""
    photos = [tmp_path / f"p{i:02d}.jpg" for i in range(3)]
    for p in photos:
        _write_jpg(p)

    before = {p.name: _sha256(p) for p in photos}

    monkeypatch.setattr(pl, "analyze_photo",
                        lambda path, **kw: (_mock_result(), _MOCK_USAGE))

    pl.run_pipeline(
        folder=str(tmp_path), api_key="k", concurrency=1,
        write_metadata=False, db_path=tmp_path / "r.db",
    )

    after = {p.name: _sha256(p) for p in photos}
    assert before == after, (
        "dry-run modified photo bytes — "
        f"changed: {[n for n in before if before[n] != after[n]]}"
    )


def test_dry_run_does_not_instantiate_exiftool_batch(tmp_path, monkeypatch):
    """Zero perl subprocess spawned when write_metadata=False."""
    _write_jpg(tmp_path / "p.jpg")

    monkeypatch.setattr(pl, "analyze_photo",
                        lambda path, **kw: (_mock_result(), _MOCK_USAGE))

    ctor_calls = {"n": 0}

    class _TrackingBatch:
        def __init__(self): ctor_calls["n"] += 1
        def write(self, *a, **kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _TrackingBatch)

    pl.run_pipeline(
        folder=str(tmp_path), api_key="k", concurrency=1,
        write_metadata=False, db_path=tmp_path / "r.db",
    )

    assert ctor_calls["n"] == 0, (
        "write_metadata=False still constructed ExiftoolBatch — leaks a "
        "perl process + defeats dry-run's 'no side effects' guarantee"
    )


def test_dry_run_still_persists_result_to_store(tmp_path, monkeypatch):
    """User wants to preview analysis results — SQLite persistence must
    still happen even in dry-run."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    monkeypatch.setattr(pl, "analyze_photo",
                        lambda path, **kw: (_mock_result(), _MOCK_USAGE))

    db_path = tmp_path / "r.db"
    results = pl.run_pipeline(
        folder=str(tmp_path), api_key="k", concurrency=1,
        write_metadata=False, db_path=db_path,
    )

    assert len(results) == 1

    # Verify persistence
    store = ResultStore(db_path)
    row = store.conn.execute(
        "SELECT status, result_json FROM results WHERE file_path = ?",
        (str(photo),),
    ).fetchone()
    assert row is not None
    assert row["status"] == "completed"
    import json
    assert json.loads(row["result_json"])["title"] == "t"
    store.close()


def test_dry_run_write_metadata_true_actually_writes_args(tmp_path, monkeypatch):
    """Regression guard flip side: write_metadata=True DOES call
    exiftool. Otherwise the 'write' path would silently dry-run."""
    _write_jpg(tmp_path / "p.jpg")

    monkeypatch.setattr(pl, "analyze_photo",
                        lambda path, **kw: (_mock_result(), _MOCK_USAGE))

    write_calls = []

    class _TrackingBatch:
        def write(self, photo_path, args):
            write_calls.append((photo_path, args))
            return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _TrackingBatch)

    pl.run_pipeline(
        folder=str(tmp_path), api_key="k", concurrency=1,
        write_metadata=True, db_path=tmp_path / "r.db",
    )

    assert len(write_calls) == 1, (
        "write_metadata=True did NOT call ExiftoolBatch.write — "
        "the 'real' mode is broken"
    )
    assert any("-IPTC:Headline=" in a for a in write_calls[0][1])
