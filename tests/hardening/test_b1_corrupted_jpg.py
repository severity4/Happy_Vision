"""tests/hardening/test_b1_corrupted_jpg.py

Hardening B1: 損壞的 JPG（0-byte / 截斷 / 錯誤檔頭）→ skip + 記錄 failed，
絕不 crash 整個 pipeline。

實際情境：同事把一包照片拖進來，其中幾張是中途 AirDrop 失敗截斷的 / 誤把
`.jpg.download` 改名成 `.jpg` / NAS 同步到一半的半檔。這些進 PIL 會丟
UnidentifiedImageError，我們必須在 analyze_photo 裡吃掉，讓其他好照片
照樣跑完。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from modules import pipeline as pl
from modules.gemini_vision import analyze_photo, resize_for_api


_MOCK_USAGE = {
    "input_tokens": 100,
    "output_tokens": 20,
    "total_tokens": 120,
    "model": "gemini-2.5-flash-lite",
}


def _mock_result() -> dict:
    return {
        "title": "Good photo",
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


def _write_zero_byte(path: Path) -> None:
    path.write_bytes(b"")


def _write_bogus_header(path: Path) -> None:
    # Not a JPEG magic marker — random bytes.
    path.write_bytes(b"NOT A REAL JPEG\x00\x01\x02\x03" * 16)


def _write_truncated(path: Path) -> None:
    # SOI + first few bytes then cut — PIL can open but fails mid-decode.
    # Use a REAL JPEG header then truncate to 32 bytes.
    img = Image.new("RGB", (100, 100), color="red")
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="JPEG")
    path.write_bytes(buf.getvalue()[:32])


def _write_good_jpeg(path: Path) -> None:
    img = Image.new("RGB", (200, 150), color=(10, 20, 30))
    img.save(str(path), format="JPEG")


def test_analyze_photo_returns_none_on_zero_byte_jpg(tmp_path):
    bad = tmp_path / "empty.jpg"
    _write_zero_byte(bad)

    # Gemini client must NOT be called for a corrupt image — we bail before
    # that. Patch generate_content to assert it never fires.
    with patch("modules.gemini_vision._get_client") as mock_client:
        result, usage = analyze_photo(str(bad), api_key="k", model="lite")

    assert result is None
    assert usage is None
    # Never constructed a client for a corrupt image.
    mock_client.assert_not_called()


def test_analyze_photo_returns_none_on_bogus_header(tmp_path):
    bad = tmp_path / "bogus.jpg"
    _write_bogus_header(bad)

    with patch("modules.gemini_vision._get_client") as mock_client:
        result, usage = analyze_photo(str(bad), api_key="k", model="lite")

    assert result is None
    assert usage is None
    mock_client.assert_not_called()


def test_analyze_photo_returns_none_on_truncated_jpg(tmp_path):
    bad = tmp_path / "trunc.jpg"
    _write_truncated(bad)

    with patch("modules.gemini_vision._get_client") as mock_client:
        result, usage = analyze_photo(str(bad), api_key="k", model="lite")

    # Truncated may or may not open; we just require "don't crash, return
    # None OR call Gemini with whatever PIL salvaged — but NEVER raise".
    # If it chose to call the client, that's a separate cost decision but
    # not a crash bug, so we only assert the no-exception path.
    assert (result is None and usage is None) or mock_client.called


def test_pipeline_skips_corrupt_photos_and_processes_good_ones(tmp_path, monkeypatch):
    """Mixed batch: 1 good + 3 corrupt. Must complete, good one analyzed,
    3 marked failed, no crash."""
    good = tmp_path / "good.jpg"
    _write_good_jpeg(good)
    _write_zero_byte(tmp_path / "zero.jpg")
    _write_bogus_header(tmp_path / "bogus.jpg")
    _write_truncated(tmp_path / "trunc.jpg")

    # Only the good JPG should actually call Gemini. Mock it to return a
    # success. Corrupt ones should NEVER reach this mock — if they do, the
    # bug is that we didn't detect corruption locally.
    call_paths: list[str] = []
    real_analyze = analyze_photo

    def tracking_analyze(path, **kw):
        call_paths.append(path)
        # For corrupt photos we want the real short-circuit (returns None);
        # for the good one we bypass the network with a mocked result.
        if Path(path).name == "good.jpg":
            return _mock_result(), _MOCK_USAGE
        return real_analyze(path, **kw)

    monkeypatch.setattr(pl, "analyze_photo", tracking_analyze)
    # Stub exiftool so we test pure analysis + DB side, not metadata write.
    class _NoopBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    # Prevent the real analyze_photo from constructing a real client for
    # corrupt photos (they should short-circuit before that; if they don't,
    # the client constructor would fail on fake key anyway, but we still
    # want to guard against network calls).
    monkeypatch.setattr(
        "modules.gemini_vision._get_client",
        lambda _k: (_ for _ in ()).throw(RuntimeError("must not be called")),
    )

    db_path = tmp_path / "r.db"
    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=2,  # exercise the thread-pool path
        write_metadata=False,
        db_path=db_path,
    )

    # 1 completed, 3 failed. Pipeline must NOT have raised.
    assert len(results) == 1
    assert results[0]["title"] == "Good photo"

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT file_path, status FROM results"
        ).fetchall()
    finally:
        conn.close()

    statuses = {Path(fp).name: st for fp, st in rows}
    assert statuses["good.jpg"] == "completed"
    assert statuses["zero.jpg"] == "failed"
    assert statuses["bogus.jpg"] == "failed"
    # truncated behaviour is allowed to be either, depending on PIL version
    assert statuses["trunc.jpg"] in ("failed", "completed")


def test_resize_for_api_raises_useful_error_on_corrupt_bytes():
    """resize_for_api is the lowest layer. It currently raises on corrupt
    input — that's FINE as long as the caller (analyze_photo) catches and
    returns None. We document the contract here."""
    import pytest
    from PIL import UnidentifiedImageError

    with pytest.raises(UnidentifiedImageError):
        resize_for_api(b"")
    with pytest.raises(UnidentifiedImageError):
        resize_for_api(b"NOT A JPEG AT ALL")
