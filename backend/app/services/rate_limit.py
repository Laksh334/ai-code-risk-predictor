"""C4 - Brute-force protection for login: too many failed attempts -> temporary lockout.

In-memory (per server process), which is enough for one instance. With several instances
the counters would move to Redis.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class FailedAttemptLimiter:
    def __init__(self, max_failures: int = 5, window_seconds: int = 300):
        self.max_failures, self.window = max_failures, window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def retry_after(self, key: str) -> int:
        """Seconds until `key` may try again (0 = allowed now)."""
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if len(q) < self.max_failures:
                return 0
            return int(self.window - (now - q[0])) + 1

    def failed(self, key: str) -> None:
        with self._lock:
            self._failures[key].append(time.monotonic())

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_limiter = FailedAttemptLimiter()
