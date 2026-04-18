"""modules/rate_limiter.py — Token bucket rate limiter (thread-safe).

Shared between pipeline and folder_watcher so concurrent Gemini API calls
respect a single RPM budget instead of each worker thread independently
backing off on 429s."""

import threading
import time


class RateLimiter:
    """Simple token bucket. Acquire blocks until a token is available.

    Bucket starts full. Tokens refill continuously at rate_per_minute/60 per
    second, capped at rate_per_minute total.
    """

    def __init__(self, rate_per_minute: int):
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be positive")
        self._capacity = float(rate_per_minute)
        self._refill_per_sec = rate_per_minute / 60.0
        self._tokens = float(rate_per_minute)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

    @property
    def rate_per_minute(self) -> int:
        return int(self._capacity)

    def _refill(self) -> None:
        """Must be called with self._lock held."""
        now = time.monotonic()
        delta = now - self._last_refill
        if delta > 0:
            self._tokens = min(self._capacity, self._tokens + delta * self._refill_per_sec)
            self._last_refill = now

    def acquire(self, timeout: float | None = None) -> bool:
        """Block until a token is available. Returns True on success,
        False if timeout expired."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while True:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return True
                # Need to wait for more tokens
                needed = 1 - self._tokens
                wait_time = needed / self._refill_per_sec
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    wait_time = min(wait_time, remaining)
                self._cond.wait(timeout=wait_time)


# Default limiter used by gemini_vision.analyze_photo. Starts at a conservative
# 60 RPM (Gemini free tier). web_ui.py calls `configure(...)` during post-start
# init to apply the user's configured `rate_limit_rpm`. Runtime changes via
# /api/settings also call configure().
#
# IMPORTANT: callers must access this through `rate_limiter.default_limiter`
# (module attribute), NOT `from modules.rate_limiter import default_limiter`,
# so that `configure()` swaps are visible live.
default_limiter = RateLimiter(rate_per_minute=60)


def configure(rate_per_minute: int) -> None:
    """Replace the default limiter with one at the given rate.

    Clamps to [1, 5000] — above 2000 is beyond anything Google publishes for
    flash-lite on paid tier so we leave headroom but don't let users footgun
    themselves with nonsense values. Returns silently if already at the rate."""
    global default_limiter
    rate = max(1, min(5000, int(rate_per_minute)))
    if rate == default_limiter.rate_per_minute:
        return
    default_limiter = RateLimiter(rate_per_minute=rate)
