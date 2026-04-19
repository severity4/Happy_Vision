"""tests/hardening/test_a4_extension_case_mixing.py

Hardening A4: `.JPG` / `.jpg` / `.JPEG` / `.jpeg` / `.Jpg` 大小寫混合都要被
scan_photos + folder_watcher._scan_recursive 識別為 JPG。

攝影師不同相機出來的副檔名大小寫不固定 — 老 Nikon 吐 `.JPG`，Lightroom
export 吐 `.jpg`。scan 漏掉任何一種都會讓同事誤以為「檔案被系統忽略了」。
同時也要確保非 JPG（`.png` / `.heic` / `.tiff`）不論大小寫都被排除。
"""

from __future__ import annotations

from pathlib import Path

from modules.folder_watcher import _scan_recursive
from modules.pipeline import scan_photos


# All valid JPEG extension variants we must accept.
_VALID_VARIANTS = [
    "shot1.jpg",
    "shot2.JPG",
    "shot3.Jpg",
    "shot4.jPg",
    "shot5.jpeg",
    "shot6.JPEG",
    "shot7.Jpeg",
    "shot8.jPeG",
]

# Non-JPEG formats we must ignore regardless of case.
_INVALID_VARIANTS = [
    "notes.png",
    "notes.PNG",
    "raw.heic",
    "raw.HEIC",
    "archive.tiff",
    "archive.TIFF",
    "archive.tif",
    "doc.pdf",
    "readme.txt",
    "noext",
]


def _stub_jpeg(path: Path) -> None:
    # Minimal valid JPEG (SOI + EOI). Good enough for a format-agnostic
    # extension scan; gemini_vision is mocked out of the pipeline.
    path.write_bytes(b"\xff\xd8\xff\xd9")


def test_scan_photos_accepts_all_jpeg_case_variants(tmp_path):
    for name in _VALID_VARIANTS:
        _stub_jpeg(tmp_path / name)

    photos = scan_photos(str(tmp_path))
    found = {Path(p).name for p in photos}

    assert found == set(_VALID_VARIANTS), (
        f"scan_photos missed case variants: "
        f"expected {set(_VALID_VARIANTS)}, got {found}"
    )


def test_scan_photos_rejects_non_jpeg_extensions(tmp_path):
    # Mix both so we also prove the filter doesn't false-accept based on
    # position in directory listing.
    for name in _VALID_VARIANTS + _INVALID_VARIANTS:
        (tmp_path / name).write_bytes(b"\xff\xd8\xff\xd9" if name.lower().endswith((".jpg", ".jpeg")) else b"irrelevant")

    photos = scan_photos(str(tmp_path))
    found = {Path(p).name for p in photos}

    assert found == set(_VALID_VARIANTS)
    # None of the invalid ones should leak through, even .heic (which
    # photographers might argue is "image"). Gemini only accepts JPEG from
    # our resize pipeline; HEIC slipping in would crash resize_for_api.
    for bad in _INVALID_VARIANTS:
        assert bad not in found


def test_folder_watcher_scan_recursive_accepts_all_jpeg_case_variants(tmp_path):
    """folder_watcher has its OWN scanner (os.scandir-based, for speed on
    150k-photo NAS). Must stay consistent with pipeline.scan_photos or the
    two code paths disagree on what counts as a photo."""
    subdir = tmp_path / "nested"
    subdir.mkdir()
    for i, name in enumerate(_VALID_VARIANTS):
        # Spread across root + nested to exercise recursion too.
        target = (tmp_path if i % 2 == 0 else subdir) / name
        _stub_jpeg(target)
    # Dot-prefixed files (e.g., `.DS_Store`, `.icloud` placeholders) must
    # be ignored by folder_watcher — it explicitly skips them in
    # _scan_recursive.
    (tmp_path / ".hidden.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    found = {Path(p).name for p in _scan_recursive(str(tmp_path))}

    assert found == set(_VALID_VARIANTS)
    assert ".hidden.jpg" not in found


def test_scanners_agree_on_same_folder(tmp_path):
    """Regression guard: pipeline.scan_photos and folder_watcher._scan_recursive
    must produce the SAME set of photos for the same folder. Past drift (one
    accepting `.JPEG`, the other not) would cause watch-mode to skip photos
    that batch-mode processed."""
    for name in _VALID_VARIANTS + _INVALID_VARIANTS:
        _stub_jpeg(tmp_path / name) if name.lower().endswith((".jpg", ".jpeg")) else (tmp_path / name).write_bytes(b"x")

    from_pipeline = {Path(p).name for p in scan_photos(str(tmp_path))}
    from_watcher = {Path(p).name for p in _scan_recursive(str(tmp_path))}

    assert from_pipeline == from_watcher
