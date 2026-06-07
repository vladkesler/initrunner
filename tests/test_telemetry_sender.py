"""Zero-dependency sender: endpoint/shape, never-raise, bounded flush, debug mode."""

from __future__ import annotations

import json
import time
import urllib.request

import pytest

from initrunner.telemetry import _sender


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return b""


@pytest.fixture(autouse=True)
def _clear_pending(monkeypatch):
    monkeypatch.delenv("INITRUNNER_TELEMETRY_DEBUG", raising=False)
    monkeypatch.delenv("INITRUNNER_POSTHOG_HOST", raising=False)
    monkeypatch.delenv("INITRUNNER_POSTHOG_KEY", raising=False)
    _sender._pending.clear()
    yield
    _sender._pending.clear()


def test_flush_posts_batch_with_expected_shape(monkeypatch):
    captured: dict = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["data"] = request.data
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    _sender.enqueue(
        "cli_command",
        "abc123",
        {"$process_person_profile": False, "command": "run"},
    )
    _sender.flush()

    assert captured["url"].endswith("/batch/")
    assert captured["timeout"] == _sender._SOCKET_TIMEOUT
    body = json.loads(captured["data"])
    assert body["api_key"]
    event = body["batch"][0]
    assert event["event"] == "cli_command"
    assert event["distinct_id"] == "abc123"
    assert event["properties"]["$process_person_profile"] is False


def test_never_raises_when_urlopen_fails(monkeypatch):
    def boom(request, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    _sender.enqueue("cli_command", "abc", {})
    _sender.flush()  # must not raise


def test_flush_bounded_when_network_hangs(monkeypatch):
    def hang(request, timeout=None):
        time.sleep(10)

    monkeypatch.setattr(urllib.request, "urlopen", hang)
    monkeypatch.setattr(_sender, "_JOIN_TIMEOUT", 0.2)
    _sender.enqueue("cli_command", "abc", {})

    start = time.monotonic()
    _sender.flush()
    elapsed = time.monotonic() - start
    assert elapsed < 2.0  # bounded by the join timeout, not the 10s hang


def test_flush_noop_when_empty(monkeypatch):
    def fail(request, timeout=None):
        raise AssertionError("should not POST with no pending events")

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    _sender.flush()  # nothing enqueued


def test_debug_mode_prints_and_skips_network(monkeypatch, capsys):
    def fail(request, timeout=None):
        raise AssertionError("debug mode must not hit the network")

    monkeypatch.setenv("INITRUNNER_TELEMETRY_DEBUG", "1")
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    _sender.enqueue("cli_command", "abc", {"command": "run"})
    _sender.flush()

    err = capsys.readouterr().err
    assert "[initrunner telemetry]" in err
    assert "cli_command" in err
