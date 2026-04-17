"""tests/test_update_verify.py"""
import stat
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
    with pytest.raises(ValueError, match="outside"):
        update_verify.safe_extract(src, dest)


def test_verify_size_accepts_small():
    update_verify.verify_size(1000)  # no raise


def test_verify_size_rejects_huge():
    with pytest.raises(ValueError, match="size limit"):
        update_verify.verify_size(update_verify.MAX_ZIP_SIZE + 1)


def test_safe_extract_rejects_backslash_traversal(tmp_path):
    """Entry with Windows-style backslash separators must be rejected."""
    src = tmp_path / "backslash.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("subdir\\..\\..\\evil.txt", b"pwned")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValueError, match="outside"):
        update_verify.safe_extract(src, dest)


def test_safe_extract_rejects_symlink_entry(tmp_path):
    """A zip entry encoded as a symlink must be rejected."""
    src = tmp_path / "symlink.zip"
    with zipfile.ZipFile(src, "w") as z:
        # Symlink entry pointing outside dest
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, "../../etc/passwd")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValueError, match="[Ss]ymlink"):
        update_verify.safe_extract(src, dest)


def test_safe_extract_rejects_backslash_absolute(tmp_path):
    src = tmp_path / "winabs.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("\\Windows\\evil.dll", b"pwned")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValueError, match="outside"):
        update_verify.safe_extract(src, dest)


def test_verify_sha256_match(tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello")
    import hashlib
    expected = hashlib.sha256(b"hello").hexdigest()
    update_verify.verify_sha256(f, expected)  # no raise


def test_verify_sha256_mismatch(tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello")
    with pytest.raises(ValueError, match="checksum"):
        update_verify.verify_sha256(f, "0" * 64)


def test_parse_sha256sums_finds_entry():
    text = (
        "abc123  HappyVision-0.3.0-macos.zip\n"
        "def456  OtherFile.zip\n"
    )
    assert update_verify.parse_sha256sums(text, "HappyVision-0.3.0-macos.zip") == "abc123"


def test_parse_sha256sums_with_binary_star_marker():
    """shasum's binary mode emits '*' prefix on the filename."""
    text = "abc123 *HappyVision-0.3.0-macos.zip\n"
    assert update_verify.parse_sha256sums(text, "HappyVision-0.3.0-macos.zip") == "abc123"


def test_parse_sha256sums_missing_entry():
    text = "abc123  OtherFile.zip\n"
    with pytest.raises(ValueError, match="not found"):
        update_verify.parse_sha256sums(text, "HappyVision-0.3.0-macos.zip")


def test_parse_sha256sums_ignores_comments_and_blanks():
    text = (
        "# Comment line\n"
        "\n"
        "abc123  HappyVision.zip\n"
    )
    assert update_verify.parse_sha256sums(text, "HappyVision.zip") == "abc123"
