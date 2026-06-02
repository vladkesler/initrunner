"""P3 hardening: subprocess env scrubbing breadth and bounded body reads."""

from __future__ import annotations

import pytest

from initrunner.agent._subprocess import scrub_env
from initrunner.middleware import read_body_capped


class TestScrubEnvBreadth:
    @pytest.mark.parametrize(
        "name",
        [
            "AWS_ACCESS_KEY_ID",  # ends in _ID -> only the AWS_ prefix catches it
            "AWS_SECRET_ACCESS_KEY",
            "GITHUB_PAT",  # ends in _PAT
            "SECRET_KEY_BASE",  # framework secret, ends in _BASE
            "SENTRY_DSN",  # ends in _DSN
            "MYAPP_DSN",
            "OPENAI_API_KEY",
            "STRIPE_SECRET_KEY",
            "SLACK_WEBHOOK_URL",
            "DATABASE_URL",
            "JWT_SECRET",
            "DD_API_KEY",
        ],
    )
    def test_sensitive_names_scrubbed(self, name, monkeypatch):
        monkeypatch.setenv(name, "leak")
        assert name not in scrub_env()

    @pytest.mark.parametrize(
        "name", ["PATH", "HOME", "LANG", "TERM", "MY_PROJECT_DIR", "AWS_PLAIN"]
    )
    def test_benign_names_kept(self, name, monkeypatch):
        # AWS_PLAIN starts with AWS_ -> intentionally dropped (broad prefix); the
        # rest are kept. Assert the clearly-benign ones survive.
        monkeypatch.setenv(name, "value")
        env = scrub_env()
        if name == "AWS_PLAIN":
            assert name not in env  # broad AWS_ prefix is deliberate
        else:
            assert env.get(name) == "value"


class _FakeRequest:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def stream(self):
        for c in self._chunks:
            yield c


class TestReadBodyCapped:
    def test_under_cap_returns_body(self):
        import asyncio

        assert asyncio.run(read_body_capped(_FakeRequest([b"ab", b"cd", b"ef"]), 100)) == b"abcdef"

    def test_over_cap_returns_none(self):
        # Chunked stream with no Content-Length: must abort once the cap is crossed.
        import asyncio

        assert asyncio.run(read_body_capped(_FakeRequest([b"x" * 8, b"y" * 8]), 10)) is None

    def test_exact_cap_ok(self):
        import asyncio

        assert asyncio.run(read_body_capped(_FakeRequest([b"x" * 10]), 10)) == b"x" * 10
