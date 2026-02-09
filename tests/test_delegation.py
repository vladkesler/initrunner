"""Tests for agent delegation: depth tracking, inline invoker, MCP invoker."""

import textwrap
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent.delegation import (
    DelegationDepthExceeded,
    InlineInvoker,
    McpInvoker,
    enter_delegation,
    exit_delegation,
    get_current_chain,
    get_current_depth,
    reset_context,
)


@pytest.fixture(autouse=True)
def _clean_context():
    """Reset delegation context before and after each test."""
    reset_context()
    yield
    reset_context()


class TestDepthTracking:
    def test_initial_depth_zero(self):
        assert get_current_depth() == 0
        assert get_current_chain() == []

    def test_enter_exit(self):
        enter_delegation("agent-a", max_depth=3)
        assert get_current_depth() == 1
        assert get_current_chain() == ["agent-a"]

        exit_delegation()
        assert get_current_depth() == 0
        assert get_current_chain() == []

    def test_nested_delegation(self):
        enter_delegation("agent-a", max_depth=3)
        enter_delegation("agent-b", max_depth=3)
        assert get_current_depth() == 2
        assert get_current_chain() == ["agent-a", "agent-b"]

        exit_delegation()
        assert get_current_depth() == 1
        assert get_current_chain() == ["agent-a"]

    def test_depth_exceeded(self):
        enter_delegation("a", max_depth=2)
        enter_delegation("b", max_depth=2)
        with pytest.raises(DelegationDepthExceeded, match="depth 3 exceeds max_depth 2"):
            enter_delegation("c", max_depth=2)

    def test_depth_exceeded_shows_chain(self):
        enter_delegation("parent", max_depth=1)
        with pytest.raises(DelegationDepthExceeded, match="parent -> child"):
            enter_delegation("child", max_depth=1)

    def test_exit_at_zero_is_safe(self):
        exit_delegation()
        assert get_current_depth() == 0

    def test_reset_context(self):
        enter_delegation("a", max_depth=5)
        enter_delegation("b", max_depth=5)
        reset_context()
        assert get_current_depth() == 0
        assert get_current_chain() == []


class TestInlineInvoker:
    def test_successful_invocation(self, tmp_path):
        role_file = tmp_path / "agent.yaml"
        role_file.write_text(
            textwrap.dedent("""\
                apiVersion: initrunner/v1
                kind: Agent
                metadata:
                  name: sub-agent
                spec:
                  role: You are helpful.
                  model:
                    provider: openai
                    name: gpt-4o-mini
            """)
        )

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "sub-agent response"

        with (
            patch("initrunner.agent.loader.load_and_build") as mock_load,
            patch("initrunner.agent.executor.execute_run") as mock_exec,
        ):
            mock_load.return_value = (MagicMock(), MagicMock())
            mock_load.return_value[0].metadata.name = "sub-agent"
            mock_exec.return_value = (mock_result, [])

            invoker = InlineInvoker(role_file, max_depth=3, timeout=60)
            result = invoker.invoke("hello")

        assert result == "sub-agent response"

    def test_load_failure_returns_error(self, tmp_path):
        role_file = tmp_path / "missing.yaml"
        invoker = InlineInvoker(role_file, max_depth=3, timeout=60)
        result = invoker.invoke("hello")
        assert "[DELEGATION ERROR]" in result
        assert "Failed to load" in result

    def test_depth_exceeded_returns_error(self, tmp_path):
        role_file = tmp_path / "agent.yaml"
        role_file.write_text(
            textwrap.dedent("""\
                apiVersion: initrunner/v1
                kind: Agent
                metadata:
                  name: deep-agent
                spec:
                  role: Test
                  model:
                    provider: openai
                    name: gpt-4o-mini
            """)
        )

        # Pre-fill depth to max
        enter_delegation("parent", max_depth=5)

        with patch("initrunner.agent.loader.load_and_build") as mock_load:
            mock_load.return_value = (MagicMock(), MagicMock())
            mock_load.return_value[0].metadata.name = "deep-agent"

            invoker = InlineInvoker(role_file, max_depth=1, timeout=60)
            result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "exceeds max_depth" in result

    def test_agent_failure_returns_error(self, tmp_path):
        role_file = tmp_path / "agent.yaml"
        role_file.write_text("dummy")

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "API limit exceeded"

        with (
            patch("initrunner.agent.loader.load_and_build") as mock_load,
            patch("initrunner.agent.executor.execute_run") as mock_exec,
        ):
            mock_load.return_value = (MagicMock(), MagicMock())
            mock_load.return_value[0].metadata.name = "fail-agent"
            mock_exec.return_value = (mock_result, [])

            invoker = InlineInvoker(role_file, max_depth=3, timeout=60)
            result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "API limit exceeded" in result


class TestMcpInvoker:
    def test_successful_invocation(self):
        invoker = McpInvoker(
            base_url="http://summarizer:8000",
            agent_name="summarizer",
            timeout=30,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "Summary result"}}]}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = invoker.invoke("summarize this")

        assert result == "Summary result"
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "/v1/chat/completions" in call_args.args[0]

    def test_timeout_returns_error(self):
        import httpx

        invoker = McpInvoker(
            base_url="http://summarizer:8000",
            agent_name="summarizer",
            timeout=5,
        )

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = httpx.TimeoutException("timed out")
            mock_client_cls.return_value = mock_client

            result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "timed out" in result.lower()

    def test_http_error_returns_error(self):
        import httpx

        invoker = McpInvoker(
            base_url="http://summarizer:8000",
            agent_name="summarizer",
            timeout=30,
        )

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "500", request=MagicMock(), response=mock_response
            )
            mock_client_cls.return_value = mock_client

            result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "500" in result

    def test_headers_env_resolved(self):
        invoker = McpInvoker(
            base_url="http://agent:8000",
            agent_name="agent",
            timeout=30,
            headers_env={"Authorization": "MY_TOKEN"},
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        mock_response.raise_for_status = MagicMock()

        with (
            patch.dict("os.environ", {"MY_TOKEN": "Bearer secret123"}),
            patch("httpx.Client") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            invoker.invoke("test")

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer secret123"

    def test_trailing_slash_stripped(self):
        invoker = McpInvoker(
            base_url="http://agent:8000/",
            agent_name="agent",
            timeout=30,
        )
        assert invoker._base_url == "http://agent:8000"


class TestInlineInvokerSharedMemory:
    def test_shared_memory_patches_sub_agent(self, tmp_path):
        """When shared_memory_path is set, sub-agent gets memory overridden."""
        role_file = tmp_path / "agent.yaml"
        role_file.write_text(
            textwrap.dedent("""\
                apiVersion: initrunner/v1
                kind: Agent
                metadata:
                  name: sub-agent
                spec:
                  role: You are helpful.
                  model:
                    provider: openai
                    name: gpt-4o-mini
            """)
        )

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "response"

        shared_path = str(tmp_path / "shared.db")
        patched_memory = None

        def _capture_build(role, **kwargs):
            nonlocal patched_memory
            patched_memory = role.spec.memory
            return MagicMock()

        with (
            patch("initrunner.agent.loader.build_agent", side_effect=_capture_build),
            patch("initrunner.agent.executor.execute_run") as mock_exec,
        ):
            mock_exec.return_value = (mock_result, [])
            invoker = InlineInvoker(
                role_file,
                max_depth=3,
                timeout=60,
                shared_memory_path=shared_path,
                shared_max_memories=500,
            )
            result = invoker.invoke("hello")

        assert result == "response"
        assert patched_memory is not None
        assert patched_memory.store_path == shared_path
        assert patched_memory.max_memories == 500

    def test_no_shared_memory_leaves_role_unchanged(self, tmp_path):
        """Without shared_memory_path, standard load_and_build is used."""
        role_file = tmp_path / "agent.yaml"
        role_file.write_text(
            textwrap.dedent("""\
                apiVersion: initrunner/v1
                kind: Agent
                metadata:
                  name: sub-agent
                spec:
                  role: You are helpful.
                  model:
                    provider: openai
                    name: gpt-4o-mini
            """)
        )

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "response"

        with (
            patch("initrunner.agent.loader.load_and_build") as mock_load,
            patch("initrunner.agent.executor.execute_run") as mock_exec,
        ):
            mock_role = MagicMock()
            mock_role.metadata.name = "sub-agent"
            mock_role.spec.memory = None
            mock_load.return_value = (mock_role, MagicMock())
            mock_exec.return_value = (mock_result, [])

            invoker = InlineInvoker(role_file, max_depth=3, timeout=60)
            result = invoker.invoke("hello")

        assert result == "response"
        mock_load.assert_called_once()
        assert mock_role.spec.memory is None
