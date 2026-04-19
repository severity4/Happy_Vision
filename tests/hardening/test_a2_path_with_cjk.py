"""tests/hardening/test_a2_path_with_cjk.py

Hardening A2: 路徑含中文（CJK）時全鏈路能正確處理 — scan、分析、寫入 SQLite、
寫入 metadata、讀回來查詢、report 匯出。

映奧大部分資料夾命名就是中文（如 `2026春季活動/阿公生日`）。過去 Python / exiftool
整合踩過 macOS locale 不是 en_US.UTF-8 時 subprocess.run(..., text=True) 會拿
到 mojibake 的坑，這裡把常見情境鎖起來。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from modules import pipeline as pl
from modules.metadata_writer import build_exiftool_args
from modules.pipeline import scan_photos
from modules.result_store import ResultStore


_MOCK_USAGE = {
    "input_tokens": 100,
    "output_tokens": 20,
    "total_tokens": 120,
    "model": "gemini-2.5-flash-lite",
}


def _mock_result() -> dict:
    return {
        "title": "阿伯演講",
        "description": "一位年長的男性站在舞台上演講",
        "keywords": ["演講", "講者", "活動"],
        "category": "panel",
        "subcategory": "",
        "scene_type": "indoor",
        "mood": "formal",
        "people_count": 1,
        "identified_people": [],
        "ocr_text": ["映奧創意"],
    }


def test_scan_photos_finds_cjk_named_files(tmp_path):
    folder = tmp_path / "2026春季活動"
    folder.mkdir()
    (folder / "阿公生日.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (folder / "合照.JPG").write_bytes(b"\xff\xd8\xff\xd9")
    # Mixed: CJK + Japanese kana + Korean hangul
    (folder / "セレモニー 축하 慶祝.jpeg").write_bytes(b"\xff\xd8\xff\xd9")

    photos = scan_photos(str(folder))
    names = {Path(p).name for p in photos}

    assert names == {"阿公生日.jpg", "合照.JPG", "セレモニー 축하 慶祝.jpeg"}
    # Every path must round-trip through the filesystem (no encoding damage).
    for p in photos:
        assert Path(p).is_file()


def test_pipeline_persists_cjk_path_as_primary_key(tmp_path, monkeypatch):
    """file_path is the PRIMARY KEY on results table. If we ever lose or
    re-encode bytes on the way in, is_processed() won't recognise the same
    photo on resume and we'll re-call Gemini (= re-bill)."""
    folder = tmp_path / "阿伯的演講"
    folder.mkdir()
    photo = folder / "開場致詞.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xd9")

    monkeypatch.setattr(
        pl,
        "analyze_photo",
        lambda path, **_kw: (_mock_result(), _MOCK_USAGE),
    )

    writes: list[str] = []

    class FakeBatch:
        def write(self, path, _args):
            writes.append(path)
            return True

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            pass

    monkeypatch.setattr(pl, "ExiftoolBatch", FakeBatch)

    db_path = tmp_path / "結果.db"
    pl.run_pipeline(
        folder=str(folder),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=db_path,
    )

    # exiftool received the exact path (no mojibake).
    assert len(writes) == 1
    assert Path(writes[0]) == photo

    # SQLite key is the exact string with CJK intact.
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT file_path, result_json FROM results").fetchone()
    finally:
        conn.close()
    assert row is not None
    assert Path(row[0]) == photo
    stored_key = row[0]
    assert "阿伯" in stored_key
    assert "開場致詞" in stored_key
    payload = json.loads(row[1])
    assert payload["title"] == "阿伯演講"

    # Resume semantics: re-instantiating ResultStore against the same DB and
    # asking `is_processed(photo_path)` must return True. Regression guard
    # for "CJK key mismatch → re-bills Gemini on every resume".
    store = ResultStore(db_path)
    try:
        assert store.is_processed(str(photo)) is True
    finally:
        store.close()


def test_exiftool_args_carry_cjk_values_verbatim():
    """build_exiftool_args must embed CJK / Japanese / Korean verbatim as
    UTF-8. The ExiftoolBatch stdin protocol is text=True (UTF-8); any arg
    mangling here shows up as `??` in the written IPTC tag."""
    result = {
        "title": "阿伯演講",
        "description": "一位年長男性在舞台",
        "keywords": ["講者", "セレモニー", "축하"],
        "category": "panel",
        "subcategory": "",
        "scene_type": "indoor",
        "mood": "formal",
        "people_count": 1,
        "identified_people": ["張大明"],
        "ocr_text": ["映奧創意"],
    }

    args = build_exiftool_args(result)

    # Title / description flow into IPTC:Headline / Caption-Abstract.
    assert "-IPTC:Headline=阿伯演講" in args
    assert "-IPTC:Caption-Abstract=一位年長男性在舞台" in args
    # Keywords emit both IPTC:Keywords and XMP:Subject per entry.
    # B5: list-type tags use `+=` (merge) so user's manual keywords aren't wiped.
    assert "-IPTC:Keywords+=講者" in args
    assert "-IPTC:Keywords+=セレモニー" in args
    assert "-IPTC:Keywords+=축하" in args
    # identified_people are merged into keywords.
    assert "-IPTC:Keywords+=張大明" in args
    # OCR goes to XMP:Comment
    assert "-XMP:Comment=映奧創意" in args
