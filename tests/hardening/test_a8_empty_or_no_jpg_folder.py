"""tests/hardening/test_a8_empty_or_no_jpg_folder.py

Hardening A8: 空資料夾 / 只有非 JPG / 資料夾不存在 → pipeline 不 crash，
on_complete(0, 0) 被呼叫，report_generator 產出空 report（不中斷）。

現實情境：同事選錯資料夾（選到 `~/Desktop` 而不是 `~/Desktop/活動照片`），
目前畫面要能告訴他「沒找到 JPG」而不是無限轉圈、500 error 或 silently 啥事
都沒發生讓他以為軟體掛了。
"""

from __future__ import annotations

from pathlib import Path

from modules import pipeline as pl
from modules.pipeline import scan_photos
from modules.report_generator import generate_csv, generate_json


def test_scan_empty_folder_returns_empty_list(tmp_path):
    photos = scan_photos(str(tmp_path))
    assert photos == []


def test_scan_folder_with_only_non_jpg_files_returns_empty(tmp_path):
    (tmp_path / "readme.txt").write_text("hello")
    (tmp_path / "photo.png").write_bytes(b"\x89PNG")
    (tmp_path / "raw.heic").write_bytes(b"heic")
    (tmp_path / "notes.pdf").write_bytes(b"%PDF-")

    photos = scan_photos(str(tmp_path))

    assert photos == []


def test_scan_nonexistent_folder_returns_empty(tmp_path):
    missing = tmp_path / "does-not-exist-at-all"
    # Sanity check the path really isn't there.
    assert not missing.exists()

    photos = scan_photos(str(missing))
    assert photos == []


def test_scan_file_instead_of_folder_returns_empty(tmp_path):
    """If caller accidentally passes a file path instead of a directory,
    must not crash — just produce nothing."""
    f = tmp_path / "not-a-dir.txt"
    f.write_text("x")
    photos = scan_photos(str(f))
    assert photos == []


def test_pipeline_on_empty_folder_calls_on_complete_0_0(tmp_path, monkeypatch):
    """Empty folder pipeline must still call on_complete so the UI can
    reset the spinner; and MUST NOT call analyze_photo (which would burn
    API quota for nothing)."""
    progress_calls: list[tuple[int, int, str]] = []
    complete_calls: list[tuple[int, int]] = []
    api_calls: list[str] = []

    class _CB(pl.PipelineCallbacks):
        def on_progress(self, done, total, path):
            progress_calls.append((done, total, path))

        def on_complete(self, total, failed):
            complete_calls.append((total, failed))

    def boom_analyze(path, **_kw):
        api_calls.append(path)
        raise RuntimeError("must not be called on empty folder")

    monkeypatch.setattr(pl, "analyze_photo", boom_analyze)

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
        callbacks=_CB(),
    )

    assert results == []
    assert complete_calls == [(0, 0)]
    assert progress_calls == []  # no photos ever processed
    assert api_calls == []  # crucially, no Gemini calls


def test_pipeline_on_nonjpg_only_folder_no_api_calls(tmp_path, monkeypatch):
    (tmp_path / "a.png").write_bytes(b"\x89PNG")
    (tmp_path / "b.txt").write_text("x")

    api_calls: list[str] = []

    def tracking(path, **_kw):
        api_calls.append(path)
        return None, None

    monkeypatch.setattr(pl, "analyze_photo", tracking)

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    assert results == []
    assert api_calls == []


def test_report_generator_handles_empty_results(tmp_path):
    """G4-adjacent: empty pipeline results must produce valid (empty)
    CSV + JSON files without raising."""
    csv_path = tmp_path / "r.csv"
    json_path = tmp_path / "r.json"

    generate_csv([], csv_path)
    generate_json([], json_path)

    # CSV: header row only
    csv_lines = [ln for ln in csv_path.read_text().splitlines() if ln.strip()]
    assert len(csv_lines) == 1
    # JSON: empty list
    import json as _json
    assert _json.loads(json_path.read_text()) == []
