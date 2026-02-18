"""Smoke tests for daemon runner, webhook trigger HTTP, and rate limiter."""

from __future__ import annotations

import hashlib
import hmac
import signal
import socket
import threading
import time
from unittest.mock import MagicMock, Mock, patch

import httpx

from initrunner.agent.executor import RunResult
from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
from initrunner.agent.schema.memory import MemoryConfig
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.agent.schema.triggers import WebhookTriggerConfig
from initrunner.server.rate_limiter import TokenBucketRateLimiter
from initrunner.triggers.base import TriggerEvent
from initrunner.triggers.dispatcher import TriggerDispatcher
from initrunner.triggers.webhook import WebhookTrigger

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_free_port() -> int:
    """Return a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    """Block until a TCP port is accepting connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError(f"Port {port} not ready within {timeout}s")


def _sign_body(body: bytes, secret: str) -> dict[str, str]:
    """Compute X-Hub-Signature-256 header dict for the given body and secret."""
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"x-hub-signature-256": sig}


def _make_role(
    *,
    port: int = 8080,
    path: str = "/webhook",
    secret: str | None = None,
    rate_limit_rpm: int = 60,
    triggers: list | None = None,
    memory: MemoryConfig | None = None,
) -> RoleDefinition:
    """Build a minimal RoleDefinition with a webhook trigger."""
    if triggers is None:
        triggers = [
            WebhookTriggerConfig(
                port=port,
                path=path,
                secret=secret,
                rate_limit_rpm=rate_limit_rpm,
            )
        ]
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name="test-agent"),
        spec=AgentSpec(
            role="Test agent",
            model=ModelConfig(provider="openai", name="gpt-4o-mini"),
            triggers=triggers,
            memory=memory,
        ),
    )


# ---------------------------------------------------------------------------
# TestWebhookTriggerHTTP — real HTTP requests to a live webhook server
# ---------------------------------------------------------------------------


class TestWebhookTriggerHTTP:
    """Real HTTP requests against a live WebhookTrigger."""

    def test_post_fires_callback(self):
        port = _get_free_port()
        events: list[TriggerEvent] = []
        config = WebhookTriggerConfig(port=port)
        trigger = WebhookTrigger(config, events.append)
        trigger.start()
        try:
            _wait_for_port(port)
            body = b"hello world"
            assert config.secret is not None
            resp = httpx.post(
                f"http://127.0.0.1:{port}/webhook",
                content=body,
                headers=_sign_body(body, config.secret),
            )
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}
            assert len(events) == 1
            assert events[0].prompt == "hello world"
            assert events[0].trigger_type == "webhook"
        finally:
            trigger.stop()

    def test_wrong_method_returns_405(self):
        port = _get_free_port()
        config = WebhookTriggerConfig(port=port)
        trigger = WebhookTrigger(config, lambda e: None)
        trigger.start()
        try:
            _wait_for_port(port)
            resp = httpx.get(f"http://127.0.0.1:{port}/webhook")
            assert resp.status_code == 405
        finally:
            trigger.stop()

    def test_hmac_valid_signature(self):
        port = _get_free_port()
        secret = "test-secret"
        events: list[TriggerEvent] = []
        config = WebhookTriggerConfig(port=port, secret=secret)
        trigger = WebhookTrigger(config, events.append)
        trigger.start()
        try:
            _wait_for_port(port)
            body = b"signed payload"
            sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            resp = httpx.post(
                f"http://127.0.0.1:{port}/webhook",
                content=body,
                headers={"x-hub-signature-256": sig},
            )
            assert resp.status_code == 200
            assert len(events) == 1
        finally:
            trigger.stop()

    def test_hmac_invalid_signature(self):
        port = _get_free_port()
        config = WebhookTriggerConfig(port=port, secret="real-secret")
        trigger = WebhookTrigger(config, lambda e: None)
        trigger.start()
        try:
            _wait_for_port(port)
            resp = httpx.post(
                f"http://127.0.0.1:{port}/webhook",
                content=b"payload",
                headers={"x-hub-signature-256": "sha256=wrong"},
            )
            assert resp.status_code == 403
        finally:
            trigger.stop()

    def test_hmac_missing_signature(self):
        port = _get_free_port()
        config = WebhookTriggerConfig(port=port, secret="some-secret")
        trigger = WebhookTrigger(config, lambda e: None)
        trigger.start()
        try:
            _wait_for_port(port)
            resp = httpx.post(
                f"http://127.0.0.1:{port}/webhook",
                content=b"payload",
            )
            assert resp.status_code == 403
        finally:
            trigger.stop()

    def test_rate_limit_returns_429(self):
        port = _get_free_port()
        config = WebhookTriggerConfig(port=port, rate_limit_rpm=1)
        trigger = WebhookTrigger(config, lambda e: None)
        trigger.start()
        try:
            _wait_for_port(port)
            body = b"first"
            assert config.secret is not None
            r1 = httpx.post(
                f"http://127.0.0.1:{port}/webhook",
                content=body,
                headers=_sign_body(body, config.secret),
            )
            assert r1.status_code == 200
            r2 = httpx.post(f"http://127.0.0.1:{port}/webhook", content="second")
            assert r2.status_code == 429
        finally:
            trigger.stop()

    def test_custom_path(self):
        port = _get_free_port()
        events: list[TriggerEvent] = []
        config = WebhookTriggerConfig(port=port, path="/custom/hook")
        trigger = WebhookTrigger(config, events.append)
        trigger.start()
        try:
            _wait_for_port(port)
            body = b"routed"
            assert config.secret is not None
            resp = httpx.post(
                f"http://127.0.0.1:{port}/custom/hook",
                content=body,
                headers=_sign_body(body, config.secret),
            )
            assert resp.status_code == 200
            assert len(events) == 1
            assert events[0].metadata["path"] == "/custom/hook"
        finally:
            trigger.stop()

    def test_clean_shutdown(self):
        port = _get_free_port()
        config = WebhookTriggerConfig(port=port)
        trigger = WebhookTrigger(config, lambda e: None)
        trigger.start()
        _wait_for_port(port)
        body = b"before stop"
        assert config.secret is not None
        httpx.post(
            f"http://127.0.0.1:{port}/webhook",
            content=body,
            headers=_sign_body(body, config.secret),
        )
        trigger.stop()
        assert trigger._thread is not None
        assert not trigger._thread.is_alive()


# ---------------------------------------------------------------------------
# TestTokenBucketRateLimiter — unit tests for the rate limiter
# ---------------------------------------------------------------------------


class TestTokenBucketRateLimiter:
    """Unit tests for the token-bucket rate limiter."""

    def test_allows_within_burst(self):
        limiter = TokenBucketRateLimiter(rate=1.0, burst=3)
        assert all(limiter.allow() for _ in range(3))

    def test_rejects_over_burst(self):
        limiter = TokenBucketRateLimiter(rate=0.01, burst=1)
        assert limiter.allow() is True
        assert limiter.allow() is False

    def test_refills_over_time(self):
        limiter = TokenBucketRateLimiter(rate=20.0, burst=1)
        assert limiter.allow() is True
        assert limiter.allow() is False
        time.sleep(0.15)
        assert limiter.allow() is True


# ---------------------------------------------------------------------------
# TestDaemonRunner — integration tests for run_daemon()
# ---------------------------------------------------------------------------


def _run_daemon_in_thread(
    role: RoleDefinition,
    **kwargs,
) -> tuple[threading.Thread, list]:
    """Start run_daemon in a background thread with signal.signal mocked.

    Returns (thread, captured_signal_handlers).
    """
    from initrunner.runner import run_daemon

    captured_handlers: list = []

    def mock_signal(signum, handler):
        captured_handlers.append(handler)

    with patch("initrunner._signal.signal.signal", side_effect=mock_signal):
        t = threading.Thread(
            target=run_daemon,
            args=(Mock(), role),
            kwargs=kwargs,
            daemon=True,
        )
        t.start()

    return t, captured_handlers


class TestDaemonRunner:
    """Integration tests for run_daemon()."""

    def test_daemon_exits_on_no_triggers(self):
        from initrunner.runner import run_daemon

        role = _make_role(triggers=[])
        # Should return immediately without crashing
        run_daemon(Mock(), role)

    def test_daemon_runs_agent_on_trigger(self):
        port = _get_free_port()
        role = _make_role(port=port)
        trigger_cfg = role.spec.triggers[0]
        assert isinstance(trigger_cfg, WebhookTriggerConfig)
        secret = trigger_cfg.secret
        assert secret is not None

        execute_called = threading.Event()
        mock_result = RunResult(run_id="test-run", output="ok", success=True)

        def mock_execute(*args, **kwargs):
            execute_called.set()
            return mock_result, []

        captured_handlers: list = []

        def mock_signal(signum, handler):
            captured_handlers.append(handler)

        with (
            patch("initrunner.runner.daemon.execute_run", side_effect=mock_execute),
            patch("initrunner._signal.signal.signal", side_effect=mock_signal),
        ):
            from initrunner.runner import run_daemon

            t = threading.Thread(target=run_daemon, args=(Mock(), role), daemon=True)
            t.start()

            try:
                _wait_for_port(port)
                body = b"fire!"
                httpx.post(
                    f"http://127.0.0.1:{port}/webhook",
                    content=body,
                    headers=_sign_body(body, secret),
                )
                assert execute_called.wait(timeout=5), "execute_run was not called"
            finally:
                if captured_handlers:
                    captured_handlers[0](signal.SIGINT, None)
                t.join(timeout=5)

    def test_daemon_dispatches_to_sinks(self):
        port = _get_free_port()
        role = _make_role(port=port)
        trigger_cfg = role.spec.triggers[0]
        assert isinstance(trigger_cfg, WebhookTriggerConfig)
        secret = trigger_cfg.secret
        assert secret is not None

        execute_called = threading.Event()
        mock_result = RunResult(run_id="test-run", output="ok", success=True)

        def mock_execute(*args, **kwargs):
            execute_called.set()
            return mock_result, []

        sink_dispatcher = MagicMock()
        captured_handlers: list = []

        def mock_signal(signum, handler):
            captured_handlers.append(handler)

        with (
            patch("initrunner.runner.daemon.execute_run", side_effect=mock_execute),
            patch("initrunner._signal.signal.signal", side_effect=mock_signal),
        ):
            from initrunner.runner import run_daemon

            t = threading.Thread(
                target=run_daemon,
                args=(Mock(), role),
                kwargs={"sink_dispatcher": sink_dispatcher},
                daemon=True,
            )
            t.start()

            try:
                _wait_for_port(port)
                body = b"dispatch me"
                httpx.post(
                    f"http://127.0.0.1:{port}/webhook",
                    content=body,
                    headers=_sign_body(body, secret),
                )
                assert execute_called.wait(timeout=5)
                # The callback runs synchronously in the request handler,
                # so dispatch has been called by the time we get the response.
                sink_dispatcher.dispatch.assert_called_once()
            finally:
                if captured_handlers:
                    captured_handlers[0](signal.SIGINT, None)
                t.join(timeout=5)

    def test_daemon_prunes_memory(self):
        port = _get_free_port()
        role = _make_role(port=port, memory=MemoryConfig())
        trigger_cfg = role.spec.triggers[0]
        assert isinstance(trigger_cfg, WebhookTriggerConfig)
        secret = trigger_cfg.secret
        assert secret is not None

        execute_called = threading.Event()
        mock_result = RunResult(run_id="test-run", output="ok", success=True)

        def mock_execute(*args, **kwargs):
            execute_called.set()
            return mock_result, []

        memory_store = MagicMock()
        captured_handlers: list = []

        def mock_signal(signum, handler):
            captured_handlers.append(handler)

        with (
            patch("initrunner.runner.daemon.execute_run", side_effect=mock_execute),
            patch("initrunner._signal.signal.signal", side_effect=mock_signal),
        ):
            from initrunner.runner import run_daemon

            t = threading.Thread(
                target=run_daemon,
                args=(Mock(), role),
                kwargs={"memory_store": memory_store},
                daemon=True,
            )
            t.start()

            try:
                _wait_for_port(port)
                body = b"prune me"
                httpx.post(
                    f"http://127.0.0.1:{port}/webhook",
                    content=body,
                    headers=_sign_body(body, secret),
                )
                assert execute_called.wait(timeout=5)
                # Callback is synchronous — prune_sessions runs before response.
                assert role.spec.memory is not None
                memory_store.prune_sessions.assert_called_once_with(
                    "test-agent", role.spec.memory.max_sessions
                )
            finally:
                if captured_handlers:
                    captured_handlers[0](signal.SIGINT, None)
                t.join(timeout=5)


# ---------------------------------------------------------------------------
# TestTriggerDispatcherWebhook — dispatcher + webhook integration
# ---------------------------------------------------------------------------


class TestTriggerDispatcherWebhook:
    """Dispatcher integration with webhook triggers."""

    def test_dispatcher_builds_webhook(self):
        port = _get_free_port()
        config = WebhookTriggerConfig(port=port)
        dispatcher = TriggerDispatcher([config], lambda e: None)
        assert dispatcher.count == 1

    def test_dispatcher_webhook_receives_http(self):
        port = _get_free_port()
        config = WebhookTriggerConfig(port=port)
        events: list[TriggerEvent] = []
        dispatcher = TriggerDispatcher([config], events.append)
        with dispatcher:
            _wait_for_port(port)
            body = b"dispatch test"
            assert config.secret is not None
            resp = httpx.post(
                f"http://127.0.0.1:{port}/webhook",
                content=body,
                headers=_sign_body(body, config.secret),
            )
            assert resp.status_code == 200
        assert len(events) == 1
        assert events[0].prompt == "dispatch test"


# ---------------------------------------------------------------------------
# TestWebhookSecurityEnhancements — auto-generated secrets & body size limits
# ---------------------------------------------------------------------------


class TestWebhookSecurityEnhancements:
    """Tests for auto-generated webhook secrets and body size limits."""

    def test_auto_generated_secret(self):
        config = WebhookTriggerConfig()
        assert config.secret is not None
        assert isinstance(config.secret, str)
        assert len(config.secret) > 0

    def test_auto_generated_secret_is_unique(self):
        c1 = WebhookTriggerConfig()
        c2 = WebhookTriggerConfig()
        assert c1.secret != c2.secret

    def test_user_provided_secret_preserved(self):
        config = WebhookTriggerConfig(secret="my-secret")
        assert config.secret == "my-secret"

    def test_body_too_large_rejected(self):
        port = _get_free_port()
        config = WebhookTriggerConfig(port=port)
        trigger = WebhookTrigger(config, lambda e: None)
        trigger.start()
        try:
            _wait_for_port(port)
            body = b"x" * (1_048_576 + 1)
            resp = httpx.post(f"http://127.0.0.1:{port}/webhook", content=body)
            assert resp.status_code == 413
            assert resp.json() == {"error": "payload too large"}
        finally:
            trigger.stop()

    def test_secret_not_logged_at_info_level(self):
        port = _get_free_port()
        config = WebhookTriggerConfig(port=port)
        trigger = WebhookTrigger(config, lambda e: None)
        with patch("initrunner.triggers.webhook.logger") as mock_logger:
            trigger.start()
            try:
                _wait_for_port(port)
            finally:
                trigger.stop()
        # Secret value must never appear in log calls
        assert config.secret is not None
        for call in mock_logger.info.call_args_list:
            args = call[0] if call[0] else ()
            for a in args:
                assert config.secret not in str(a), "Secret value leaked in info log"
