"""P3 hardening: subprocess env scrubbing breadth and bounded body reads."""

from __future__ import annotations

import asyncio

import pytest
from starlette.requests import Request

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


def _streaming_request(chunks: list[bytes]) -> Request:
    """A real Starlette Request whose body arrives in chunks (no Content-Length)."""
    queue = list(chunks)

    async def receive():
        if queue:
            return {"type": "http.request", "body": queue.pop(0), "more_body": bool(queue)}
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request({"type": "http", "method": "POST", "headers": [], "query_string": b""}, receive)


class TestReadBodyCapped:
    def test_under_cap_returns_body(self):
        req = _streaming_request([b"ab", b"cd", b"ef"])
        assert asyncio.run(read_body_capped(req, 100)) == b"abcdef"

    def test_over_cap_returns_none(self):
        # Chunked stream with no Content-Length: must abort once the cap is crossed.
        req = _streaming_request([b"x" * 8, b"y" * 8])
        assert asyncio.run(read_body_capped(req, 10)) is None

    def test_exact_cap_ok(self):
        req = _streaming_request([b"x" * 10])
        assert asyncio.run(read_body_capped(req, 10)) == b"x" * 10
