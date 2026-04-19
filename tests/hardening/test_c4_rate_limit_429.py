"""tests/hardening/test_c4_rate_limit_429.py

Hardening C4: Gemini 回 429 / RESOURCE_EXHAUSTED → retry with exp backoff，
最終失敗歸 failed 但不影響其他照片；rate_limiter 正確退避不 crash。

重點：
- 429 **不是**致命錯誤（和 C3/C5 的 PERMISSION_DENIED 不同）— 只是 too fast
- 重試 `max_retries` 次後若還是 429，僅 fail 該張，batch 繼續
- rate_limiter.acquire 在 timeout 時回 False 也要被優雅處理

為了速度，我們 monkey-patch `time.sleep` 避免實際睡 1s+2s+4s = 7s × N 張。
"""

from __future__ import annotations

import threading
from pathlib import Path

from modules import gemini_vision
from modules import pipeline as pl
from modules import rate_limiter as rl
from modules.gemini_vision import analyze_photo


_MOCK_USAGE_META = type("UM", (), {
    "prompt_token_count": 10,
    "candidates_token_count": 5,
    "total_token_count": 15,
})()


def _write_jpg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (64, 64), color="white").save(str(path), format="JPEG")


def _fake_response(text):
    class _R:
        pass
    r = _R()
    r.text = text
    r.usage_metadata = _MOCK_USAGE_META
    return r


class _NoopBatch:
    def write(self, *_a, **_kw): return True
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_a): pass


def test_analyze_photo_retries_on_429_and_eventually_succeeds(
    tmp_path, monkeypatch,
):
    """First two attempts 429, third succeeds. Must return the result."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    # Skip the backoff sleep — tests must finish < 1s.
    sleeps: list[float] = []
    monkeypatch.setattr(
        gemini_vision.time, "sleep",
        lambda s: sleeps.append(s),
    )

    attempt = {"n": 0}

    class _Models:
        def generate_content(self, **_kw):
            attempt["n"] += 1
            if attempt["n"] <= 2:
                raise Exception("429 RESOURCE_EXHAUSTED: rate limit exceeded")
            return _fake_response(
                '{"title": "ok", "description": "d", "keywords": [], '
                '"category": "other", "scene_type": "indoor", '
                '"mood": "neutral", "people_count": 0}'
            )

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    result, usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=3)

    assert result is not None
    assert result["title"] == "ok"
    assert usage is not None
    # Exponential backoff: 2^0=1, 2^1=2. Both logged.
    assert sleeps == [1, 2]


def test_analyze_photo_exhausts_retries_and_returns_none_on_persistent_429(
    tmp_path, monkeypatch,
):
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    attempt = {"n": 0}

    class _Models:
        def generate_content(self, **_kw):
            attempt["n"] += 1
            raise Exception("429 RESOURCE_EXHAUSTED")

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    result, usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=3)

    assert result is None
    assert usage is None
    # Exactly max_retries attempts, no extra.
    assert attempt["n"] == 3


def test_pipeline_continues_after_one_photo_exhausts_429_retries(
    tmp_path, monkeypatch,
):
    """Photo 1 gets permanent 429 (retries → fail). Photo 2 succeeds.
    Batch must not halt on the one failure; only auth/quota halts batch."""
    for i in range(2):
        _write_jpg(tmp_path / f"p{i:02d}.jpg")

    monkeypatch.setattr(gemini_vision.time, "sleep", lambda _s: None)

    counter = {"n": 0}
    lock = threading.Lock()

    class _Models:
        def generate_content(self, **_kw):
            with lock:
                counter["n"] += 1
                n = counter["n"]
            # First 3 calls all 429 (photo 1's retries). Calls 4+ succeed.
            if n <= 3:
                raise Exception("429 RESOURCE_EXHAUSTED")
            return _fake_response(
                '{"title": "ok", "description": "d", "keywords": [], '
                '"category": "other", "scene_type": "indoor", '
                '"mood": "neutral", "people_count": 0}'
            )

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())
    monkeypatch.setattr(pl, "ExiftoolBatch", _NoopBatch)

    results = pl.run_pipeline(
        folder=str(tmp_path),
        api_key="test",
        concurrency=1,  # deterministic order
        write_metadata=False,
        db_path=tmp_path / "r.db",
    )

    # One succeeded (photo 2 got calls 4+).
    assert len(results) == 1
    # We tried 3 times for photo 1, then 1 time for photo 2 = 4 total.
    assert counter["n"] == 4


def test_rate_limiter_timeout_is_handled_gracefully(tmp_path, monkeypatch):
    """If rate_limiter.acquire returns False (bucket closed / timeout),
    analyze_photo must return (None, None) and MUST NOT call the API."""
    photo = tmp_path / "p.jpg"
    _write_jpg(photo)

    # Replace default_limiter with one whose acquire always returns False.
    class _FailingLimiter:
        def acquire(self, timeout=None):
            return False

    monkeypatch.setattr(rl, "default_limiter", _FailingLimiter())

    # Client construction is cached and cheap — allow it. But the API call
    # (generate_content) must never fire when the limiter denied us.
    api_called = {"n": 0}

    class _Models:
        def generate_content(self, **_kw):
            api_called["n"] += 1
            raise RuntimeError("must not be called when limiter failed")

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_vision, "_get_client", lambda _k: _Client())

    result, usage = analyze_photo(str(photo), api_key="k", model="lite", max_retries=1)
    assert result is None
    assert usage is None
    assert api_called["n"] == 0, "API was invoked despite rate limiter denial"


def test_rate_limiter_acquire_refills_and_unblocks():
    """Unit test: deplete bucket, then wait → acquire succeeds once refilled.
    Uses rate_per_minute=600 so 1 token refills in 100ms — keeps test < 1s."""
    limiter = rl.RateLimiter(rate_per_minute=600)
    # Drain bucket.
    for _ in range(600):
        assert limiter.acquire(timeout=0.01) is True
    # Immediately next acquire should need to wait ~100ms.
    import time
    start = time.monotonic()
    assert limiter.acquire(timeout=0.5) is True
    elapsed = time.monotonic() - start
    assert 0.05 <= elapsed <= 0.5, f"refill wait unexpected: {elapsed}s"


def test_rate_limiter_close_wakes_waiters():
    """configure() replaces the limiter; old waiters must be released
    immediately so they retry under the new rate."""
    limiter = rl.RateLimiter(rate_per_minute=1)  # one token per minute = long wait
    # Consume the only token.
    assert limiter.acquire(timeout=0.01) is True

    released = threading.Event()

    def wait_and_fail():
        # This should block until close() wakes us, NOT until the next
        # token refills (which is ~60s away).
        got = limiter.acquire(timeout=5.0)
        assert got is False
        released.set()

    t = threading.Thread(target=wait_and_fail, daemon=True)
    t.start()

    import time
    time.sleep(0.05)  # let the thread enter wait()
    limiter.close()

    t.join(timeout=2.0)
    assert released.is_set(), "close() did not wake the waiter"
