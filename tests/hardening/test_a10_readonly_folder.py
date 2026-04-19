"""tests/hardening/test_a10_readonly_folder.py

Hardening A10: 唯讀資料夾 / 檔案 → metadata 寫入失敗時不污染 result_store。

macOS APFS 補充：
- 光 `chmod 0o444` 在**檔案**上不會擋住 exiftool，因為 `-overwrite_original`
  走的是 rename(2) — 只要**目錄**可寫就能成功（exiftool 建臨時檔後 rename）。
- 真正擋得住寫入的是 **目錄** 0o555。這也對應到 SD 卡/光碟/唯讀掛載點
  真實出現的情境。

所以本關用「read-only directory」而不是「read-only file」作為 metadata
寫入失敗的模擬環境。
"""

from __future__ import annotations

import shutil
import stat
from pathlib import Path

import pytest

from modules import metadata_writer as mw
from modules.pipeline import scan_photos


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (32, 32), color="white").save(str(path), format="JPEG")


def _make_dir_readonly(d: Path) -> None:
    d.chmod(0o555)


def _restore_writable(d: Path) -> None:
    d.chmod(0o755)


def test_scan_photos_works_on_readonly_folder(tmp_path):
    """Read access only — scan should still enumerate JPGs."""
    folder = tmp_path / "locked"
    folder.mkdir()
    _write_jpg(folder / "a.jpg")
    _write_jpg(folder / "b.jpg")

    _make_dir_readonly(folder)
    try:
        photos = scan_photos(str(folder))
    finally:
        _restore_writable(folder)

    assert len(photos) == 2


def test_write_metadata_returns_false_in_readonly_directory(tmp_path):
    """exiftool -overwrite_original fails (can't write temp file) in a
    read-only directory. metadata_writer must return False (not raise)."""
    if not shutil.which("exiftool"):
        pytest.skip("exiftool not installed")

    folder = tmp_path / "locked"
    folder.mkdir()
    photo = folder / "p.jpg"
    _write_jpg(photo)

    _make_dir_readonly(folder)
    try:
        ok = mw.write_metadata(
            str(photo),
            {"title": "t", "description": "d", "keywords": ["k"]},
        )
    finally:
        _restore_writable(folder)

    assert ok is False, (
        "metadata_writer must return False when dir is read-only — "
        "pipeline depends on this to mark photo failed, not completed"
    )


def test_write_metadata_keeps_bytes_unchanged_in_readonly_dir(tmp_path):
    """Failed write must leave the file bytes exactly as they were."""
    if not shutil.which("exiftool"):
        pytest.skip("exiftool not installed")

    folder = tmp_path / "locked"
    folder.mkdir()
    photo = folder / "p.jpg"
    _write_jpg(photo)
    original = photo.read_bytes()

    _make_dir_readonly(folder)
    try:
        mw.write_metadata(
            str(photo),
            {"title": "t", "description": "d", "keywords": ["k"]},
        )
        after = photo.read_bytes()
    finally:
        _restore_writable(folder)

    assert after == original


def test_write_metadata_returns_false_on_nonexistent_file(tmp_path):
    """Defensive: if pipeline somehow called write on a missing path
    (e.g., user moved the file mid-run), we log and return False."""
    missing = tmp_path / "never_existed.jpg"

    ok = mw.write_metadata(str(missing), {"title": "t"})

    assert ok is False


def test_exiftool_batch_survives_readonly_dir_and_recovers(tmp_path):
    """ExiftoolBatch.write on a read-only dir should return False
    WITHOUT killing the long-lived exiftool session. Subsequent writes
    to a writable dir must still succeed — else one bad photo would
    break 150k-photo folder_watcher scans."""
    if not shutil.which("exiftool"):
        pytest.skip("exiftool not installed")

    locked = tmp_path / "locked"
    locked.mkdir()
    writable = tmp_path / "writable"
    writable.mkdir()

    bad = locked / "bad.jpg"
    good = writable / "good.jpg"
    _write_jpg(bad)
    _write_jpg(good)

    _make_dir_readonly(locked)
    batch = mw.ExiftoolBatch()
    try:
        ok_bad = batch.write(
            str(bad),
            ["-IPTC:Headline=t", "-overwrite_original"],
        )
        assert ok_bad is False

        ok_good = batch.write(
            str(good),
            ["-IPTC:Headline=g", "-overwrite_original"],
        )
        assert ok_good is True, (
            "ExiftoolBatch session was killed by one readonly-dir failure"
        )
    finally:
        batch.close()
        _restore_writable(locked)
