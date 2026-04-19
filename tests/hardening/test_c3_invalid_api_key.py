"""tests/hardening/test_c3_invalid_api_key.py

Hardening C3: Gemini 回 401 / API_KEY_INVALID / UNAUTHENTICATED / PERMISSION_DENIED
時，pipeline 必須立刻停止整批，不可繼續逐張呼叫（燒時間 + 製造 500 筆一模
一樣的失敗紀錄讓 result_store 變得沒法用）。

同事第一次設完 key 很可能打錯一個字。一個 500-photo dogfood batch 在錯 key
下應該 3 秒內結束並清楚告訴使用者「去設定裡重新輸入 API key」，而不是跑 10
分鐘後留下一屋子 `failed` row。
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from modules import gemini_vision
from modules import pipeline as pl
from modules.gemini_vision import InvalidAPIKeyError, analyze_photo


_MOCK_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "total_tokens": 15,
    "model": "gemini-2.5-flash-lite",
}


def _write_jpg(path: Path) -> None:
    # Minimal valid JPEG magic so resize_for_api doesn't short-circuit us
    # before we get to the mocked API call.
    from PIL import Image
    Image.new("RGB", (64, 64), color="white").save(str(path), format="JPEG")


def test_analyze_photo_raises_invalid_key_error_on_api_key_invalid(tmp_path, monkeypatch):
    """analyze_photo must not swallow 401 — the caller needs a chance to
    stop the batch. Currently a generic return (None, None) makes every
    subsequent photo re-trigger the same failure."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    class _FakeModels:
        def generate_content(self, **_kw):
            raise Exception("400 API_KEY_INVALID: API key not valid. Please pass a valid API key.")

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _FakeClient())

    with pytest.raises(InvalidAPIKeyError):
        analyze_photo(str(photo), api_key="bogus", model="lite", max_retries=1)


def test_analyze_photo_raises_invalid_key_error_on_unauthenticated(tmp_path, monkeypatch):
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    class _FakeModels:
        def generate_content(self, **_kw):
            raise Exception("401 UNAUTHENTICATED: request had invalid credentials")

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _FakeClient())

    with pytest.raises(InvalidAPIKeyError):
        analyze_photo(str(photo), api_key="bogus", model="lite", max_retries=1)


def test_pipeline_halts_on_auth_error_before_burning_remaining_photos(tmp_path, monkeypatch):
    """Real scenario: 10 photos, bad key. analyze_photo should be called at
    most once (maybe twice under concurrency race), then pipeline halts."""
    for i in range(10):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    # Track every analyze_photo call; raise InvalidAPIKeyError on the first.
    call_count = {"n": 0}
    lock = threading.Lock()

    def exploding_analyze(path, **_kw):
        with lock:
            call_count["n"] += 1
        raise InvalidAPIKeyError("API_KEY_INVALID: fake")

    monkeypatch.setattr(pl, "analyze_photo", exploding_analyze)

    class _NoopBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    errors = []

    class _CB(pl.PipelineCallbacks):
        def on_error(self, path, err):
            errors.append((path, err))

    # concurrency=1 keeps the test deterministic on halt count.
    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="bogus",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
        callbacks=_CB(),
    )

    assert results == []
    # Critical assertion: we should NOT have called analyze_photo 10 times.
    # One failure is enough to halt the batch.
    assert call_count["n"] <= 2, f"pipeline kept burning after auth error: {call_count['n']} calls"
    # User must see an error mentioning the API key, not a generic failure.
    assert errors, "pipeline must surface the auth error via callbacks.on_error"
    assert any("api key" in err.lower() or "auth" in err.lower() or "invalid" in err.lower()
               for _path, err in errors)


def test_pipeline_auth_halt_keeps_successful_photos(tmp_path, monkeypatch):
    """If photos 1-2 succeed and photo 3 hits 401, photos 1-2 results must
    remain persisted. The halt must not roll back prior work."""
    for i in range(5):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    call_order = []
    lock = threading.Lock()

    def mixed_analyze(path, **_kw):
        with lock:
            call_order.append(Path(path).name)
            n = len(call_order)
        if n <= 2:
            return (
                {
                    "title": f"t{n}",
                    "description": "d",
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
        raise InvalidAPIKeyError("API_KEY_INVALID")

    monkeypatch.setattr(pl, "analyze_photo", mixed_analyze)

    class _NoopBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="bogus",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    # 2 good results preserved, rest never analyzed.
    assert len(results) == 2
    assert len(call_order) <= 4  # allow 1 call after last success before halt propagates


def test_non_auth_errors_do_not_halt_batch(tmp_path, monkeypatch):
    """Regression guard: a generic 500 server error on ONE photo must NOT
    halt the batch — that's the job only for auth failures. Batch should
    fail that one photo and move on."""
    for i in range(3):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    call_count = {"n": 0}
    lock = threading.Lock()

    def mixed_analyze(path, **_kw):
        with lock:
            call_count["n"] += 1
            n = call_count["n"]
        if n == 1:
            return (None, None)  # generic failure (e.g., parse error)
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

    monkeypatch.setattr(pl, "analyze_photo", mixed_analyze)

    class _NoopBatch:
        def write(self, *_a, **_kw): return True
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *_a): pass

    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="ok",
        concurrency=1,
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    # 2 successes despite the first one failing with non-auth error.
    assert len(results) == 2
    assert call_count["n"] == 3
