"""Tests for A2A (Agent-to-Agent protocol): compat, invoker, schema, server, CLI."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

fasta2a = pytest.importorskip("fasta2a", reason="a2a extras not installed")

from fasta2a.schema import TaskSendParams, TextPart  # type: ignore[import-not-found]  # noqa: E402

from initrunner.agent.delegation import A2AInvoker, reset_context  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_context():
    reset_context()
    yield
    reset_context()


# ---------------------------------------------------------------------------
# Compat / dependency
# ---------------------------------------------------------------------------


class TestCompat:
    def test_require_a2a_when_missing(self):
        from initrunner._compat import MissingExtraError, require_a2a

        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(MissingExtraError, match="initrunner\\[a2a\\]"):
                require_a2a()

    def test_fasta2a_in_extra_packages(self):
        from initrunner._compat import _EXTRA_PACKAGES

        assert "fasta2a" in _EXTRA_PACKAGES
        assert _EXTRA_PACKAGES["fasta2a"][0] == "a2a"


# ---------------------------------------------------------------------------
# A2AInvoker
# ---------------------------------------------------------------------------


def _make_invoker(**kwargs: Any) -> A2AInvoker:
    return A2AInvoker(
        base_url=kwargs.get("base_url", "http://agent:8000"),
        agent_name=kwargs.get("agent_name", "researcher"),
        timeout=kwargs.get("timeout", 30),
        headers_env=kwargs.get("headers_env"),
        source_metadata=kwargs.get("source_metadata"),
    )


def _mock_client():
    """Create a mock httpx.Client context manager."""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def _a2a_response(state, artifacts=None, history=None, task_id="task-1"):
    """Build a mock A2A JSON-RPC response."""
    result = {
        "id": task_id,
        "status": {"state": state},
    }
    if artifacts is not None:
        result["artifacts"] = artifacts
    if history is not None:
        result["history"] = history
    return {"jsonrpc": "2.0", "id": 1, "result": result}


class TestA2AInvokerSuccess:
    def test_completed_text_artifact(self):
        invoker = _make_invoker()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = _a2a_response(
            "completed",
            artifacts=[
                {
                    "artifact_id": "a1",
                    "parts": [{"kind": "text", "text": "Research findings"}],
                }
            ],
        )

        with patch("httpx.Client", return_value=_mock_client()) as cls:
            cls.return_value.post.return_value = resp
            result = invoker.invoke("find papers on X")

        assert result == "Research findings"

    def test_completed_data_artifact(self):
        invoker = _make_invoker()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = _a2a_response(
            "completed",
            artifacts=[
                {
                    "artifact_id": "a1",
                    "parts": [{"kind": "data", "data": {"result": {"score": 0.95}}}],
                }
            ],
        )

        with patch("httpx.Client", return_value=_mock_client()) as cls:
            cls.return_value.post.return_value = resp
            result = invoker.invoke("score this")

        assert '"score": 0.95' in result

    def test_completed_fallback_to_history(self):
        invoker = _make_invoker()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = _a2a_response(
            "completed",
            artifacts=[],
            history=[
                {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "from history"}],
                }
            ],
        )

        with patch("httpx.Client", return_value=_mock_client()) as cls:
            cls.return_value.post.return_value = resp
            result = invoker.invoke("hello")

        assert result == "from history"


class TestA2AInvokerErrors:
    def test_failed_task(self):
        invoker = _make_invoker()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = _a2a_response("failed")

        with patch("httpx.Client", return_value=_mock_client()) as cls:
            cls.return_value.post.return_value = resp
            result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "failed" in result.lower()

    def test_rejected_task(self):
        invoker = _make_invoker()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = _a2a_response("rejected")

        with patch("httpx.Client", return_value=_mock_client()) as cls:
            cls.return_value.post.return_value = resp
            result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "rejected" in result

    def test_jsonrpc_error(self):
        invoker = _make_invoker()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Invalid request"},
        }

        with patch("httpx.Client", return_value=_mock_client()) as cls:
            cls.return_value.post.return_value = resp
            result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "Invalid request" in result

    def test_timeout(self):
        import httpx

        invoker = _make_invoker()

        with patch("httpx.Client", return_value=_mock_client()) as cls:
            cls.return_value.post.side_effect = httpx.TimeoutException("timed out")
            result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "timed out" in result.lower()

    def test_http_error(self):
        import httpx

        invoker = _make_invoker()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch("httpx.Client", return_value=_mock_client()) as cls:
            cls.return_value.post.side_effect = httpx.HTTPStatusError(
                "Server Error", request=MagicMock(), response=mock_resp
            )
            result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "500" in result

    def test_non_json_response(self):
        invoker = _make_invoker()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.side_effect = ValueError("bad json")
        resp.text = "<html>error</html>"

        with patch("httpx.Client", return_value=_mock_client()) as cls:
            cls.return_value.post.return_value = resp
            result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "Non-JSON" in result

    def test_no_output_returns_error(self):
        invoker = _make_invoker()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = _a2a_response("completed", artifacts=[], history=[])

        with patch("httpx.Client", return_value=_mock_client()) as cls:
            cls.return_value.post.return_value = resp
            result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "No output" in result


class TestA2AInvokerPolling:
    def test_polling_flow(self):
        invoker = _make_invoker()

        # First response: submitted, second: working, third: completed
        submitted_resp = MagicMock()
        submitted_resp.raise_for_status = MagicMock()
        submitted_resp.json.return_value = _a2a_response("submitted")

        working_resp = MagicMock()
        working_resp.raise_for_status = MagicMock()
        working_resp.json.return_value = _a2a_response("working")

        completed_resp = MagicMock()
        completed_resp.raise_for_status = MagicMock()
        completed_resp.json.return_value = _a2a_response(
            "completed",
            artifacts=[{"artifact_id": "a1", "parts": [{"kind": "text", "text": "done"}]}],
        )

        with patch("httpx.Client", return_value=_mock_client()) as cls:
            cls.return_value.post.side_effect = [
                submitted_resp,  # initial message/send
                working_resp,  # first poll
                completed_resp,  # second poll
            ]
            with (
                patch("time.monotonic", side_effect=[0, 1, 2, 3]),
                patch("time.sleep"),
            ):
                result = invoker.invoke("hello")

        assert result == "done"

    def test_polling_timeout(self):
        invoker = _make_invoker(timeout=5)

        submitted_resp = MagicMock()
        submitted_resp.raise_for_status = MagicMock()
        submitted_resp.json.return_value = _a2a_response("submitted")

        working_resp = MagicMock()
        working_resp.raise_for_status = MagicMock()
        working_resp.json.return_value = _a2a_response("working")

        with patch("httpx.Client", return_value=_mock_client()) as cls:
            cls.return_value.post.side_effect = [submitted_resp, working_resp, working_resp]
            with (
                patch("time.monotonic", side_effect=[0, 3, 10]),
                patch("time.sleep"),
            ):
                result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "timed out" in result.lower()


class TestA2AInvokerPolicy:
    def test_policy_denial(self):
        from unittest.mock import PropertyMock

        metadata = MagicMock()
        metadata.name = "coordinator"
        type(metadata).name = PropertyMock(return_value="coordinator")

        invoker = _make_invoker(source_metadata=metadata)

        with patch(
            "initrunner.agent.delegation.check_delegation_policy",
            return_value=False,
        ):
            result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "Delegation denied by policy" in result


class TestA2AInvokerHeaders:
    def test_headers_from_env(self):
        import os

        invoker = _make_invoker(headers_env={"Authorization": "MY_API_KEY"})

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = _a2a_response(
            "completed",
            artifacts=[{"artifact_id": "a1", "parts": [{"kind": "text", "text": "ok"}]}],
        )

        with (
            patch.dict(os.environ, {"MY_API_KEY": "Bearer secret123"}),
            patch("httpx.Client", return_value=_mock_client()) as cls,
        ):
            cls.return_value.post.return_value = resp
            invoker.invoke("hello")

        call_headers = cls.return_value.post.call_args.kwargs.get(
            "headers"
        ) or cls.return_value.post.call_args[1].get("headers", {})
        assert call_headers.get("Authorization") == "Bearer secret123"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestDelegateToolConfigA2A:
    def test_a2a_mode_requires_url(self):
        from initrunner.agent.schema.tools._integration import (
            DelegateAgentRef,
            DelegateToolConfig,
        )

        with pytest.raises(ValueError, match="A2A mode requires 'url'"):
            DelegateToolConfig(
                type="delegate",
                mode="a2a",
                agents=[DelegateAgentRef(name="remote-agent")],
            )

    def test_a2a_mode_valid_with_url(self):
        from initrunner.agent.schema.tools._integration import (
            DelegateAgentRef,
            DelegateToolConfig,
        )

        config = DelegateToolConfig(
            type="delegate",
            mode="a2a",
            agents=[DelegateAgentRef(name="remote-agent", url="http://agent:8000")],
        )
        assert config.mode == "a2a"
        assert config.agents[0].url == "http://agent:8000"

    def test_summary_includes_mode(self):
        from initrunner.agent.schema.tools._integration import (
            DelegateAgentRef,
            DelegateToolConfig,
        )

        config = DelegateToolConfig(
            type="delegate",
            mode="a2a",
            agents=[DelegateAgentRef(name="remote-agent", url="http://agent:8000")],
        )
        assert "a2a" in config.summary()


# ---------------------------------------------------------------------------
# Tool builder
# ---------------------------------------------------------------------------


class TestBuildDelegateA2A:
    def test_a2a_mode_creates_a2a_invoker(self):
        from initrunner.agent.schema.tools._integration import (
            DelegateAgentRef,
            DelegateToolConfig,
        )
        from initrunner.agent.tools.custom import build_delegate_toolset

        config = DelegateToolConfig(
            type="delegate",
            mode="a2a",
            agents=[
                DelegateAgentRef(
                    name="remote",
                    url="http://remote:8000",
                    description="Remote A2A agent",
                )
            ],
        )

        mock_ctx = MagicMock()
        mock_ctx.role_dir = None
        mock_ctx.role.metadata = MagicMock()

        toolset = build_delegate_toolset(config, mock_ctx)
        # Verify toolset was created (tool function registered)
        assert toolset is not None


# ---------------------------------------------------------------------------
# Server module
# ---------------------------------------------------------------------------


class TestA2AServer:
    def test_build_a2a_app(self):
        from initrunner.a2a.server import build_a2a_app

        mock_agent = MagicMock()
        mock_role = MagicMock()
        mock_role.metadata.name = "test-agent"
        mock_role.metadata.description = "A test agent"

        app = build_a2a_app(mock_agent, mock_role, host="127.0.0.1", port=9000)

        # FastA2A is a Starlette ASGI app
        assert hasattr(app, "task_manager")

    def test_build_a2a_app_with_api_key(self):
        from initrunner.a2a.server import build_a2a_app

        mock_agent = MagicMock()
        mock_role = MagicMock()
        mock_role.metadata.name = "test-agent"
        mock_role.metadata.description = "A test agent"

        app = build_a2a_app(
            mock_agent,
            mock_role,
            api_key="secret",
        )
        assert app is not None

    def test_build_a2a_app_with_cors(self):
        from initrunner.a2a.server import build_a2a_app

        mock_agent = MagicMock()
        mock_role = MagicMock()
        mock_role.metadata.name = "test-agent"
        mock_role.metadata.description = "A test agent"

        app = build_a2a_app(
            mock_agent,
            mock_role,
            cors_origins=["http://localhost:3000"],
        )
        assert app is not None


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class TestInitRunnerWorker:
    @pytest.mark.anyio
    async def test_run_task_success(self):
        from initrunner.a2a.server import InitRunnerWorker

        mock_agent = MagicMock()
        mock_role = MagicMock()
        mock_broker = MagicMock()
        mock_storage = AsyncMock()
        mock_audit = MagicMock()

        worker = InitRunnerWorker(
            broker=mock_broker,
            storage=mock_storage,
            agent=mock_agent,
            role=mock_role,
            audit_logger=mock_audit,
        )

        task_data = {
            "id": "t1",
            "context_id": "ctx1",
            "status": {"state": "submitted"},
            "history": [
                {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Hello"}],
                    "kind": "message",
                    "message_id": "m1",
                }
            ],
        }
        mock_storage.load_task.return_value = task_data
        mock_storage.load_context.return_value = None

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "Hello back!"

        _send_params: TaskSendParams = {
            "id": "t1",
            "context_id": "ctx1",
            "message": {
                "role": "user",
                "parts": [TextPart(kind="text", text="Hello")],
                "kind": "message",
                "message_id": "m1",
            },
        }

        with patch(
            "initrunner.services.execution.execute_run_async",
            new_callable=AsyncMock,
            return_value=(mock_result, []),
        ):
            await worker.run_task(_send_params)

        # Verify task was marked completed
        calls = mock_storage.update_task.call_args_list
        states = [c.kwargs.get("state") or c.args[1] for c in calls]
        assert "working" in states
        assert "completed" in states

    @pytest.mark.anyio
    async def test_run_task_failure(self):
        from initrunner.a2a.server import InitRunnerWorker

        mock_agent = MagicMock()
        mock_role = MagicMock()
        mock_broker = MagicMock()
        mock_storage = AsyncMock()

        worker = InitRunnerWorker(
            broker=mock_broker,
            storage=mock_storage,
            agent=mock_agent,
            role=mock_role,
        )

        task_data = {
            "id": "t1",
            "context_id": "ctx1",
            "status": {"state": "submitted"},
            "history": [
                {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Hello"}],
                    "kind": "message",
                    "message_id": "m1",
                }
            ],
        }
        mock_storage.load_task.return_value = task_data
        mock_storage.load_context.return_value = None

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "model error"

        _send_params: TaskSendParams = {
            "id": "t1",
            "context_id": "ctx1",
            "message": {
                "role": "user",
                "parts": [TextPart(kind="text", text="Hello")],
                "kind": "message",
                "message_id": "m1",
            },
        }

        with patch(
            "initrunner.services.execution.execute_run_async",
            new_callable=AsyncMock,
            return_value=(mock_result, []),
        ):
            await worker.run_task(_send_params)

        calls = mock_storage.update_task.call_args_list
        states = [c.kwargs.get("state") or c.args[1] for c in calls]
        assert "failed" in states


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestA2ACLI:
    def test_help(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["a2a", "serve", "--help"])
        assert result.exit_code == 0
        assert "A2A" in result.output or "a2a" in result.output
        assert "ROLE_FILE" in result.output
