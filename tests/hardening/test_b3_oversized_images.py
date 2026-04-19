"""tests/hardening/test_b3_oversized_images.py

Hardening B3: 超大尺寸照片（例如 Fuji GFX 100 的 11648×8736 = 100M pixels
= PIL 的 DecompressionBombWarning 門檻）能被正確處理。

PIL 的 `Image.MAX_IMAGE_PIXELS` 預設是 ~89M pixels。超過這個會 warn / raise
DecompressionBombError（依 Pillow 版本）。映奧大部分活動照是 Sony / Canon
等 < 60MP 的設備，但偶爾遇到哈蘇或富士中片幅大檔。

重點：
- 正常大檔（例如 4000×6000 × 10MB JPEG）被 resize 成 max_size 後 ok，
  **不應該**記憶體爆炸（PIL 讀檔時會暫時持有 decoded pixels）
- 炸彈照片（超出 MAX_IMAGE_PIXELS）被 B1 的 catch 攔下，標記失敗不 crash

這裡不真的生出 100MP 測試檔（會 OOM CI）— 改用 monkey-patch
MAX_IMAGE_PIXELS 到一個低值，用正常尺寸觸發相同 DecompressionBombError。
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from modules import pipeline as pl
from modules.gemini_vision import analyze_photo, resize_for_api


_MOCK_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


def _jpeg_bytes(size: tuple[int, int], quality: int = 90) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, (128, 128, 128)).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def test_resize_for_api_handles_large_but_reasonable_image():
    """6000×4000 JPEG (Sony A7 IV territory) must resize cleanly to
    max_size without memory issues. Output MUST be strictly smaller."""
    large = _jpeg_bytes((6000, 4000))
    out = resize_for_api(large, max_size=1024)

    # Output bytes strictly smaller (resize actually happened).
    assert len(out) < len(large)
    # And still JPEG.
    assert out[:2] == b"\xff\xd8"
    # Max dimension honored.
    img = Image.open(BytesIO(out))
    assert max(img.size) <= 1024


def test_resize_for_api_preserves_aspect_ratio_for_portrait(tmp_path):
    """Portrait orientation must keep aspect — no squished result."""
    portrait = _jpeg_bytes((3000, 6000))
    out = resize_for_api(portrait, max_size=1500)

    img = Image.open(BytesIO(out))
    w, h = img.size
    assert max(w, h) <= 1500
    # Aspect ratio preserved within 1%.
    ratio = w / h if w > h else h / w
    expected = 3000 / 6000
    assert abs(ratio - (1 / expected if ratio > 1 else expected)) < 0.02


def test_analyze_photo_marks_decompression_bomb_as_failed(tmp_path, monkeypatch):
    """Simulate a decompression bomb by lowering MAX_IMAGE_PIXELS so a
    modest JPEG triggers the same error path as a real 100MP file. The
    B1 catch in analyze_photo must treat this as a graceful failure."""
    bomb_photo = tmp_path / "bomb.jpg"
    bomb_photo.write_bytes(_jpeg_bytes((2000, 2000)))  # 4M pixels

    # Force PIL to treat anything > 1M pixels as a bomb.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1_000_000)
    # Also turn warning into error for determinism.
    import warnings
    warnings.simplefilter("error", Image.DecompressionBombWarning)

    # Gemini client must not be called — we bail locally before network.
    with patch("modules.gemini_vision._get_client") as mock_client:
        result, usage = analyze_photo(str(bomb_photo), api_key="k", model="lite", max_retries=1)

    assert result is None
    assert usage is None
    mock_client.assert_not_called()


def test_pipeline_skips_bomb_photo_and_processes_others(tmp_path, monkeypatch):
    """Mixed batch: one legit photo + one bomb. Must end with 1 completed,
    1 failed, no crash."""
    legit = tmp_path / "legit.jpg"
    bomb = tmp_path / "bomb.jpg"
    legit.write_bytes(_jpeg_bytes((400, 300)))
    bomb.write_bytes(_jpeg_bytes((2000, 2000)))

    # Bomb threshold below bomb.jpg's pixel count but above legit's.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1_000_000)
    import warnings
    warnings.simplefilter("error", Image.DecompressionBombWarning)

    # Real resize on the legit photo; we stub only the API call.
    real_analyze = analyze_photo

    def spy(path, **kw):
        if Path(path).name == "legit.jpg":
            # Route through resize_for_api to verify the modest-size path
            # really works with the lowered bomb limit.
            resize_for_api(Path(path).read_bytes(), max_size=256)
            return (
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
            )
        return real_analyze(path, **kw)

    monkeypatch.setattr(pl, "analyze_photo", spy)

    class _NoopBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)
    # Don't contact a real Gemini client.
    monkeypatch.setattr(
        "modules.gemini_vision._get_client",
        lambda _k: (_ for _ in ()).throw(RuntimeError("bomb path must short-circuit")),
    )

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    # legit.jpg succeeds; bomb.jpg is marked failed.
    assert len(results) == 1
    assert results[0]["title"] == "t"
