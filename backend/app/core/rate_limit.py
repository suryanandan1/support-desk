"""In-memory sliding-window rate limiting.

Counters live in this process. That is right for the single API process this project
runs on Windows; a multi-process deployment would move them to Redis.
"""

import re
import threading
import time
from collections import defaultdict, deque

from app.core.exceptions import AppError

_PERIODS = {"second": 1, "minute": 60, "hour": 3600}
_RATE = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour)\s*$")


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Too many requests. Try again in {retry_after} seconds.")
        self.headers = {"Retry-After": str(retry_after)}


def parse_rate(rate: str) -> tuple[int, int]:
    """'20/minute' -> (20, 60)."""
    match = _RATE.match(rate)
    if not match:
        raise ValueError(f"Invalid rate limit {rate!r}; use the form '20/minute'")
    return int(match.group(1)), _PERIODS[match.group(2)]


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> None:
        """Record one request for ``key``; raise RateLimitedError when over the limit."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                raise RateLimitedError(max(1, int(hits[0] + self.window - now) + 1))
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_limiters: dict[str, RateLimiter] = {}
_registry_lock = threading.Lock()


def get_limiter(name: str, rate: str) -> RateLimiter:
    limit, window = parse_rate(rate)
    with _registry_lock:
        limiter = _limiters.get(name)
        if limiter is None or (limiter.limit, limiter.window) != (limit, window):
            limiter = _limiters[name] = RateLimiter(limit, window)
        return limiter


def reset_all() -> None:
    """Clear every counter (used by the tests)."""
    with _registry_lock:
        for limiter in _limiters.values():
            limiter.reset()
