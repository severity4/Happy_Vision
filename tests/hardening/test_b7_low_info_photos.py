"""tests/hardening/test_b7_low_info_photos.py

Hardening B7: 黑白 / 去色 / 低解析度 / 純色照片 → Gemini 分析失敗或給出
極低資訊時的 fallback。

真實情境：
- 照片 QA 不小心把 test chart (純灰 / 純黑 / 色條) 混進批次
- DSLR 失焦整張糊掉 → Gemini 還是會給 response，但 title 會很 generic
  （"A blurry image"）、keywords 可能空
- 照片只有 100x100 → Gemini 看得到但辨識力低

合約：
- resize_for_api 不會因為 1x1 或純色圖 crash
- parse_response 接受 minimal response（只有 title），用 defaults 填滿剩下
- pipeline 把它當 completed 存進 store（有 title 就算成功），不讓這種
  邊角照片 block 整批
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from modules import gemini_vision
from modules import pipeline as pl
from modules.gemini_vision import analyze_photo, parse_response, resize_for_api


def _write_solid(path: Path, color=(0, 0, 0), size=(64, 64)) -> None:
    Image.new("RGB", size, color=color).save(str(path), format="JPEG", quality=85)


def _write_grayscale(path: Path, size=(64, 64)) -> None:
    Image.new("L", size, color=128).save(str(path), format="JPEG", quality=85)


_GOOD_USAGE = {
    "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


def _make_response(text):
    class _R:
        pass
    r = _R()
    r.text = text
    r.usage_metadata = type("UM", (), {
        "prompt_token_count": 10,
        "candidates_token_count": 5,
        "total_token_count": 15,
    })()
    return r


# ---------- resize_for_api handles low-info inputs ----------

def test_resize_survives_pure_black_image(tmp_path):
    photo = tmp_path / "black.jpg"
    _write_solid(photo, color=(0, 0, 0), size=(512, 512))
    out = resize_for_api(photo.read_bytes(), max_size=256)
    assert out.startswith(b"\xff\xd8")  # JPEG SOI


def test_resize_survives_1x1_pixel(tmp_path):
    photo = tmp_path / "tiny.jpg"
    _write_solid(photo, color=(200, 100, 50), size=(1, 1))
    out = resize_for_api(photo.read_bytes(), max_size=3072)
    assert out.startswith(b"\xff\xd8")


def test_resize_converts_grayscale_to_jpeg(tmp_path):
    photo = tmp_path / "gray.jpg"
    _write_grayscale(photo, size=(200, 200))
    out = resize_for_api(photo.read_bytes(), max_size=3072)
    # Grayscale stays grayscale in JPEG (mode L) — still a valid JPEG payload
    assert out.startswith(b"\xff\xd8")


# ---------- parse_response fills defaults for minimal responses ----------

def test_parse_response_fills_defaults_for_one_field_only():
    """Gemini on a pure-black photo may return only {"title": "Black image"}.
    parse_response must fill in description, keywords, category, etc. with
    defaults so downstream (metadata_writer, result_store) doesn't KeyError."""
    minimal = '{"title": "Black image"}'
    result = parse_response(minimal)
    assert result is not None
    assert result["title"] == "Black image"
    # All schema fields present with safe defaults
    assert result["description"] == ""
    assert result["keywords"] == []
    assert result["category"] == ""
    assert result["scene_type"] == ""
    assert result["mood"] == ""
    assert result["people_count"] == 0
    assert result["identified_people"] == []
    assert result["ocr_text"] == []


def test_parse_response_handles_empty_keywords():
    """Common low-info case: Gemini says 'uncertain' and gives empty keywords."""
    minimal = (
        '{"title": "Abstract image", "description": "Unable to identify",'
        ' "keywords": [], "category": "other", "scene_type": "studio",'
        ' "mood": "neutral", "people_count": 0}'
    )
    result = parse_response(minimal)
    assert result is not None
    assert result["keywords"] == []
    # metadata_writer must handle empty keywords without crashing (see
    # build_exiftool_args — empty list produces no keyword args)


def test_build_exiftool_args_no_keywords_still_valid(tmp_path):
    """Regression: empty keywords must not yield malformed exiftool args."""
    from modules.metadata_writer import build_exiftool_args
    args = build_exiftool_args({
        "title": "t", "description": "d",
        "keywords": [], "category": "other",
        "scene_type": "studio", "mood": "neutral",
        "people_count": 0, "identified_people": [], "ocr_text": [],
    })
    # At least the title arg + the HappyVisionProcessed marker must be there
    assert any(a.startswith("-IPTC:Headline=") for a in args)
    assert any("HappyVisionProcessed" in a for a in args)
    # No bare `-IPTC:Keywords+=` (empty value)
    assert not any(a == "-IPTC:Keywords+=" for a in args)


# ---------- end-to-end: pipeline completes low-info photo, no crash ----------

def test_pipeline_marks_low_info_photo_completed(tmp_path, monkeypatch):
    """A pure-gray photo + Gemini returning a minimal response =
    pipeline should save as completed (title present = usable result).
    This is the expected 'good enough' behavior — don't reject just
    because description is empty."""
    photo = tmp_path / "gray.jpg"
    _write_solid(photo, color=(128, 128, 128))

    class _Models:
        def generate_content(self, **_kw):
            return _make_response('{"title": "Grey image"}')

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    class _NoopBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    results = pl.run_pipeline(
        folder=str(tmp_path), api_key="k", concurrency=1,
        write_metadata=False, db_path=tmp_path / "r.db",
    )

    assert len(results) == 1
    assert results[0]["title"] == "Grey image"
    # Ensures the defaults filled in (no KeyError on any downstream access)
    assert results[0]["keywords"] == []


def test_analyze_photo_on_solid_color_returns_result(tmp_path, monkeypatch):
    """Smoke test: solid color photo + good response → (result, usage)."""
    photo = tmp_path / "black.jpg"
    _write_solid(photo, color=(0, 0, 0))

    class _Models:
        def generate_content(self, **_kw):
            return _make_response('{"title": "Dark", "keywords": ["abstract"]}')

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    result, usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=1)
    assert result is not None
    assert result["title"] == "Dark"
    assert usage is not None
    assert usage["total_tokens"] == 15
