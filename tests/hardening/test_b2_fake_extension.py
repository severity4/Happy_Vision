"""tests/hardening/test_b2_fake_extension.py

Hardening B2: 檔名是 `.jpg` 但實際是 PNG / HEIC / TIFF / BMP → 清楚處理，
不能把錯的 bytes 丟給 Gemini 卻標 `image/jpeg`。

常見情境：同事截圖存成 `screenshot.png` 後手動改名為 `.jpg`；或 macOS 某些
工具把 HEIC 匯出時誤判副檔名。目前 `resize_for_api` 在 `max(w,h) <= max_size`
時直接 return 原 bytes — 小張 PNG 會被標錯 mime 丟給 Gemini，可能悄悄失敗，
或 RGBA PNG 在大張時走到 `img.save(..., format="JPEG")` 丟 OSError。

B1 的 catch 已經能擋住 RGBA 大 PNG 的 OSError，但小張 PNG 的「mime 說謊」
洞還在。本回合鎖死：不論 size / mode，resize_for_api 一律 re-encode 為 JPEG。
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from modules import pipeline as pl
from modules.gemini_vision import analyze_photo, resize_for_api


_MOCK_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


def _png_bytes(size: tuple[int, int] = (200, 200), mode: str = "RGB") -> bytes:
    img = Image.new(mode, size, color=(40, 80, 160))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _tiff_bytes(size: tuple[int, int] = (200, 200)) -> bytes:
    img = Image.new("RGB", size, color=(60, 120, 200))
    buf = BytesIO()
    img.save(buf, format="TIFF")
    return buf.getvalue()


def _is_jpeg(data: bytes) -> bool:
    # SOI marker 0xFFD8, and ideally EOI 0xFFD9 at end.
    return data[:2] == b"\xff\xd8"


def test_resize_for_api_returns_jpeg_for_small_png():
    """Regression guard: a small (< max_size) PNG must still be re-encoded
    to JPEG bytes before going to Gemini. Previously we short-circuited
    with `return photo_bytes` when the image was small enough, which sent
    PNG bytes with `mime_type='image/jpeg'`."""
    png = _png_bytes(size=(100, 100))

    out = resize_for_api(png, max_size=3072)

    assert _is_jpeg(out), (
        "resize_for_api returned non-JPEG bytes for small PNG input — "
        "downstream Gemini call would get a mime/payload mismatch."
    )


def test_resize_for_api_returns_jpeg_for_small_tiff():
    tiff = _tiff_bytes(size=(150, 120))

    out = resize_for_api(tiff, max_size=3072)

    assert _is_jpeg(out)


def test_resize_for_api_returns_jpeg_for_rgba_png():
    """RGBA PNG must be flattened + re-encoded as JPEG without blowing up
    with OSError('cannot write mode RGBA as JPEG'). Safe fallback: paste
    onto a solid background, or convert to RGB."""
    png_rgba = _png_bytes(size=(100, 100), mode="RGBA")

    out = resize_for_api(png_rgba, max_size=3072)

    assert _is_jpeg(out)


def test_resize_for_api_keeps_real_jpeg_bytes_intact_for_small_input():
    """A legitimately small JPG should not be wastefully re-encoded if
    doing so would cause quality loss for no benefit. Acceptable behaviors:
    (a) return verbatim, (b) re-encode at high quality. Both produce JPEG
    output — we only care that the bytes start with the JPEG SOI marker."""
    img = Image.new("RGB", (100, 100), color="red")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    jpg = buf.getvalue()

    out = resize_for_api(jpg, max_size=3072)

    assert _is_jpeg(out)


def test_pipeline_handles_png_renamed_as_jpg(tmp_path, monkeypatch):
    """End-to-end: a fake-extension file lands in the folder. Pipeline
    must either analyze it cleanly (if resize_for_api transcodes) or mark
    it failed — never crash."""
    photo = tmp_path / "screenshot.jpg"
    photo.write_bytes(_png_bytes(size=(200, 200)))

    # Ensure Gemini always sees JPEG bytes — if our resize does its job,
    # the mock receives JPEG; if the short-circuit bug returns, we'd
    # see PNG bytes here.
    received: list[bytes] = []

    def spy_analyze(path, **_kw):
        # Bypass the real network but still exercise resize_for_api.
        data = Path(path).read_bytes()
        out = resize_for_api(data, max_size=3072)
        received.append(out)
        return (
            {
                "title": "shot",
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
        )

    monkeypatch.setattr(pl, "analyze_photo", spy_analyze)

    class _NoopBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    assert len(results) == 1
    assert received, "analyze was never called"
    assert _is_jpeg(received[0]), "PNG bytes leaked through as 'image/jpeg' to Gemini"
