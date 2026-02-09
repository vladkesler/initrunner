"""Tests for the token-bucket rate limiter."""

from __future__ import annotations

import time

from initrunner.server.rate_limiter import TokenBucketRateLimiter


class TestTokenBucketRateLimiter:
    def test_allows_within_burst(self):
        limiter = TokenBucketRateLimiter(rate=1.0, burst=3)
        assert limiter.allow() is True
        assert limiter.allow() is True
        assert limiter.allow() is True

    def test_blocks_after_burst(self):
        limiter = TokenBucketRateLimiter(rate=1.0, burst=2)
        assert limiter.allow() is True
        assert limiter.allow() is True
        assert limiter.allow() is False

    def test_refills_over_time(self):
        limiter = TokenBucketRateLimiter(rate=100.0, burst=1)
        assert limiter.allow() is True
        assert limiter.allow() is False
        time.sleep(0.02)  # Wait for refill
        assert limiter.allow() is True

    def test_does_not_exceed_burst(self):
        limiter = TokenBucketRateLimiter(rate=100.0, burst=2)
        assert limiter.allow() is True
        assert limiter.allow() is True
        assert limiter.allow() is False
        time.sleep(0.1)  # Wait long enough for several tokens
        # Should refill up to burst (2), not more
        assert limiter.allow() is True
        assert limiter.allow() is True
        assert limiter.allow() is False

    def test_zero_rate_blocks(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst=1)
        assert limiter.allow() is True
        assert limiter.allow() is False
        time.sleep(0.01)
        assert limiter.allow() is False
