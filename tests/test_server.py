"""Tests for the OpenAI-compatible API server."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from initrunner.agent.executor import RunResult
from initrunner.agent.schema import (
    AgentSpec,
    ApiVersion,
    Guardrails,
    Kind,
    Metadata,
    ModelConfig,
    RateLimitConfig,
    RoleDefinition,
    SecurityPolicy,
    ServerConfig,
)
from initrunner.cli.main import app as cli_app
from initrunner.server.conversations import ConversationStore
from initrunner.server.convert import openai_messages_to_pydantic
from initrunner.server.models import ChatMessage

cli_runner = CliRunner()


def _make_role(name: str = "test-agent") -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name=name),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-4o-mini"),
            guardrails=Guardrails(),
        ),
    )


# ---- convert.py tests ----


class TestOpenaiMessagesToPydantic:
    def test_simple_user_message(self):
        messages = [ChatMessage(role="user", content="Hello")]
        prompt, history = openai_messages_to_pydantic(messages)
        assert prompt == "Hello"
        assert history is None

    def test_multi_turn(self):
        messages = [
            ChatMessage(role="user", content="Hi"),
            ChatMessage(role="assistant", content="Hello!"),
            ChatMessage(role="user", content="How are you?"),
        ]
        prompt, history = openai_messages_to_pydantic(messages)
        assert prompt == "How are you?"
        assert history is not None
        assert len(history) == 2  # request + response

    def test_system_prepend_no_history(self):
        messages = [
            ChatMessage(role="system", content="Be helpful"),
            ChatMessage(role="user", content="Hello"),
        ]
        prompt, history = openai_messages_to_pydantic(messages)
        assert "Be helpful" in prompt
        assert "Hello" in prompt
        assert history is None

    def test_system_prepend_with_history(self):
        messages = [
            ChatMessage(role="system", content="Be helpful"),
            ChatMessage(role="user", content="Hi"),
            ChatMessage(role="assistant", content="Hello!"),
            ChatMessage(role="user", content="Follow up"),
        ]
        prompt, history = openai_messages_to_pydantic(messages)
        assert prompt == "Follow up"
        assert history is not None
        # The system content gets prepended to the first user message in history
        from pydantic_ai.messages import ModelRequest

        first_req = history[0]
        assert isinstance(first_req, ModelRequest)
        assert "Be helpful" in first_req.parts[0].content  # type: ignore[union-attr]

    def test_empty_messages_raises(self):
        with pytest.raises(ValueError, match="empty"):
            openai_messages_to_pydantic([])

    def test_no_user_message_raises(self):
        messages = [ChatMessage(role="assistant", content="Hi")]
        with pytest.raises(ValueError, match="no user message"):
            openai_messages_to_pydantic(messages)

    def test_backwards_scan_finds_last_user(self):
        messages = [
            ChatMessage(role="user", content="First"),
            ChatMessage(role="assistant", content="Response"),
            ChatMessage(role="user", content="Second"),
            ChatMessage(role="assistant", content="Response 2"),
            ChatMessage(role="user", content="Third"),
        ]
        prompt, history = openai_messages_to_pydantic(messages)
        assert prompt == "Third"
        assert history is not None
        assert len(history) == 4  # 2 requests + 2 responses

    def test_tool_messages_skipped(self):
        messages = [
            ChatMessage(role="user", content="Hi"),
            ChatMessage(role="assistant", content="Let me check"),
            ChatMessage(role="tool", content="tool output"),
            ChatMessage(role="user", content="Thanks"),
        ]
        prompt, history = openai_messages_to_pydantic(messages)
        assert prompt == "Thanks"
        assert history is not None
        # tool message should not appear in history
        assert len(history) == 2  # request + response only


# ---- conversations.py tests ----


class TestConversationStore:
    def test_save_and_get(self):
        store = ConversationStore()
        store.save("conv-1", [{"fake": "message"}])
        result = store.get("conv-1")
        assert result is not None
        assert len(result) == 1

    def test_get_nonexistent(self):
        store = ConversationStore()
        assert store.get("nonexistent") is None

    def test_ttl_expiry(self):
        store = ConversationStore(ttl_seconds=0.01)
        store.save("conv-1", [{"fake": "message"}])
        time.sleep(0.05)
        assert store.get("conv-1") is None

    def test_clear(self):
        store = ConversationStore()
        store.save("conv-1", [{"fake": "message"}])
        store.save("conv-2", [{"fake": "message"}])
        store.clear()
        assert store.get("conv-1") is None
        assert store.get("conv-2") is None

    def test_access_refreshes_ttl(self):
        store = ConversationStore(ttl_seconds=0.1)
        store.save("conv-1", [{"fake": "message"}])
        time.sleep(0.05)
        # Access should refresh TTL
        result = store.get("conv-1")
        assert result is not None
        time.sleep(0.07)
        # Should still be alive because we accessed it
        result = store.get("conv-1")
        assert result is not None


# ---- app.py endpoint tests ----


def _create_test_client(api_key: str | None = None) -> TestClient:
    """Create a TestClient with a mocked agent."""
    from initrunner.server.app import create_app

    role = _make_role()
    agent = MagicMock()
    app = create_app(agent, role, api_key=api_key)
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self):
        client = _create_test_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestModelsEndpoint:
    def test_list_models(self):
        client = _create_test_client()
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == "test-agent"
        assert data["data"][0]["owned_by"] == "initrunner"


class TestChatCompletionsEndpoint:
    @patch("initrunner.server.app.execute_run")
    def test_non_streaming(self, mock_execute):
        mock_execute.return_value = (
            RunResult(
                run_id="test-123",
                output="Hello there!",
                tokens_in=10,
                tokens_out=5,
                total_tokens=15,
                success=True,
            ),
            [],
        )

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-agent",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Hello there!"
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["usage"]["prompt_tokens"] == 10
        assert data["usage"]["completion_tokens"] == 5
        assert "X-Conversation-Id" in resp.headers

    @patch("initrunner.server.app.execute_run")
    def test_non_streaming_error(self, mock_execute):
        mock_execute.return_value = (
            RunResult(run_id="test-123", output="", success=False, error="model error"),
            [],
        )

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-agent",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )
        assert resp.status_code == 500
        # Error details are sanitized — no internal info leaked
        assert resp.json()["error"]["message"] == "Internal server error"

    def test_invalid_json(self):
        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    def test_empty_messages(self):
        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "test-agent", "messages": []},
        )
        assert resp.status_code == 400
        assert "empty" in resp.json()["error"]["message"]

    def test_no_user_message(self):
        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-agent",
                "messages": [{"role": "assistant", "content": "Hi"}],
            },
        )
        assert resp.status_code == 400
        assert "no user message" in resp.json()["error"]["message"]

    @patch("initrunner.server.app.execute_run")
    def test_conversation_id_returned(self, mock_execute):
        mock_execute.return_value = (
            RunResult(run_id="test", output="Hi", success=True),
            [],
        )
        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp.status_code == 200
        conv_id = resp.headers.get("X-Conversation-Id")
        assert conv_id is not None
        assert len(conv_id) > 0

    @patch("initrunner.server.app.execute_run")
    def test_non_streaming_excludes_null_fields(self, mock_execute):
        mock_execute.return_value = (
            RunResult(
                run_id="test",
                output="Hi",
                success=True,
                tokens_in=5,
                tokens_out=3,
                total_tokens=8,
            ),
            [],
        )
        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp.status_code == 200
        raw = resp.text
        assert "null" not in raw

    @patch("initrunner.server.app.execute_run")
    def test_conversation_tracking_with_header(self, mock_execute):
        mock_execute.return_value = (
            RunResult(run_id="test", output="First reply", success=True),
            [{"mock": "messages"}],
        )

        client = _create_test_client()

        # First request — no conversation ID
        resp1 = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp1.status_code == 200
        conv_id = resp1.headers["X-Conversation-Id"]

        # Second request — with conversation ID
        mock_execute.return_value = (
            RunResult(run_id="test2", output="Second reply", success=True),
            [{"mock": "messages2"}],
        )
        resp2 = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Follow up"}]},
            headers={"X-Conversation-Id": conv_id},
        )
        assert resp2.status_code == 200
        assert resp2.headers["X-Conversation-Id"] == conv_id
        # Server-side history path: execute_run should have received server-side history
        call_kwargs = mock_execute.call_args
        assert call_kwargs.kwargs["message_history"] is not None


class TestAuthMiddleware:
    def test_no_auth_required(self):
        client = _create_test_client(api_key=None)
        resp = client.get("/v1/models")
        assert resp.status_code == 200

    def test_auth_required_missing_key(self):
        client = _create_test_client(api_key="secret-key")
        resp = client.get("/v1/models")
        assert resp.status_code == 401

    def test_auth_required_wrong_key(self):
        client = _create_test_client(api_key="secret-key")
        resp = client.get(
            "/v1/models",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401

    def test_auth_required_correct_key(self):
        client = _create_test_client(api_key="secret-key")
        resp = client.get(
            "/v1/models",
            headers={"Authorization": "Bearer secret-key"},
        )
        assert resp.status_code == 200

    def test_health_no_auth_needed(self):
        client = _create_test_client(api_key="secret-key")
        resp = client.get("/health")
        assert resp.status_code == 200


# ---- Security tests ----


def _make_security_role(**security_kwargs) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-4o-mini"),
            guardrails=Guardrails(),
            security=SecurityPolicy(**security_kwargs),
        ),
    )


def _create_security_client(role: RoleDefinition, api_key: str | None = None) -> TestClient:
    from initrunner.server.app import create_app

    agent = MagicMock()
    app = create_app(agent, role, api_key=api_key)
    return TestClient(app)


class TestTimingSafeAuth:
    def test_timing_safe_auth_correct(self):
        client = _create_test_client(api_key="secret-key")
        resp = client.get(
            "/v1/models",
            headers={"Authorization": "Bearer secret-key"},
        )
        assert resp.status_code == 200

    def test_timing_safe_auth_wrong(self):
        client = _create_test_client(api_key="secret-key")
        resp = client.get(
            "/v1/models",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401


class TestCORSLockdown:
    def test_no_cors_headers_by_default(self):
        role = _make_security_role()
        client = _create_security_client(role)
        resp = client.get("/health")
        assert "access-control-allow-origin" not in resp.headers

    def test_explicit_origins(self):
        role = _make_security_role(server=ServerConfig(cors_origins=["https://example.com"]))
        client = _create_security_client(role)
        resp = client.options(
            "/v1/chat/completions",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "https://example.com"

    def test_cors_exposes_conversation_id_header(self):
        role = _make_security_role(server=ServerConfig(cors_origins=["https://example.com"]))
        client = _create_security_client(role)
        # expose_headers is sent on actual responses, not preflight OPTIONS
        resp = client.get(
            "/health",
            headers={"Origin": "https://example.com"},
        )
        expose = resp.headers.get("access-control-expose-headers", "")
        assert "X-Conversation-Id" in expose


class TestHTTPSEnforcement:
    def test_https_enforcement_blocks_http(self):
        role = _make_security_role(server=ServerConfig(require_https=True))
        client = _create_security_client(role)
        resp = client.get("/v1/models")
        assert resp.status_code == 403

    def test_https_enforcement_allows_https(self):
        role = _make_security_role(server=ServerConfig(require_https=True))
        client = _create_security_client(role)
        resp = client.get("/v1/models", headers={"X-Forwarded-Proto": "https"})
        assert resp.status_code == 200

    def test_health_exempt_from_https(self):
        role = _make_security_role(server=ServerConfig(require_https=True))
        client = _create_security_client(role)
        resp = client.get("/health")
        assert resp.status_code == 200


class TestRequestBodyLimit:
    def test_body_too_large_returns_413(self):
        role = _make_security_role(server=ServerConfig(max_request_body_bytes=100))
        client = _create_security_client(role)
        resp = client.post(
            "/v1/chat/completions",
            content=b"x" * 200,
            headers={"content-type": "application/json", "content-length": "200"},
        )
        assert resp.status_code == 413


class TestRateLimiting:
    def test_rate_limit_returns_429_after_burst(self):
        role = _make_security_role(
            rate_limit=RateLimitConfig(requests_per_minute=600, burst_size=2)
        )
        client = _create_security_client(role)
        # Exhaust burst
        client.get("/v1/models")
        client.get("/v1/models")
        resp = client.get("/v1/models")
        assert resp.status_code == 429


class TestErrorSanitization:
    @patch("initrunner.server.app.execute_run")
    def test_exception_details_not_leaked(self, mock_execute):
        mock_execute.side_effect = RuntimeError("secret database password: hunter2")
        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp.status_code == 500
        assert "hunter2" not in resp.json()["error"]["message"]
        assert resp.json()["error"]["message"] == "Internal server error"


class TestConversationCap:
    def test_max_conversations_evicts_oldest(self):
        store = ConversationStore(max_conversations=2)
        store.save("conv-1", [{"fake": "msg1"}])
        store.save("conv-2", [{"fake": "msg2"}])
        store.save("conv-3", [{"fake": "msg3"}])
        # conv-1 should be evicted
        assert store.get("conv-1") is None
        assert store.get("conv-2") is not None
        assert store.get("conv-3") is not None


# ---- CLI tests ----


def _stream_body(content: str = "Hi") -> dict:
    """Build a streaming chat completion request body."""
    return {
        "model": "test-agent",
        "messages": [{"role": "user", "content": content}],
        "stream": True,
    }


class TestStreamingEndpoint:
    @patch("initrunner.server.app.execute_run_stream")
    @patch("initrunner.server.app.validate_input")
    def test_streaming_uses_executor(self, mock_validate, mock_stream):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(valid=True)
        mock_stream.return_value = (
            RunResult(
                run_id="s-1",
                output="Hi",
                tokens_in=5,
                tokens_out=3,
                total_tokens=8,
                success=True,
            ),
            [],
        )

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json=_stream_body(),
        )
        assert resp.status_code == 200
        mock_stream.assert_called_once()
        call_kwargs = mock_stream.call_args
        assert call_kwargs.kwargs.get("on_token") is not None

    @patch("initrunner.server.app.validate_input")
    def test_streaming_blocked_input(self, mock_validate):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(
            valid=False,
            reason="Blocked by policy",
        )

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json=_stream_body("bad"),
        )
        # Should get HTTP 400, NOT a 200 SSE stream
        assert resp.status_code == 400
        assert "Blocked by policy" in resp.json()["error"]["message"]

    @patch("initrunner.server.app.execute_run_stream")
    @patch("initrunner.server.app.validate_input")
    def test_streaming_passes_audit_logger(
        self,
        mock_validate,
        mock_stream,
    ):
        from initrunner.agent.policies import ValidationResult
        from initrunner.server.app import create_app

        mock_validate.return_value = ValidationResult(valid=True)
        mock_stream.return_value = (
            RunResult(run_id="s-2", output="Ok", success=True),
            [],
        )

        role = _make_role()
        agent = MagicMock()
        audit = MagicMock()
        app = create_app(agent, role, audit_logger=audit)
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json=_stream_body(),
        )
        assert resp.status_code == 200
        call_kwargs = mock_stream.call_args
        assert call_kwargs.kwargs["audit_logger"] is audit

    @patch("initrunner.server.app.execute_run_stream")
    @patch("initrunner.server.app.validate_input")
    def test_streaming_returns_conversation_id(
        self,
        mock_validate,
        mock_stream,
    ):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(valid=True)
        mock_stream.return_value = (
            RunResult(run_id="s-3", output="Hi", success=True),
            [],
        )

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json=_stream_body(),
        )
        assert resp.status_code == 200
        assert "X-Conversation-Id" in resp.headers

    @patch("initrunner.server.app.execute_run_stream")
    @patch("initrunner.server.app.validate_input")
    def test_streaming_openai_sse_format(
        self,
        mock_validate,
        mock_stream,
    ):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(valid=True)

        def fake_stream(agent, role, prompt, *, on_token=None, **kw):
            if on_token:
                on_token("Hello")
                on_token(" world")
            return (
                RunResult(
                    run_id="s-4",
                    output="Hello world",
                    tokens_in=10,
                    tokens_out=5,
                    total_tokens=15,
                    success=True,
                ),
                [],
            )

        mock_stream.side_effect = fake_stream

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json=_stream_body(),
        )
        assert resp.status_code == 200

        lines = resp.text.strip().split("\n\n")
        chunks = []
        for line in lines:
            if line.startswith("data: ") and line != "data: [DONE]":
                import json as _json

                chunks.append(_json.loads(line[len("data: ") :]))
            elif line == "data: [DONE]":
                chunks.append("[DONE]")

        assert len(chunks) >= 4  # role + content(s) + finish + DONE
        # First chunk: role
        assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
        # Last data chunk before [DONE]: finish with usage
        finish_chunk = chunks[-2]
        assert finish_chunk["choices"][0]["finish_reason"] == "stop"
        assert finish_chunk["usage"]["prompt_tokens"] == 10
        assert finish_chunk["usage"]["completion_tokens"] == 5
        assert finish_chunk["usage"]["total_tokens"] == 15
        assert chunks[-1] == "[DONE]"

    @patch("initrunner.server.app.execute_run_stream")
    @patch("initrunner.server.app.validate_input")
    def test_streaming_exception_handling(
        self,
        mock_validate,
        mock_stream,
    ):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(valid=True)
        mock_stream.side_effect = RuntimeError("secret crash details")

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json=_stream_body(),
        )
        assert resp.status_code == 200  # SSE stream starts before error
        assert "Internal server error" in resp.text
        assert "secret crash details" not in resp.text
        assert "[DONE]" in resp.text

    @patch("initrunner.server.app.execute_run_stream")
    @patch("initrunner.server.app.validate_input")
    def test_streaming_chunks_exclude_null_fields(self, mock_validate, mock_stream):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(valid=True)

        def fake_stream(agent, role, prompt, *, on_token=None, **kw):
            if on_token:
                on_token("Hello")
            return (
                RunResult(
                    run_id="s-null",
                    output="Hello",
                    success=True,
                    tokens_in=5,
                    tokens_out=3,
                    total_tokens=8,
                ),
                [],
            )

        mock_stream.side_effect = fake_stream

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json=_stream_body(),
        )
        assert resp.status_code == 200
        for line in resp.text.strip().split("\n\n"):
            if line.startswith("data: ") and line != "data: [DONE]":
                assert "null" not in line

    @patch("initrunner.server.app.execute_run_stream")
    @patch("initrunner.server.app.validate_input")
    def test_streaming_multi_turn_with_conversation_id(self, mock_validate, mock_stream):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(valid=True)

        call_count = 0

        def fake_stream(agent, role, prompt, *, on_token=None, message_history=None, **kw):
            nonlocal call_count
            call_count += 1
            if on_token:
                on_token(f"Reply {call_count}")
            return (
                RunResult(
                    run_id=f"mt-{call_count}",
                    output=f"Reply {call_count}",
                    success=True,
                ),
                [{"mock": f"history-{call_count}"}],
            )

        mock_stream.side_effect = fake_stream

        client = _create_test_client()

        # First streaming request
        resp1 = client.post(
            "/v1/chat/completions",
            json=_stream_body("Hello"),
        )
        assert resp1.status_code == 200
        conv_id = resp1.headers["X-Conversation-Id"]

        # Second streaming request with conversation ID
        resp2 = client.post(
            "/v1/chat/completions",
            json=_stream_body("Follow up"),
            headers={"X-Conversation-Id": conv_id},
        )
        assert resp2.status_code == 200
        assert resp2.headers["X-Conversation-Id"] == conv_id
        # Second call should have received server-side history
        second_call_kwargs = mock_stream.call_args
        assert second_call_kwargs.kwargs["message_history"] is not None


class TestCORSCLIOverride:
    def test_cors_origins_from_cli(self):
        from initrunner.server.app import create_app

        role = _make_role()
        agent = MagicMock()
        app = create_app(agent, role, cors_origins=["https://myapp.com"])
        client = TestClient(app)

        resp = client.options(
            "/v1/chat/completions",
            headers={
                "Origin": "https://myapp.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "https://myapp.com"

    def test_cors_cli_merged_with_role_config(self):
        from initrunner.server.app import create_app

        role = _make_security_role(server=ServerConfig(cors_origins=["https://role-origin.com"]))
        agent = MagicMock()
        app = create_app(agent, role, cors_origins=["https://cli-origin.com"])
        client = TestClient(app)

        # Role origin should work
        resp1 = client.options(
            "/v1/chat/completions",
            headers={
                "Origin": "https://role-origin.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp1.headers.get("access-control-allow-origin") == "https://role-origin.com"

        # CLI origin should also work
        resp2 = client.options(
            "/v1/chat/completions",
            headers={
                "Origin": "https://cli-origin.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp2.headers.get("access-control-allow-origin") == "https://cli-origin.com"

    def test_cors_no_cli_no_role_means_no_headers(self):
        from initrunner.server.app import create_app

        role = _make_role()
        agent = MagicMock()
        app = create_app(agent, role)
        client = TestClient(app)

        resp = client.options(
            "/v1/chat/completions",
            headers={
                "Origin": "https://random.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in resp.headers


class TestServeCLICorsFlag:
    def test_cors_origin_flag_accepted(self):
        """CLI parser recognizes the --cors-origin flag."""
        result = cli_runner.invoke(
            cli_app,
            ["serve", "/nonexistent/role.yaml", "--cors-origin", "https://example.com"],
        )
        # Will fail because role file doesn't exist, but the flag itself is parsed
        assert result.exit_code == 1
        # Should NOT fail with "no such option" error
        assert "No such option" not in (result.output or "")


class TestNonStreamingValidation:
    """Tests for pre-flight input validation and error classification (fixes #2, #3)."""

    @patch("initrunner.server.app.execute_run")
    @patch("initrunner.server.app.validate_input")
    def test_non_streaming_blocked_input_returns_400(self, mock_validate, mock_execute):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(
            valid=False,
            reason="Blocked by content policy",
        )

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "bad input"}]},
        )
        assert resp.status_code == 400
        assert "Blocked by content policy" in resp.json()["error"]["message"]
        mock_execute.assert_not_called()

    @patch("initrunner.server.app.execute_run")
    def test_non_streaming_timeout_returns_504(self, mock_execute):
        mock_execute.return_value = (
            RunResult(
                run_id="t-1",
                output="",
                success=False,
                error="TimeoutError: Run timed out after 30s",
            ),
            [],
        )

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp.status_code == 504
        assert resp.json()["error"]["type"] == "timeout"
        assert resp.json()["error"]["message"] == "Request timed out"

    @patch("initrunner.server.app.execute_run")
    def test_non_streaming_output_blocked_returns_400(self, mock_execute):
        mock_execute.return_value = (
            RunResult(
                run_id="t-2",
                output="",
                success=False,
                error="Output blocked pattern detected in response",
            ),
            [],
        )

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["type"] == "content_filter"

    @patch("initrunner.server.app.execute_run")
    def test_non_streaming_usage_limit_from_result_returns_400(self, mock_execute):
        mock_execute.return_value = (
            RunResult(
                run_id="t-3",
                output="",
                success=False,
                error="Usage limit exceeded: token budget exhausted",
            ),
            [],
        )

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["type"] == "context_length_exceeded"

    @patch("initrunner.server.app.execute_run")
    def test_non_streaming_model_error_sanitized(self, mock_execute):
        mock_execute.return_value = (
            RunResult(
                run_id="t-4",
                output="",
                success=False,
                error="Model API error: secret-api-key-12345 unauthorized",
            ),
            [],
        )

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp.status_code == 500
        assert "secret-api-key" not in resp.json()["error"]["message"]
        assert resp.json()["error"]["message"] == "Internal server error"


class TestConversationTrimming:
    """Tests for conversation history trimming (fix #4)."""

    def test_conversation_history_trimmed(self):
        from initrunner.server.app import _MAX_CONVERSATION_HISTORY, _trim_history

        messages = list(range(_MAX_CONVERSATION_HISTORY + 20))
        trimmed = _trim_history(messages, _MAX_CONVERSATION_HISTORY)
        assert len(trimmed) == _MAX_CONVERSATION_HISTORY

    def test_conversation_trim_preserves_system_prompt(self):
        from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart

        from initrunner.server.app import _trim_history

        system_msg = ModelRequest(
            parts=[SystemPromptPart(content="You are a helper"), UserPromptPart(content="Hi")]
        )
        other_messages = [f"msg-{i}" for i in range(50)]
        messages = [system_msg, *other_messages]
        trimmed = _trim_history(messages, 10)
        assert len(trimmed) == 10
        assert trimmed[0] is system_msg


class TestStreamingHeaders:
    """Tests for streaming response headers (fix #6)."""

    @patch("initrunner.server.app.execute_run_stream")
    @patch("initrunner.server.app.validate_input")
    def test_streaming_has_x_accel_buffering_header(self, mock_validate, mock_stream):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(valid=True)
        mock_stream.return_value = (
            RunResult(run_id="s-h1", output="Ok", success=True),
            [],
        )

        client = _create_test_client()
        resp = client.post(
            "/v1/chat/completions",
            json=_stream_body(),
        )
        assert resp.status_code == 200
        assert resp.headers.get("X-Accel-Buffering") == "no"


class TestExecutorStreamUsage:
    """Test that run_stream_sync is used correctly (fix #1)."""

    def test_run_stream_sync_used_directly(self):
        import inspect

        from initrunner.agent.executor import execute_run_stream

        source = inspect.getsource(execute_run_stream)
        assert "agent.run_stream_sync(" in source


class TestTokenQueueSize:
    """Test that token queue is large enough (fix #5)."""

    def test_token_queue_max_sufficient(self):
        # Read the source to verify the constant — the queue is defined inside
        # create_app so we inspect source.
        import inspect

        from initrunner.server import app as app_module

        source = inspect.getsource(app_module)
        assert "_TOKEN_QUEUE_MAX = 65_536" in source


class TestStreamingResultChecks:
    """Tests for streaming handler checking result.success after stream completes."""

    @patch("initrunner.server.app.execute_run_stream")
    @patch("initrunner.server.app.validate_input")
    def test_streaming_failed_result_does_not_save_conversation(self, mock_validate, mock_stream):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(valid=True)

        def fake_stream(agent, role, prompt, *, on_token=None, **kw):
            if on_token:
                on_token("partial")
            return (
                RunResult(
                    run_id="fail-1",
                    output="",
                    success=False,
                    error="Model API error: something broke",
                ),
                [],
            )

        mock_stream.side_effect = fake_stream

        client = _create_test_client()

        resp = client.post("/v1/chat/completions", json=_stream_body())
        assert resp.status_code == 200

        # The SSE stream should NOT contain finish_reason="stop" for a failed run
        import json as _json

        chunks = []
        for line in resp.text.strip().split("\n\n"):
            if line.startswith("data: ") and line != "data: [DONE]":
                chunks.append(_json.loads(line[len("data: ") :]))

        stop_chunks = [
            c for c in chunks if c.get("choices", [{}])[0].get("finish_reason") == "stop"
        ]
        assert len(stop_chunks) == 0

    @patch("initrunner.server.app.execute_run_stream")
    @patch("initrunner.server.app.validate_input")
    def test_streaming_output_blocked_sends_content_filter(self, mock_validate, mock_stream):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(valid=True)

        def fake_stream(agent, role, prompt, *, on_token=None, **kw):
            if on_token:
                on_token("some output")
            return (
                RunResult(
                    run_id="block-1",
                    output="",
                    success=False,
                    error="Output blocked pattern detected in response",
                ),
                [],
            )

        mock_stream.side_effect = fake_stream

        client = _create_test_client()
        resp = client.post("/v1/chat/completions", json=_stream_body())
        assert resp.status_code == 200

        # Parse SSE chunks
        import json as _json

        chunks = []
        for line in resp.text.strip().split("\n\n"):
            if line.startswith("data: ") and line != "data: [DONE]":
                chunks.append(_json.loads(line[len("data: ") :]))

        # The finish chunk should have content_filter, not stop
        finish_chunks = [c for c in chunks if c.get("choices", [{}])[0].get("finish_reason")]
        assert len(finish_chunks) == 1
        assert finish_chunks[0]["choices"][0]["finish_reason"] == "content_filter"

    @patch("initrunner.server.app.execute_run_stream")
    @patch("initrunner.server.app.validate_input")
    def test_streaming_timeout_sends_error_sse(self, mock_validate, mock_stream):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(valid=True)

        def fake_stream(agent, role, prompt, *, on_token=None, **kw):
            return (
                RunResult(
                    run_id="timeout-1",
                    output="",
                    success=False,
                    error="TimeoutError: Run timed out after 30s",
                ),
                [],
            )

        mock_stream.side_effect = fake_stream

        client = _create_test_client()
        resp = client.post("/v1/chat/completions", json=_stream_body())
        assert resp.status_code == 200

        # Should contain an error SSE event with timeout info
        assert "Request timed out" in resp.text
        assert "timeout" in resp.text
        assert "[DONE]" in resp.text

    @patch("initrunner.server.app.execute_run_stream")
    @patch("initrunner.server.app.validate_input")
    def test_streaming_success_still_works(self, mock_validate, mock_stream):
        """Regression guard: successful streaming should still save conversation and send stop."""
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(valid=True)

        def fake_stream(agent, role, prompt, *, on_token=None, **kw):
            if on_token:
                on_token("Hello")
            return (
                RunResult(
                    run_id="ok-1",
                    output="Hello",
                    tokens_in=10,
                    tokens_out=5,
                    total_tokens=15,
                    success=True,
                ),
                [{"mock": "messages"}],
            )

        mock_stream.side_effect = fake_stream

        client = _create_test_client()
        resp = client.post("/v1/chat/completions", json=_stream_body())
        assert resp.status_code == 200

        import json as _json

        chunks = []
        for line in resp.text.strip().split("\n\n"):
            if line.startswith("data: ") and line != "data: [DONE]":
                chunks.append(_json.loads(line[len("data: ") :]))

        # Should have finish_reason=stop with usage
        finish_chunks = [c for c in chunks if c.get("choices", [{}])[0].get("finish_reason")]
        assert len(finish_chunks) == 1
        assert finish_chunks[0]["choices"][0]["finish_reason"] == "stop"
        assert finish_chunks[0]["usage"]["prompt_tokens"] == 10
        assert finish_chunks[0]["usage"]["completion_tokens"] == 5


class TestSkipDoubleValidation:
    """Tests that the server passes skip_input_validation=True to avoid double validation."""

    @patch("initrunner.server.app.execute_run")
    @patch("initrunner.server.app.validate_input")
    def test_non_streaming_passes_skip_input_validation(self, mock_validate, mock_execute):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(valid=True)
        mock_execute.return_value = (
            RunResult(run_id="skip-1", output="Ok", success=True),
            [],
        )

        client = _create_test_client()
        client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
        call_kwargs = mock_execute.call_args
        assert call_kwargs.kwargs["skip_input_validation"] is True

    @patch("initrunner.server.app.execute_run_stream")
    @patch("initrunner.server.app.validate_input")
    def test_streaming_passes_skip_input_validation(self, mock_validate, mock_stream):
        from initrunner.agent.policies import ValidationResult

        mock_validate.return_value = ValidationResult(valid=True)
        mock_stream.return_value = (
            RunResult(run_id="skip-2", output="Ok", success=True),
            [],
        )

        client = _create_test_client()
        client.post("/v1/chat/completions", json=_stream_body())
        call_kwargs = mock_stream.call_args
        assert call_kwargs.kwargs["skip_input_validation"] is True


class TestServeCLI:
    def test_missing_role_file(self):
        result = cli_runner.invoke(cli_app, ["serve", "/nonexistent/role.yaml"])
        assert result.exit_code == 1
