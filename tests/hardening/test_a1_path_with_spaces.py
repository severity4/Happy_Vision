"""tests/hardening/test_a1_path_with_spaces.py

Hardening A1: 路徑含空格時，scan → analyze → metadata write 全鏈路不 crash，
結果正確寫入 result_store。

同事拖進視窗的資料夾很可能叫 `2026 春季活動/阿伯演講 1/`。scan_photos
用 pathlib.rglob，分析走 analyze_photo(photo_path=str)，metadata 走
exiftool CLI，任何一層對空格處理錯誤都會導致首次 demo 翻車。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from modules import pipeline as pl
from modules.metadata_writer import build_exiftool_args
from modules.pipeline import scan_photos


_MOCK_USAGE = {
    "input_tokens": 100,
    "output_tokens": 20,
    "total_tokens": 120,
    "model": "gemini-2.5-flash-lite",
}


def _mock_result(title: str) -> dict:
    return {
        "title": title,
        "description": "desc with a space",
        "keywords": ["kw one", "kw two"],
        "category": "other",
        "subcategory": "",
        "scene_type": "indoor",
        "mood": "neutral",
        "people_count": 0,
        "identified_people": [],
        "ocr_text": [],
    }


def test_scan_photos_finds_files_in_folder_with_spaces(tmp_path):
    folder = tmp_path / "my photos 2026"
    folder.mkdir()
    (folder / "group photo.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (folder / "another one.JPEG").write_bytes(b"\xff\xd8\xff\xd9")

    photos = scan_photos(str(folder))

    assert len(photos) == 2
    names = {Path(p).name for p in photos}
    assert names == {"group photo.jpg", "another one.JPEG"}
    # Every returned path must still point at an existing file — proves we
    # didn't return a shell-quoted or otherwise mangled path.
    for p in photos:
        assert Path(p).is_file()


def test_scan_photos_handles_nested_folder_with_spaces(tmp_path):
    root = tmp_path / "2026 春季活動"  # mixed spaces + non-ASCII
    nested = root / "演講 第一場"
    nested.mkdir(parents=True)
    (nested / "stage shot.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    photos = scan_photos(str(root))

    assert len(photos) == 1
    assert Path(photos[0]).name == "stage shot.jpg"
    assert Path(photos[0]).is_file()


def test_pipeline_analyzes_photo_in_folder_with_spaces(tmp_path, monkeypatch):
    """Full pipeline (analyze + write_metadata) against a spacey path."""
    folder = tmp_path / "my photos 2026"
    folder.mkdir()
    photo = folder / "group photo.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xd9")

    analyze_calls: list[str] = []

    def fake_analyze(path, **_kw):
        analyze_calls.append(path)
        return _mock_result("Group photo"), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", fake_analyze)

    writes: list[tuple[str, list[str]]] = []

    class FakeBatch:
        def write(self, path, args):
            writes.append((path, args))
            return True

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            pass

    monkeypatch.setattr(pl, "ExiftoolBatch", FakeBatch)

    db_path = tmp_path / "results with space.db"
    results = pl.run_pipeline(
        folder=str(folder),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=db_path,
    )

    assert len(results) == 1
    assert len(analyze_calls) == 1
    assert " " in analyze_calls[0]  # path still contained the space when passed through
    assert Path(analyze_calls[0]) == photo

    assert len(writes) == 1
    written_path, _args = writes[0]
    assert Path(written_path) == photo

    # Result must be persisted using the *exact* path as key. If somewhere in
    # the stack did a shell-unsafe os.system / .split() we'd store a mangled
    # key and is_processed() would miss it on resume.
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT file_path, result_json FROM results"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert Path(row[0]) == photo
    payload = json.loads(row[1])
    assert payload["title"] == "Group photo"


def test_exiftool_args_allow_value_containing_spaces():
    """build_exiftool_args must NOT pre-quote or split values containing
    spaces — the ExiftoolBatch stdin protocol is one-arg-per-line, so
    anything containing a space is a single arg and exiftool sees it whole."""
    result = _mock_result("My Title With Spaces")
    args = build_exiftool_args(result)

    # The headline tag should keep the raw value intact (not wrapped in
    # quotes). Shell-quoting here would double-escape when exiftool reads
    # from stdin.
    assert "-IPTC:Headline=My Title With Spaces" in args
    # Keyword with space must survive as a single arg.
    assert "-IPTC:Keywords=kw one" in args
