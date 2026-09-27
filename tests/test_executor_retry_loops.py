"""A model HTTP client must survive being used from a new event loop per run.

The client is built once with the agent, but ``run_sync`` starts a fresh event
loop for every run. Before the per-loop transport, the second run reused a
connection pooled on the first (closed) loop and failed with "Event loop is
closed": every second REPL turn and every approval resume.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anyio
import pytest

from initrunner.agent.executor_retry import build_retrying_async_client


class _KeepAlive(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep connections open so the client pools them

    def do_GET(self):
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


@pytest.fixture
def server_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _KeepAlive)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
    server.server_close()


# openai gets the httpx2 client, groq the legacy httpx one.
@pytest.mark.parametrize("provider", ["openai", "groq"])
def test_one_client_across_event_loops(server_url, provider):
    client = build_retrying_async_client(provider)

    async def fetch() -> int:
        response = await client.get(server_url)
        return response.status_code

    # Each anyio.run is a new event loop, the way run_sync runs each agent run.
    assert anyio.run(fetch) == 200
    assert anyio.run(fetch) == 200
    assert anyio.run(fetch) == 200


@pytest.mark.parametrize("provider", ["openai", "groq"])
def test_connections_are_pooled_within_a_loop(server_url, provider):
    client = build_retrying_async_client(provider)

    async def fetch_twice() -> list[int]:
        return [(await client.get(server_url)).status_code for _ in range(2)]

    assert anyio.run(fetch_twice) == [200, 200]
