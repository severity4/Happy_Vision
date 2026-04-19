"""tests/hardening/test_a6_symlinks.py

Hardening A6: symlink 指向的 JPG 能被處理；broken symlink（指向不存在檔案）
必須優雅失敗，不能 crash 整個 scan。

真實情境：
- iCloud Drive 在 macOS 上的 `.icloud` 佔位符不是 symlink 但形式相似，
  這裡只處理 POSIX symlink（Dropbox / Resilio Sync 有時會）
- 使用者用 `ln -s ~/Photos ~/Desktop/Wedding` 做捷徑，scan 時應該要能跟
- `.dng` → `.jpg` 的 sidecar 用 symlink 實作（Lightroom 某些 workflow）

合約：
- scan_photos 會跟進 symlink（pathlib.rglob 預設跟進）
- analyze_photo 對 broken symlink 的路徑不要 crash — 應該回 (None, None)
- pipeline 最終標 failed 給 broken symlink
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules import pipeline as pl
from modules.pipeline import scan_photos


_MOCK_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


def _mock_result() -> dict:
    return {
        "title": "t", "description": "", "keywords": [],
        "category": "other", "subcategory": "",
        "scene_type": "indoor", "mood": "neutral",
        "people_count": 0, "identified_people": [], "ocr_text": [],
    }


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (32, 32), color="white").save(str(path), format="JPEG")


def _can_symlink(tmp_path: Path) -> bool:
    try:
        (tmp_path / "src").touch()
        (tmp_path / "lnk").symlink_to(tmp_path / "src")
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        for name in ("src", "lnk"):
            p = tmp_path / name
            if p.exists() or p.is_symlink():
                p.unlink()


class _NoopBatch:
    def write(self, *_a, **_kw): return True
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_a): pass


def test_scan_follows_symlink_to_jpg(tmp_path):
    if not _can_symlink(tmp_path):
        pytest.skip("filesystem / permissions prevent symlink creation")

    real = tmp_path / "real.jpg"
    _write_jpg(real)

    link_folder = tmp_path / "linked_folder"
    link_folder.mkdir()
    link = link_folder / "alias.jpg"
    link.symlink_to(real)

    photos = scan_photos(str(link_folder))
    assert len(photos) == 1
    # path returned may be the symlink path itself; both acceptable as long
    # as the file resolves to JPG content.
    resolved = Path(photos[0]).resolve()
    assert resolved == real.resolve()


def test_scan_follows_symlink_to_folder(tmp_path):
    if not _can_symlink(tmp_path):
        pytest.skip("symlink-creation not available")

    real_folder = tmp_path / "real"
    real_folder.mkdir()
    _write_jpg(real_folder / "a.jpg")
    _write_jpg(real_folder / "b.jpg")

    # Shortcut folder via symlink.
    shortcut = tmp_path / "shortcut"
    shortcut.symlink_to(real_folder)

    photos = scan_photos(str(shortcut))
    # rglob with follow_symlinks=default follows dir symlinks too.
    assert len(photos) == 2


def test_scan_skips_broken_symlinks_without_crash(tmp_path):
    if not _can_symlink(tmp_path):
        pytest.skip("symlink-creation not available")

    # Create a real photo, plus a broken symlink to a deleted file.
    real = tmp_path / "real.jpg"
    _write_jpg(real)
    gone = tmp_path / "gone.jpg"
    _write_jpg(gone)
    broken = tmp_path / "broken.jpg"
    broken.symlink_to(gone)
    gone.unlink()  # symlink now dangling

    photos = scan_photos(str(tmp_path))

    # scan must not crash; must still return the healthy photo.
    assert str(real) in photos or str(real.resolve()) in [Path(p).resolve().__str__() for p in photos]
    # The broken symlink behavior is implementation-defined:
    # - path.is_file() returns False on broken symlinks, so it SHOULD be
    #   excluded from scan_photos results.
    broken_in_results = any(
        Path(p).name == "broken.jpg" and Path(p).is_symlink() for p in photos
    )
    assert not broken_in_results or broken.exists(), (
        "broken symlink slipped into scan_photos results"
    )


def test_pipeline_handles_broken_symlink_gracefully(tmp_path, monkeypatch):
    """If scan somehow returns a broken symlink path (shouldn't, but just
    in case), the pipeline must not crash trying to read it."""
    if not _can_symlink(tmp_path):
        pytest.skip("symlink-creation not available")

    good = tmp_path / "good.jpg"
    _write_jpg(good)
    target = tmp_path / "target.jpg"
    _write_jpg(target)
    broken = tmp_path / "broken.jpg"
    broken.symlink_to(target)
    target.unlink()

    call_paths = []

    def tracking(path, **_kw):
        call_paths.append(path)
        return _mock_result(), _MOCK_USAGE

    monkeypatch.setattr(pl, "analyze_photo", tracking)
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    # At minimum, the good photo processed.
    assert any("good.jpg" in Path(p).name for p in call_paths)
    # At least 1 result (the good one).
    assert len(results) >= 1


def test_analyze_photo_on_broken_symlink_returns_none(tmp_path, monkeypatch):
    """analyze_photo reads the file via `Path.read_bytes()`. On a broken
    symlink that raises FileNotFoundError — our B1 fix catches it and
    returns (None, None)."""
    if not _can_symlink(tmp_path):
        pytest.skip("symlink-creation not available")

    target = tmp_path / "target.jpg"
    _write_jpg(target)
    broken = tmp_path / "broken.jpg"
    broken.symlink_to(target)
    target.unlink()

    from modules.gemini_vision import analyze_photo

    # No need to mock client — we fail before hitting Gemini.
    result, usage = analyze_photo(str(broken), api_key="k", model="lite", max_retries=1)

    assert result is None
    assert usage is None


def test_symlink_loop_does_not_crash_scan(tmp_path):
    """A → B → A (directory symlink loop) must not hang or crash
    scan_photos. rglob has cycle protection since Python 3.13 default."""
    if not _can_symlink(tmp_path):
        pytest.skip("symlink-creation not available")

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _write_jpg(a / "real.jpg")

    # a contains a symlink back to b; b symlinks to a → loop.
    try:
        (a / "loop_to_b").symlink_to(b)
        (b / "loop_to_a").symlink_to(a)
    except OSError:
        pytest.skip("can't create directory symlinks")

    # Bounded wall-time: must finish < 2s even with the loop.
    import time
    start = time.monotonic()
    photos = scan_photos(str(tmp_path))
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"scan took {elapsed:.1f}s — symlink loop not handled"
    # The real JPG is found at least once.
    assert any("real.jpg" in Path(p).name for p in photos)
