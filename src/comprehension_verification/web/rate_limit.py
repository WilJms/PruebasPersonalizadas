"""Small bounded rate limiter for the private experimental HTTP surface.

The limiter is intentionally process-local: it is a first denial-of-wallet
boundary in front of the durable cost and idempotency guards, not a distributed
quota or a second queue.  Cloud Run instance limits keep the aggregate ceiling
bounded and the application never records request bodies or student content.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic


@dataclass(slots=True)
class _Window:
    started_at: float
    count: int


class FixedWindowRateLimiter:
    """Thread-safe fixed-window limiter with bounded in-memory cardinality."""

    def __init__(self, *, window_seconds: int = 60, max_keys: int = 10_000) -> None:
        if window_seconds < 1 or max_keys < 1:
            raise ValueError("rate limiter bounds must be positive")
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._windows: dict[str, _Window] = {}
        self._lock = Lock()

    def consume(self, key: str, *, limit: int) -> tuple[bool, int]:
        """Consume one unit and return ``(allowed, retry_after_seconds)``."""

        if limit < 1:
            raise ValueError("rate limit must be positive")
        now = monotonic()
        with self._lock:
            current = self._windows.get(key)
            if current is None or now - current.started_at >= self.window_seconds:
                if len(self._windows) >= self.max_keys:
                    expired = [
                        item_key
                        for item_key, window in self._windows.items()
                        if now - window.started_at >= self.window_seconds
                    ]
                    for item_key in expired:
                        self._windows.pop(item_key, None)
                    if len(self._windows) >= self.max_keys:
                        oldest = min(
                            self._windows,
                            key=lambda item_key: self._windows[item_key].started_at,
                        )
                        self._windows.pop(oldest, None)
                self._windows[key] = _Window(started_at=now, count=1)
                return True, 0
            if current.count >= limit:
                remaining = max(
                    1,
                    int(self.window_seconds - (now - current.started_at) + 0.999),
                )
                return False, remaining
            current.count += 1
            return True, 0
