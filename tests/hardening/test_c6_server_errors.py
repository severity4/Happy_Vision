"""tests/hardening/test_c6_server_errors.py

Hardening C6: Gemini 回 500 / 502 / 503 / 504 → 重試退避，失敗時僅標記該
張 failed，不影響其他照片；batch 繼續，已完成的不被回滾。

類似 C4 (429 rate limit)，但特別鎖死這些五位數 HTTP 狀態碼也走可重試路徑
而不是被分類成致命錯誤（C3/C5 auth-halt）。

為了速度，`time.sleep` 被 monkey-patch 掉（預設退避 1s+2s+4s = 7s × N 張
會讓測試變慢）。
"""

from __future__ import annotations

import threading
from pathlib import Path

from modules import gemini_vision
from modules import pipeline as pl
from modules.gemini_vision import analyze_photo


_MOCK_USAGE_META = type("UM", (), {
    "prompt_token_count": 10,
    "candidates_token_count": 5,
    "total_token_count": 15,
})()


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (32, 32), color="white").save(str(path), format="JPEG")


def _fake_response(text: str):
    class _R:
        pass
    r = _R()
    r.text = text
    r.usage_metadata = _MOCK_USAGE_META
    return r


_GOOD_JSON = (
    '{"title": "ok", "description": "d", "keywords": [], '
    '"category": "other", "scene_type": "indoor", '
    '"mood": "neutral", "people_count": 0}'
)


class _NoopBatch:
    def write(self, *_a, **_kw): return True
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_a): pass


def test_500_internal_error_is_retried_not_halted(tmp_path, monkeypatch):
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    attempt = {"n": 0}

    class _Models:
        def generate_content(self, **_kw):
            attempt["n"] += 1
            if attempt["n"] < 3:
                raise Exception("500 INTERNAL: internal server error")
            return _fake_response(_GOOD_JSON)

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    result, _usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=3)

    assert result is not None
    assert result["title"] == "ok"
    assert attempt["n"] == 3  # 2 failures + 1 success


def test_502_bad_gateway_is_retried(tmp_path, monkeypatch):
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    attempt = {"n": 0}

    class _Models:
        def generate_content(self, **_kw):
            attempt["n"] += 1
            if attempt["n"] < 2:
                raise Exception("502 Bad Gateway")
            return _fake_response(_GOOD_JSON)

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    result, _usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=3)
    assert result is not None


def test_503_unavailable_is_retried(tmp_path, monkeypatch):
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    attempt = {"n": 0}

    class _Models:
        def generate_content(self, **_kw):
            attempt["n"] += 1
            if attempt["n"] < 2:
                raise Exception("503 UNAVAILABLE: service temporarily overloaded")
            return _fake_response(_GOOD_JSON)

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    result, _usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=3)
    assert result is not None


def test_504_deadline_exceeded_is_retried(tmp_path, monkeypatch):
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    attempt = {"n": 0}

    class _Models:
        def generate_content(self, **_kw):
            attempt["n"] += 1
            if attempt["n"] < 2:
                raise Exception("504 DEADLINE_EXCEEDED: request timed out")
            return _fake_response(_GOOD_JSON)

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    result, _usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=3)
    assert result is not None


def test_persistent_500_exhausts_retries_and_marks_failed_without_halting_batch(
    tmp_path, monkeypatch,
):
    """Photo 1: server error every attempt → failed after max_retries.
    Photo 2: first call succeeds. Batch must NOT halt on photo 1."""
    for i in range(2):
        _write_jpg(tmp_path / f"p{i}.jpg")

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    counter = {"n": 0}
    lock = threading.Lock()

    class _Models:
        def generate_content(self, **_kw):
            with lock:
                counter["n"] += 1
                n = counter["n"]
            # First 3 calls = photo 1's 3 retries, all 500. Call 4 = photo 2.
            if n <= 3:
                raise Exception("500 INTERNAL")
            return _fake_response(_GOOD_JSON)

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    # One succeeded despite the other photo's 3 retries all failing.
    assert len(results) == 1
    # Total API calls = 3 (photo 1 retries) + 1 (photo 2 success) = 4.
    assert counter["n"] == 4


def test_500_does_not_match_auth_fatal_markers(tmp_path, monkeypatch):
    """Regression guard: '500 INTERNAL' must not match the fatal-auth
    markers (PERMISSION_DENIED etc). If it did, a single flaky 500
    would halt the whole batch instead of being retried."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    class _Models:
        def generate_content(self, **_kw):
            raise Exception("500 INTERNAL: server hiccup")

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    # Must NOT raise InvalidAPIKeyError — just returns (None, None) after
    # exhausting retries.
    result, usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=2)
    assert result is None
    assert usage is None
