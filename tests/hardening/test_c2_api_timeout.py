"""tests/hardening/test_c2_api_timeout.py

Hardening C2: Gemini API 回應超時（模擬 30s+ 無回應）→ 重試機制啟動，
最終放棄時優雅失敗。

和 C6 (500/503) 差異：這裡專門處理 timeout-shaped errors —
`TimeoutError`, `socket.timeout`, SDK 的 `DEADLINE_EXCEEDED`，以及
requests 的 `ReadTimeout`。

映奧活動一次幾千張，偶爾會遇到單一 request 卡住的情況（Gemini 對某張
特別大的 photo 思考時間過長）。這時不應該讓整個 worker thread 無期限等待，
也不應該一次失敗就放棄；應該 timeout → retry → 最終失敗該張 → batch 繼續。
"""

from __future__ import annotations

import socket
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


def test_deadline_exceeded_is_retryable(tmp_path, monkeypatch):
    """SDK raises with 'DEADLINE_EXCEEDED' in the message — already in
    retryable_markers. Lock it in."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    attempt = {"n": 0}

    class _Models:
        def generate_content(self, **_kw):
            attempt["n"] += 1
            if attempt["n"] < 3:
                raise Exception("504 DEADLINE_EXCEEDED")
            return _fake_response(_GOOD_JSON)

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    result, _usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=3)
    assert result is not None
    assert attempt["n"] == 3


def test_socket_timeout_is_retryable(tmp_path, monkeypatch):
    """Bare socket.timeout from a stuck HTTPS read."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    attempt = {"n": 0}

    class _Models:
        def generate_content(self, **_kw):
            attempt["n"] += 1
            if attempt["n"] < 2:
                raise socket.timeout("timed out")
            return _fake_response(_GOOD_JSON)

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    result, _usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=3)
    assert result is not None


def test_read_timeout_is_retryable(tmp_path, monkeypatch):
    """requests.ReadTimeout shape: 'Read timed out. (read timeout=60)'."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    attempt = {"n": 0}

    class _Models:
        def generate_content(self, **_kw):
            attempt["n"] += 1
            if attempt["n"] < 2:
                raise TimeoutError("Read timed out. (read timeout=60)")
            return _fake_response(_GOOD_JSON)

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    result, _usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=3)
    assert result is not None


def test_persistent_timeout_exhausts_retries_and_moves_on(tmp_path, monkeypatch):
    """If one photo keeps timing out, it should fail after retries but
    the next photo still gets processed."""
    for i in range(2):
        _write_jpg(tmp_path / f"p{i}.jpg")

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    call_count = {"n": 0}
    lock = threading.Lock()

    class _Models:
        def generate_content(self, **_kw):
            with lock:
                call_count["n"] += 1
                n = call_count["n"]
            if n <= 3:
                raise TimeoutError("DEADLINE_EXCEEDED")
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

    assert len(results) == 1
    assert call_count["n"] == 4


def test_timeout_during_analyze_does_not_block_worker_indefinitely(
    tmp_path, monkeypatch,
):
    """Guard against 'worker thread blocked forever' — the retry path
    must exit after max_retries regardless of error type."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    class _Models:
        def generate_content(self, **_kw):
            raise TimeoutError("DEADLINE_EXCEEDED")

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    result: list = []
    done = threading.Event()

    def runner():
        r = analyze_photo(str(photo), api_key="k", model="lite", max_retries=3)
        result.append(r)
        done.set()

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    done.wait(timeout=5.0)

    assert done.is_set(), "analyze_photo blocked > 5s on timeouts — infinite loop regression"
    assert result and result[0] == (None, None)
