"""tests/hardening/test_b4_photo_without_exif.py

Hardening B4: 照片沒有 EXIF（PS export 剝 metadata / 截圖 / 早期 Pixel 某些
匯出）→ 分析照跑、metadata 寫得進去、讀得回來。

真實情境：攝影師在 PS 裡做完色調後勾「Export for Web」，預設會剝所有
metadata。同事把這種照片拖給 Happy Vision 處理時，我們既不能靠「先讀一下
現有 EXIF」的假設，exiftool 寫入時也不能因為「沒有 IPTC segment 可追加」
就失敗。

為了不依賴 exiftool 真的存在（CI 可能沒裝），metadata write 用 FakeBatch；
真實 exiftool 測試留給 `tests/test_metadata_writer.py` 的 e2e。
"""

from __future__ import annotations

import sqlite3
from io import BytesIO
from pathlib import Path

from PIL import Image

from modules import pipeline as pl
from modules.gemini_vision import resize_for_api


_MOCK_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


def _write_jpg_no_exif(path: Path, size=(256, 256), color=(100, 150, 200)) -> None:
    """JPEG with zero EXIF/IPTC/XMP. PIL's default Image.save doesn't add
    any metadata unless you pass exif= kwarg — so this is naturally clean."""
    img = Image.new("RGB", size, color)
    img.save(str(path), format="JPEG", quality=90)


def _has_app1_exif_segment(data: bytes) -> bool:
    """Byte-level check: JPEG EXIF lives in APP1 marker 0xFFE1 with
    'Exif\\x00\\x00' identifier. Absence confirms we truly have no EXIF."""
    # APP1 marker + Exif identifier
    return b"\xff\xe1" in data and b"Exif\x00\x00" in data


def test_fixture_jpeg_really_has_no_exif(tmp_path):
    """Sanity-check the test fixture before asserting behavior against it —
    otherwise a PIL default change could silently add EXIF and we'd
    'pass' the real test for the wrong reason."""
    photo = tmp_path / "clean.jpg"
    _write_jpg_no_exif(photo)

    raw = photo.read_bytes()
    # JPEG magic is present.
    assert raw.startswith(b"\xff\xd8")
    # But no EXIF APP1 segment.
    assert not _has_app1_exif_segment(raw)


def test_resize_for_api_handles_no_exif_input(tmp_path):
    """resize_for_api doesn't read EXIF, but PIL sometimes raises on weird
    minimal JPEGs. Lock in that a metadata-stripped JPEG goes through
    cleanly."""
    photo_bytes = _jpeg_no_exif_bytes((4000, 3000))
    out = resize_for_api(photo_bytes, max_size=1024)

    # Must be JPEG and within the resize cap.
    assert out[:2] == b"\xff\xd8"
    img = Image.open(BytesIO(out))
    assert max(img.size) <= 1024


def _jpeg_no_exif_bytes(size=(256, 256)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_pipeline_analyzes_no_exif_photo_end_to_end(tmp_path, monkeypatch):
    """Full run: 2 photos (both without EXIF). Analysis mocked; metadata
    writes captured by a FakeBatch. Both must complete and save."""
    p1 = tmp_path / "shot1.jpg"
    p2 = tmp_path / "shot2.jpg"
    _write_jpg_no_exif(p1, color=(255, 0, 0))
    _write_jpg_no_exif(p2, color=(0, 255, 0))

    # Pre-flight: neither file has EXIF.
    for p in (p1, p2):
        assert not _has_app1_exif_segment(p.read_bytes())

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **_kw: (
            {
                "title": f"t-{Path(path).name}",
                "description": "d",
                "keywords": ["shot"],
                "category": "other",
                "subcategory": "",
                "scene_type": "indoor",
                "mood": "neutral",
                "people_count": 0,
                "identified_people": [],
                "ocr_text": [],
            },
            _MOCK_USAGE,
        ),
    )

    writes: list[tuple[str, list[str]]] = []

    class _Batch:
        def write(self, path, args):
            writes.append((path, args))
            return True

        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _Batch)

    db_path = tmp_path / "r.db"
    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=db_path,
    )

    assert len(results) == 2
    assert len(writes) == 2

    # Every write must include the HappyVision marker (used for resume
    # detection) plus the actual content tags.
    for _path, args in writes:
        assert "-XMP:UserComment=HappyVisionProcessed" in args
        # At least one real content tag came through.
        assert any(a.startswith("-IPTC:Headline=t-") for a in args)

    # SQLite rows intact.
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT file_path, status FROM results"
        ).fetchall()
    finally:
        conn.close()
    assert {status for _fp, status in rows} == {"completed"}


def test_metadata_write_respects_exif_absence_does_not_fail(tmp_path, monkeypatch):
    """Pipeline must not conditionally skip metadata write just because
    the input had no EXIF — that was a past bug shape elsewhere. The
    write path is independent of input metadata."""
    photo = tmp_path / "raw.jpg"
    _write_jpg_no_exif(photo)

    monkeypatch.setattr(
        pl, "analyze_photo",
        lambda path, **_kw: (
            {
                "title": "t",
                "description": "",
                "keywords": [],
                "category": "other",
                "subcategory": "",
                "scene_type": "indoor",
                "mood": "neutral",
                "people_count": 0,
                "identified_people": [],
                "ocr_text": [],
            },
            _MOCK_USAGE,
        ),
    )

    wrote_for: list[str] = []

    class _Batch:
        def write(self, path, _args):
            wrote_for.append(path)
            return True

        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _Batch)

    pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=True,
        db_path=tmp_path / "r.db",
    )

    assert wrote_for == [str(photo)]
