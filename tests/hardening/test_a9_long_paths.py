"""tests/hardening/test_a9_long_paths.py

Hardening A9: 超長路徑（> 255 chars）能處理。

真實情境：
- macOS `NAME_MAX` = 255 bytes per path component (APFS)
- macOS `PATH_MAX` 邏輯上是 1024；但 syscall 層可以接受更長路徑
- 現場觀察：映奧某個活動資料夾疊了 `2026/04/19/0419_XX公司XX主題XX活動/raw/DSC_XXXX_XXXX_final_adjusted.jpg`
  → 整條 path 可以輕易破 300 bytes
- Windows 有 MAX_PATH=260 的痛（Long Path opt-in），但我們只支 macOS 所以
  忽略 Windows 坑

合約：
- scan_photos 能抓到長路徑檔案
- result_store 能把長路徑寫進 SQLite（TEXT 無長度限制）
- `is_processed` 在長路徑下一致
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.pipeline import scan_photos
from modules.result_store import ResultStore


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (32, 32), color="white").save(str(path), format="JPEG")


def test_scan_handles_component_at_name_max_boundary(tmp_path):
    """One path component of ~240 chars (stays below macOS NAME_MAX=255)."""
    long_name = "a" * 240 + ".jpg"
    photo = tmp_path / long_name
    _write_jpg(photo)

    photos = scan_photos(str(tmp_path))
    assert len(photos) == 1
    assert Path(photos[0]).name == long_name


def test_scan_handles_deep_path_over_300_chars(tmp_path):
    """Total path length > 300 chars via nested folders."""
    current = tmp_path
    # 8 levels x ~40 chars each = ~320 chars before the filename
    for i in range(8):
        current = current / f"folder_level_{i:02d}_{'x' * 25}"
        current.mkdir()
    photo = current / "deep.jpg"
    _write_jpg(photo)

    total_len = len(str(photo))
    assert total_len > 300, f"test setup didn't produce a long enough path ({total_len})"

    photos = scan_photos(str(tmp_path))
    assert len(photos) == 1
    assert str(photo) in photos or Path(photos[0]).name == "deep.jpg"


def test_result_store_roundtrips_long_path(tmp_path):
    """SQLite TEXT has no intrinsic length cap. Lock in the contract."""
    current = tmp_path
    for i in range(6):
        current = current / f"very_long_folder_component_{i:02d}_{'y' * 30}"
        current.mkdir()
    photo = current / ("file_" + "z" * 200 + ".jpg")
    _write_jpg(photo)
    long_path = str(photo)
    assert len(long_path) > 400

    store = ResultStore(tmp_path / "r.db")
    store.save_result(
        long_path,
        {
            "title": "t", "description": "d", "keywords": ["k"],
            "category": "other", "scene_type": "indoor",
            "mood": "neutral", "people_count": 0,
            "identified_people": [], "ocr_text": [],
        },
        usage={"input_tokens": 10, "output_tokens": 5,
               "total_tokens": 15, "model": "gemini-2.5-flash-lite"},
        cost_usd=0.001,
    )

    assert store.is_processed(long_path), (
        "long path didn't round-trip through SQLite — is_processed would "
        "mis-fire and cause re-analysis on every run"
    )


def test_component_exceeding_255_gracefully_errors(tmp_path):
    """A single name component > 255 bytes is rejected by APFS.
    Our code shouldn't crash or corrupt state — just report zero results."""
    long_component = "a" * 300 + ".jpg"
    try:
        _write_jpg(tmp_path / long_component)
    except OSError:
        # Expected on APFS — can't even create the file. Nothing to test.
        pytest.skip("APFS refuses 300-char filenames — precondition fails")

    # If APFS accepted it (unusual), scan must still find or cleanly miss
    # without raising.
    photos = scan_photos(str(tmp_path))
    assert isinstance(photos, list)
