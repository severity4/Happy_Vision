"""tests/test_rate_limiter.py"""
import threading
import time

import pytest

from modules.rate_limiter import RateLimiter


def test_acquire_initial_tokens_non_blocking():
    """Start with full bucket — first N acquires should be instant."""
    rl = RateLimiter(rate_per_minute=60)
    start = time.monotonic()
    for _ in range(5):
        assert rl.acquire(timeout=0.1) is True
    elapsed = time.monotonic() - start
    assert elapsed < 0.5, f"Initial acquires took {elapsed:.2f}s"


def test_acquire_blocks_when_bucket_empty():
    """After bucket drains, next acquire must wait for refill."""
    rl = RateLimiter(rate_per_minute=60)  # 1 token/sec
    # Drain the bucket
    for _ in range(60):
        rl.acquire(timeout=0.1)

    start = time.monotonic()
    # Next acquire should wait ~1 second for refill
    assert rl.acquire(timeout=2.0) is True
    elapsed = time.monotonic() - start
    assert 0.5 < elapsed < 1.5, f"Refill wait was {elapsed:.2f}s (expected ~1.0s)"


def test_acquire_timeout_returns_false():
    rl = RateLimiter(rate_per_minute=6)  # 1 token / 10s
    # Drain
    for _ in range(6):
        rl.acquire(timeout=0.1)
    # Next acquire with short timeout should fail
    assert rl.acquire(timeout=0.1) is False


def test_refill_accumulates_over_time():
    rl = RateLimiter(rate_per_minute=120)  # 2 tokens/sec
    # Drain
    for _ in range(120):
        rl.acquire(timeout=0.1)
    # Wait 1 second → should have 2 tokens
    time.sleep(1.1)
    start = time.monotonic()
    rl.acquire(timeout=0.5)
    rl.acquire(timeout=0.5)
    elapsed = time.monotonic() - start
    assert elapsed < 0.2, f"Refilled tokens took {elapsed:.2f}s to acquire"


def test_thread_safe_concurrent_acquires():
    """Two threads hammering acquire should not double-spend tokens."""
    rl = RateLimiter(rate_per_minute=60)
    counts = {"a": 0, "b": 0}

    def worker(key):
        for _ in range(40):
            if rl.acquire(timeout=0.05):
                counts[key] += 1

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Combined cannot exceed initial 60 tokens meaningfully during the short window
    total = counts["a"] + counts["b"]
    assert total <= 65, f"Got {total} total acquires; bucket should cap at ~60"
    assert total >= 50, f"Got {total} total; should be close to 60"


def test_invalid_rate_raises():
    with pytest.raises(ValueError):
        RateLimiter(rate_per_minute=0)
    with pytest.raises(ValueError):
        RateLimiter(rate_per_minute=-1)
