"""tests/hardening/test_a7_nested_folders.py

Hardening A7: 巢狀資料夾（多層子目錄）遞迴掃描正確。

真實情境：映奧的活動照片常用 `2026/04/0419_XX婚禮/Raw/` 這種深層結構。
`scan_photos` 需要遞迴抓，且不能因為單一層裡有非 JPG 檔（.txt / .DS_Store）
而漏抓或誤抓。

合約：
- 4+ 層巢狀都能找到 JPG
- 混合子資料夾（有 JPG、沒 JPG、有非 JPG）不干擾結果
- 隱藏資料夾（`.Trash`、`.DS_Store` 會建的 `.fseventsd`）不會被誤讀
  其中的內容（至少不崩潰）
"""

from __future__ import annotations

from pathlib import Path

from modules.pipeline import scan_photos


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (32, 32), color="white").save(str(path), format="JPEG")


def test_deeply_nested_folders_all_jpgs_found(tmp_path):
    """5-level nesting with JPG at each level."""
    expected = []
    current = tmp_path
    for level in range(5):
        current = current / f"level{level}"
        current.mkdir()
        jpg = current / f"photo_L{level}.jpg"
        _write_jpg(jpg)
        expected.append(str(jpg))

    photos = scan_photos(str(tmp_path))
    found = {Path(p).name for p in photos}
    assert len(photos) == 5
    for i in range(5):
        assert f"photo_L{i}.jpg" in found, f"missed photo at level {i}"


def test_mixed_tree_with_irrelevant_files(tmp_path):
    """Tree with JPGs, non-JPGs, sidecars, and empty folders."""
    a = tmp_path / "day1"
    b = tmp_path / "day2" / "raw"
    c = tmp_path / "day3" / "empty"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    c.mkdir(parents=True)

    _write_jpg(a / "a1.jpg")
    _write_jpg(a / "a2.JPG")
    (a / "notes.txt").write_text("shot notes")
    (a / "a1.xmp").write_text("<xmp/>")  # sidecar
    _write_jpg(b / "b1.jpeg")
    _write_jpg(b / "b2.JPEG")
    # c has no photos

    photos = scan_photos(str(tmp_path))
    assert len(photos) == 4
    names = {Path(p).name for p in photos}
    assert names == {"a1.jpg", "a2.JPG", "b1.jpeg", "b2.JPEG"}


def test_hidden_dir_contents_not_crashy(tmp_path):
    """macOS sprinkles `.DS_Store`, `.Trash` at any level. We must not
    crash if a JPG happens to be in a hidden dir (user's choice) — and
    mustn't accidentally treat `.DS_Store` as an image."""
    real = tmp_path / "visible"
    real.mkdir()
    _write_jpg(real / "ok.jpg")

    (tmp_path / ".DS_Store").write_bytes(b"\x00\x00")
    hidden_folder = tmp_path / ".cache"
    hidden_folder.mkdir()
    _write_jpg(hidden_folder / "weird.jpg")

    photos = scan_photos(str(tmp_path))
    # At minimum the visible one is there; .cache/weird.jpg may or may
    # not be included (rglob does follow into hidden dirs by default),
    # but .DS_Store must never be classified as a photo.
    names = {Path(p).name for p in photos}
    assert "ok.jpg" in names
    assert ".DS_Store" not in names


def test_empty_nested_tree(tmp_path):
    """Tree of empty dirs → scan returns []."""
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    (tmp_path / "a" / "b" / "d").mkdir()
    (tmp_path / "x").mkdir()

    assert scan_photos(str(tmp_path)) == []


def test_pipeline_processes_all_nested_photos(tmp_path, monkeypatch):
    """End-to-end: pipeline hands every nested photo to analyze_photo."""
    from modules import pipeline as pl

    for sub in ("a", "a/b", "a/b/c"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    _write_jpg(tmp_path / "top.jpg")
    _write_jpg(tmp_path / "a" / "l1.jpg")
    _write_jpg(tmp_path / "a" / "b" / "l2.jpg")
    _write_jpg(tmp_path / "a" / "b" / "c" / "l3.jpg")

    seen = []

    def fake_analyze(path, **_kw):
        seen.append(Path(path).name)
        return ({
            "title": "t", "description": "d", "keywords": [],
            "category": "other", "subcategory": "",
            "scene_type": "indoor", "mood": "neutral",
            "people_count": 0, "identified_people": [], "ocr_text": [],
        }, {"input_tokens": 1, "output_tokens": 1,
            "total_tokens": 2, "model": "gemini-2.5-flash-lite"})

    monkeypatch.setattr(pl, "analyze_photo", fake_analyze)

    class _NoopBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    pl.run_pipeline(
        folder=str(tmp_path), api_key="k", concurrency=1,
        write_metadata=False, db_path=tmp_path / "r.db",
    )
    assert set(seen) == {"top.jpg", "l1.jpg", "l2.jpg", "l3.jpg"}
