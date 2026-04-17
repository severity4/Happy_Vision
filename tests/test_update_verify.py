"""tests/test_update_verify.py"""
import zipfile
from pathlib import Path

import pytest

from modules import update_verify


def test_safe_extract_ok(tmp_path):
    src = tmp_path / "ok.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("HappyVision.app/Contents/MacOS/HappyVision", b"binary")
        z.writestr("HappyVision.app/Contents/Info.plist", b"<plist/>")

    dest = tmp_path / "out"
    dest.mkdir()
    update_verify.safe_extract(src, dest)

    assert (dest / "HappyVision.app" / "Contents" / "MacOS" / "HappyVision").exists()
    assert (dest / "HappyVision.app" / "Contents" / "Info.plist").exists()


def test_safe_extract_rejects_traversal(tmp_path):
    """Entry path resolving outside dest must raise."""
    src = tmp_path / "evil.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("../../../etc/evil.conf", b"pwned")

    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValueError, match="outside"):
        update_verify.safe_extract(src, dest)


def test_safe_extract_rejects_absolute_path(tmp_path):
    src = tmp_path / "evil.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("/etc/evil.conf", b"pwned")

    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValueError):
        update_verify.safe_extract(src, dest)


def test_verify_size_accepts_small():
    update_verify.verify_size(1000)  # no raise


def test_verify_size_rejects_huge():
    with pytest.raises(ValueError, match="size limit"):
        update_verify.verify_size(update_verify.MAX_ZIP_SIZE + 1)
