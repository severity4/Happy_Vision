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


# Default limiter used by gemini_vision.analyze_photo. Configured at import time
# with a conservative default; web_ui or pipeline can call `configure(...)` to
# adjust based on user's Gemini plan.
default_limiter = RateLimiter(rate_per_minute=60)


def configure(rate_per_minute: int) -> None:
    """Replace the default limiter with one at the given rate."""
    global default_limiter
    default_limiter = RateLimiter(rate_per_minute=rate_per_minute)
