"""Token-bucket rate limiter for single-node deployment.

InitRunner is designed for single-node deployment. Multi-node scaling requires
an external state store (Redis/PostgreSQL) which is out of scope for the
lightweight runner.
"""

from __future__ import annotations

import threading
import time


class TokenBucketRateLimiter:
    """Thread-safe token-bucket rate limiter."""

    def __init__(self, rate: float, burst: int) -> None:
        """
        Args:
            rate: Tokens added per second (requests_per_minute / 60).
            burst: Maximum tokens (burst size).
        """
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False
