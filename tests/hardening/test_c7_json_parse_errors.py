"""tests/hardening/test_c7_json_parse_errors.py

Hardening C7: Gemini 回傳格式錯誤 / 截斷 / 非 JSON / 空字串 / None → 該張
標記失敗，不可讓整批 crash。

現實情境：Gemini 在高負載期偶爾會送回截斷 JSON；`response_schema` 理論上
enforce 結構但 SDK 某些路徑繞過；safety filter 有機率讓 `response.text`
變 None 或空字串。這裡把所有 parse_response 的角落情境封死。
"""

from __future__ import annotations

from pathlib import Path

from modules import gemini_vision
from modules import pipeline as pl
from modules.gemini_vision import analyze_photo, parse_response


_MOCK_USAGE_META = type("UM", (), {
    "prompt_token_count": 10,
    "candidates_token_count": 5,
    "total_token_count": 15,
})()


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (64, 64), color="white").save(str(path), format="JPEG")


# ---------- parse_response unit tests ----------

def test_parse_response_returns_none_for_empty_string():
    assert parse_response("") is None


def test_parse_response_returns_none_for_whitespace_only():
    assert parse_response("   \n  \t  ") is None


def test_parse_response_returns_none_for_truncated_json():
    truncated = '{"title": "Great shot", "description": "An event ph'
    assert parse_response(truncated) is None


def test_parse_response_returns_none_for_html_error_page():
    html = "<html><body><h1>502 Bad Gateway</h1></body></html>"
    assert parse_response(html) is None


def test_parse_response_returns_none_for_non_object_root():
    """Gemini structured-output schema enforces object, but if SDK drift or
    a fallback path emits a bare list / string, we must not return that to
    result_store (which expects a dict)."""
    for bad in ["[]", '"just a string"', "null", "42", "true"]:
        result = parse_response(bad)
        # Either None OR a dict (if we later add coercion). NEVER a list/str.
        assert result is None or isinstance(result, dict), (
            f"parse_response leaked non-dict type for {bad!r}: {type(result)}"
        )


def test_parse_response_handles_unclosed_code_fence():
    """Model sometimes wraps output in ```json without the closing fence."""
    wrapped = '```json\n{"title": "t", "keywords": []}'
    result = parse_response(wrapped)
    # Either parsed successfully OR returned None cleanly — no crash.
    assert result is None or isinstance(result, dict)


def test_parse_response_handles_proper_code_fence():
    wrapped = '```json\n{"title": "t", "keywords": []}\n```'
    result = parse_response(wrapped)
    assert isinstance(result, dict)
    assert result["title"] == "t"


def test_parse_response_fills_defaults_for_missing_fields():
    """Gemini sometimes omits optional fields. Defaults must fill in or
    downstream callers (report_generator, metadata_writer) KeyError."""
    minimal = '{"title": "t"}'
    result = parse_response(minimal)
    assert result is not None
    # Default fields present
    for key in ("description", "keywords", "category", "subcategory",
                "scene_type", "mood", "people_count",
                "identified_people", "ocr_text"):
        assert key in result


# ---------- analyze_photo end-to-end with corrupt response ----------

def _make_response(text):
    """Fake Gemini response with controllable .text."""
    class _R:
        pass
    r = _R()
    r.text = text
    r.usage_metadata = _MOCK_USAGE_META
    return r


def _patch_client_returning(monkeypatch, text):
    class _Models:
        def generate_content(self, **_kw):
            return _make_response(text)

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())


def test_analyze_photo_returns_none_on_empty_text(tmp_path, monkeypatch):
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)
    _patch_client_returning(monkeypatch, "")

    result, usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=1)
    assert result is None
    assert usage is None


def test_analyze_photo_returns_none_on_truncated_json(tmp_path, monkeypatch):
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)
    _patch_client_returning(monkeypatch, '{"title": "half')

    result, usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=1)
    assert result is None
    assert usage is None


def test_analyze_photo_handles_none_response_text(tmp_path, monkeypatch):
    """If safety filter fully blocks, response.text may be None. A naive
    `.strip()` on None raises AttributeError, which would escape to the
    outer handler — but would the handler classify it correctly? We want
    a graceful (None, None), not a crash."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)
    _patch_client_returning(monkeypatch, None)

    result, usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=1)
    assert result is None
    assert usage is None


def test_pipeline_marks_one_photo_failed_and_continues_on_parse_error(
    tmp_path, monkeypatch,
):
    """Mixed batch: photo 1 gets good JSON, photo 2 gets truncated JSON,
    photo 3 gets good JSON. Must end with 2 completed + 1 failed, no
    crash of the whole batch."""
    for i in range(3):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    seq = iter([
        '{"title": "ok1", "description": "d", "keywords": [], "category": "other", "scene_type": "indoor", "mood": "neutral", "people_count": 0}',
        '{"title": "trunc',  # broken
        '{"title": "ok3", "description": "d", "keywords": [], "category": "other", "scene_type": "indoor", "mood": "neutral", "people_count": 0}',
    ])

    class _Models:
        def generate_content(self, **_kw):
            return _make_response(next(seq))

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
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,  # deterministic ordering for seq
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    assert len(results) == 2
    titles = {r["title"] for r in results}
    assert titles == {"ok1", "ok3"}
