"""Received-byte limits before parsing, including chunked uploads and disconnects."""

from __future__ import annotations

import asyncio
import tempfile
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request
from starlette.responses import Response

from initrunner.middleware import BodySizeLimitMiddleware, detail_error_response


async def exercise(app, messages, *, headers=(), method="POST", path="/"):
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 1),
        "headers": list(headers),
    }
    incoming = iter(messages)
    sent = []

    async def receive():
        return next(incoming, {"type": "http.disconnect"})

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return sent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        (),
        ((b"content-length", b"1"),),
        ((b"content-length", b"bad"),),
        ((b"transfer-encoding", b"chunked"),),
    ],
)
async def test_received_bytes_override_headers_and_stop_reading(headers):
    downstream = AsyncMock()
    app = BodySizeLimitMiddleware(downstream, max_bytes=5, error_response=detail_error_response)
    messages = [
        {"type": "http.request", "body": b"123", "more_body": True},
        {"type": "http.request", "body": b"456", "more_body": True},
    ]
    sent = await exercise(app, messages, headers=headers)
    assert sent[0]["status"] == 413
    downstream.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, 4, 5])
async def test_accepted_body_is_replayed_exactly(size):
    seen = []

    async def downstream(scope, receive, send):
        seen.append(await Request(scope, receive).body())
        await Response(b"data: one\n\ndata: two\n\n", media_type="text/event-stream")(
            scope, receive, send
        )

    app = BodySizeLimitMiddleware(downstream, max_bytes=5, error_response=detail_error_response)
    sent = await exercise(app, [{"type": "http.request", "body": b"x" * size}])
    assert seen == [b"x" * size]
    assert sent[0]["status"] == 200
    assert sent[1]["body"] == b"data: one\n\ndata: two\n\n"


@pytest.mark.asyncio
async def test_large_upload_spools_and_closes_even_on_rejection_or_disconnect(monkeypatch):
    original = tempfile.SpooledTemporaryFile
    files = []

    def track(*args, **kwargs):
        f = original(*args, **kwargs)
        files.append(f)
        return f

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", track)
    downstream = AsyncMock()
    app = BodySizeLimitMiddleware(
        downstream, max_bytes=2_000_000, error_response=detail_error_response
    )
    for last in [
        {"type": "http.request", "body": b"x" * 1_000_000},
        {"type": "http.disconnect"},
    ]:
        await exercise(
            app, [{"type": "http.request", "body": b"x" * 1_100_000, "more_body": True}, last]
        )
        assert files[-1]._rolled
        assert files[-1].closed
    downstream.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_read_closes_spool(monkeypatch):
    original = tempfile.SpooledTemporaryFile
    files = []

    def track(*args, **kwargs):
        f = original(*args, **kwargs)
        files.append(f)
        return f

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", track)
    app = BodySizeLimitMiddleware(AsyncMock(), max_bytes=10, error_response=detail_error_response)

    async def cancelled():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await app({"type": "http", "method": "POST"}, cancelled, AsyncMock())
    assert files[0].closed


def test_nonpositive_limit_is_invalid():
    with pytest.raises(ValueError):
        BodySizeLimitMiddleware(AsyncMock(), max_bytes=0, error_response=detail_error_response)
