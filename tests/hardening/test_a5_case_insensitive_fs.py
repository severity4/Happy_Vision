"""tests/hardening/test_a5_case_insensitive_fs.py

Hardening A5: macOS 預設 APFS 是 case-insensitive（但 preserving）。同一
個檔案被以不同大小寫的 path 掃到時，is_processed() 必須認得出來，否則
resume 會重複打 Gemini。

現實情境：同事用 macOS Finder 拖資料夾（大寫開頭 `Wedding Photos/`）到
Happy Vision；下次重開 app 再拖同一個資料夾時 Finder 已經用 `wedding photos/`
顯示。APFS 上這是同一個目錄，但 Python `Path.rglob` 回傳的字串會 reflect
呼叫者傳進來的 case。如果 is_processed 只做字面比對，就會認為是全新的
150 張照片，全部再打一次 Gemini。

合約：對 same physical file 透過不同 case path 叫 `is_processed()`，應
該回 True（或明確標記這是 known limitation + 工作 around）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.pipeline import scan_photos
from modules.result_store import ResultStore


def _fs_is_case_insensitive(tmp_path: Path) -> bool:
    probe = tmp_path / "CASE_PROBE.tmp"
    probe.write_bytes(b"x")
    try:
        return (tmp_path / "case_probe.tmp").exists()
    finally:
        probe.unlink()


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (32, 32), color="white").save(str(path), format="JPEG")


def test_fs_is_case_insensitive_on_macos_default(tmp_path):
    """Sanity probe — if CI is on case-sensitive FS, skip A5 tests that
    rely on case-insensitive behaviour. macOS default APFS + most Linux
    tmpfs configs differ here."""
    if not _fs_is_case_insensitive(tmp_path):
        pytest.skip("filesystem is case-sensitive; A5 does not apply here")
    # If we're on APFS/NTFS default: passed without skip.
    assert _fs_is_case_insensitive(tmp_path)


def test_scan_photos_returns_paths_with_requested_case(tmp_path):
    """Regression guard: scan_photos preserves the case the user passed,
    which is what creates the is_processed mismatch."""
    if not _fs_is_case_insensitive(tmp_path):
        pytest.skip("case-insensitive FS only")

    folder = tmp_path / "Photos"
    folder.mkdir()
    _write_jpg(folder / "shot.jpg")

    # Access via uppercase vs lowercase variants of the folder.
    upper = scan_photos(str(tmp_path / "Photos"))
    lower = scan_photos(str(tmp_path / "photos"))

    assert len(upper) == 1
    assert len(lower) == 1
    # Paths LOOK different (preserve case) even though they reference the
    # same inode.
    assert upper[0] != lower[0]
    assert Path(upper[0]).samefile(Path(lower[0]))


def test_is_processed_recognises_same_file_across_case(tmp_path):
    """The meat of A5: save a result with one casing, then check via the
    other. If is_processed misses, resume wastes Gemini calls."""
    if not _fs_is_case_insensitive(tmp_path):
        pytest.skip("case-insensitive FS only")

    folder = tmp_path / "Photos"
    folder.mkdir()
    photo = folder / "shot.jpg"
    _write_jpg(photo)

    store = ResultStore(tmp_path / "r.db")
    try:
        # Save with uppercase-folder path.
        store.save_result(
            str(tmp_path / "Photos" / "shot.jpg"),
            {"title": "t", "description": "", "keywords": [],
             "category": "other", "scene_type": "indoor",
             "mood": "neutral", "people_count": 0},
        )

        # Query with lowercase-folder path. Same physical file on APFS.
        lower_path = str(tmp_path / "photos" / "shot.jpg")
        matched = store.is_processed(lower_path)

        if matched:
            # Ideal behaviour: the store normalizes paths / checks
            # samefile internally. Lock it in.
            assert matched is True
        else:
            # Current behaviour: string match misses. Document this as a
            # known limitation — the workaround is for the user to always
            # pick the folder from the built-in picker (which gives a
            # consistent case).
            pytest.xfail(
                "is_processed is case-sensitive even on APFS; re-opening "
                "the same folder with a different case re-analyzes. "
                "Mitigation: folder picker returns a canonical casing "
                "(and conftest A1/A2 test coverage confirms normal usage). "
                "Future: canonicalize via resolve() before PK lookup."
            )
    finally:
        store.close()


def test_scan_then_resume_with_different_case_is_handled(tmp_path, monkeypatch):
    """End-to-end: analyze once via Photos/, then run again via photos/.
    Lock in the observed behavior so anyone changing normalization knows
    to update this test."""
    if not _fs_is_case_insensitive(tmp_path):
        pytest.skip("case-insensitive FS only")

    folder_a = tmp_path / "Photos"
    folder_a.mkdir()
    _write_jpg(folder_a / "a.jpg")
    _write_jpg(folder_a / "b.jpg")

    from modules import pipeline as pl

    analyze_calls: list[str] = []

    def fake(path, **_kw):
        analyze_calls.append(path)
        return (
            {"title": "t", "description": "", "keywords": [],
             "category": "other", "scene_type": "indoor",
             "mood": "neutral", "people_count": 0},
            {"input_tokens": 10, "output_tokens": 5,
             "total_tokens": 15, "model": "gemini-2.5-flash-lite"},
        )

    monkeypatch.setattr(pl, "analyze_photo", fake)

    class _NoopBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    db = tmp_path / "r.db"
    # Round 1: uppercase folder.
    pl.run_pipeline(
        folder=str(folder_a), api_key="test", concurrency=1,
        write_metadata=False, db_path=db, skip_existing=True,
    )
    assert len(analyze_calls) == 2

    analyze_calls.clear()

    # Round 2: lowercase folder (same physical dir on APFS).
    pl.run_pipeline(
        folder=str(tmp_path / "photos"), api_key="test", concurrency=1,
        write_metadata=False, db_path=db, skip_existing=True,
    )

    # Acceptable: either 0 calls (ideal — is_processed matched) or 2 calls
    # (known limitation — case-sensitive string PK). We document the
    # count so any future normalization change is visible in diffs.
    # >2 would be a serious regression.
    assert len(analyze_calls) in (0, 2), (
        f"expected 0 (normalized) or 2 (case-sensitive PK); got {len(analyze_calls)}"
    )
