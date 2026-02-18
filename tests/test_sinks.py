"""Tests for the sink system."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx

from initrunner.agent.executor import RunResult
from initrunner.agent.schema.role import RoleDefinition
from initrunner.agent.schema.sinks import CustomSinkConfig, FileSinkConfig, WebhookSinkConfig
from initrunner.sinks.base import SinkPayload
from initrunner.sinks.dispatcher import SinkDispatcher


def _make_payload(**overrides) -> SinkPayload:
    defaults = {
        "agent_name": "test-agent",
        "run_id": "abc123",
        "prompt": "hello",
        "output": "world",
        "success": True,
        "error": None,
        "tokens_in": 10,
        "tokens_out": 20,
        "duration_ms": 100,
        "model": "gpt-4o-mini",
        "provider": "openai",
        "trigger_type": None,
        "trigger_metadata": {},
        "timestamp": "2025-01-01T00:00:00+00:00",
    }
    defaults.update(overrides)
    return SinkPayload(**defaults)  # type: ignore[arg-type]


def _make_role_data() -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent", "description": "test"},
        "spec": {
            "role": "You are a test agent.",
            "model": {"provider": "openai", "name": "gpt-4o-mini"},
        },
    }


class TestSinkPayload:
    def test_creation(self):
        p = _make_payload()
        assert p.agent_name == "test-agent"
        assert p.run_id == "abc123"
        assert p.success is True

    def test_to_dict(self):
        p = _make_payload()
        d = p.to_dict()
        assert isinstance(d, dict)
        assert d["agent_name"] == "test-agent"
        assert d["output"] == "world"
        assert d["tokens_in"] == 10
        assert d["trigger_type"] is None
        assert d["trigger_metadata"] == {}

    def test_to_dict_with_error(self):
        p = _make_payload(success=False, error="boom", output="")
        d = p.to_dict()
        assert d["success"] is False
        assert d["error"] == "boom"

    def test_to_dict_with_trigger(self):
        p = _make_payload(trigger_type="cron", trigger_metadata={"schedule": "daily"})
        d = p.to_dict()
        assert d["trigger_type"] == "cron"
        assert d["trigger_metadata"]["schedule"] == "daily"


class TestWebhookSink:
    def test_post_success(self):
        from initrunner.sinks.webhook import WebhookSink

        sink = WebhookSink(url="https://example.com/hook")
        payload = _make_payload()

        with patch("initrunner.sinks.webhook.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_client.request.return_value = mock_response

            sink.send(payload)

            mock_client.request.assert_called_once()
            call_args = mock_client.request.call_args
            assert call_args[0][0] == "POST"
            assert call_args[0][1] == "https://example.com/hook"
            assert call_args[1]["json"]["agent_name"] == "test-agent"

    def test_custom_method_and_headers(self):
        from initrunner.sinks.webhook import WebhookSink

        sink = WebhookSink(
            url="https://example.com",
            method="PUT",
            headers={"X-Custom": "value"},
        )
        payload = _make_payload()

        with patch("initrunner.sinks.webhook.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_client.request.return_value = mock_response

            sink.send(payload)

            call_args = mock_client.request.call_args
            assert call_args[0][0] == "PUT"
            assert call_args[1]["headers"]["X-Custom"] == "value"

    def test_retry_on_failure(self):
        from initrunner.sinks.webhook import WebhookSink

        sink = WebhookSink(url="https://example.com/hook", retry_count=2)
        payload = _make_payload()

        with (
            patch("initrunner.sinks.webhook.httpx.Client") as mock_client_cls,
            patch("initrunner.sinks.webhook.time.sleep") as mock_sleep,
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.request.side_effect = httpx.HTTPError("fail")

            # Should not raise
            sink.send(payload)

            assert mock_client.request.call_count == 3  # 1 + 2 retries
            assert mock_sleep.call_count == 2

    def test_never_raises(self):
        from initrunner.sinks.webhook import WebhookSink

        sink = WebhookSink(url="https://example.com/hook")
        payload = _make_payload()

        with patch("initrunner.sinks.webhook.httpx.Client") as mock_client_cls:
            mock_client_cls.side_effect = Exception("connection error")
            # Should not raise
            sink.send(payload)


class TestFileSink:
    def test_write_json(self, tmp_path):
        from initrunner.sinks.file import FileSink

        out = tmp_path / "results.jsonl"
        sink = FileSink(path=str(out), fmt="json")
        payload = _make_payload()

        sink.send(payload)

        lines = out.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["agent_name"] == "test-agent"
        assert data["output"] == "world"

    def test_write_text(self, tmp_path):
        from initrunner.sinks.file import FileSink

        out = tmp_path / "results.txt"
        sink = FileSink(path=str(out), fmt="text")
        payload = _make_payload()

        sink.send(payload)

        content = out.read_text()
        assert "test-agent" in content
        assert "OK" in content
        assert "world" in content

    def test_append_mode(self, tmp_path):
        from initrunner.sinks.file import FileSink

        out = tmp_path / "results.jsonl"
        sink = FileSink(path=str(out), fmt="json")

        sink.send(_make_payload(output="first"))
        sink.send(_make_payload(output="second"))

        lines = out.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["output"] == "first"
        assert json.loads(lines[1])["output"] == "second"

    def test_creates_parent_dirs(self, tmp_path):
        from initrunner.sinks.file import FileSink

        out = tmp_path / "deep" / "nested" / "results.jsonl"
        sink = FileSink(path=str(out), fmt="json")

        sink.send(_make_payload())

        assert out.exists()

    def test_never_raises(self, tmp_path):
        from initrunner.sinks.file import FileSink

        # Use a path that can't be written to
        sink = FileSink(path="/dev/null/impossible/file.jsonl", fmt="json")
        # Should not raise
        sink.send(_make_payload())

    def test_text_with_error(self, tmp_path):
        from initrunner.sinks.file import FileSink

        out = tmp_path / "results.txt"
        sink = FileSink(path=str(out), fmt="text")
        payload = _make_payload(success=False, error="something broke", output="")

        sink.send(payload)

        content = out.read_text()
        assert "ERROR: something broke" in content


class TestCustomSink:
    def test_calls_function(self):
        from initrunner.sinks.custom import CustomSink

        mock_func = MagicMock()
        mock_mod = MagicMock()
        mock_mod.my_handler = mock_func

        sink = CustomSink(module="my_module", function="my_handler")
        payload = _make_payload()

        with patch("initrunner.sinks.custom.importlib.import_module", return_value=mock_mod):
            sink.send(payload)

        mock_func.assert_called_once()
        call_arg = mock_func.call_args[0][0]
        assert isinstance(call_arg, dict)
        assert call_arg["agent_name"] == "test-agent"

    def test_adds_role_dir_to_sys_path(self, tmp_path):
        from initrunner.sinks.custom import CustomSink

        mock_func = MagicMock()
        mock_mod = MagicMock()
        mock_mod.handler = mock_func

        sink = CustomSink(module="local_mod", function="handler", role_dir=tmp_path)
        payload = _make_payload()

        with patch("initrunner.sinks.custom.importlib.import_module", return_value=mock_mod):
            sink.send(payload)

        assert str(tmp_path) in __import__("sys").path

    def test_never_raises(self):
        from initrunner.sinks.custom import CustomSink

        sink = CustomSink(module="nonexistent_module_xyz", function="handler")
        # Should not raise
        sink.send(_make_payload())


class TestSinkDispatcher:
    def test_build_from_configs(self):
        role = RoleDefinition.model_validate(_make_role_data())
        configs = [
            WebhookSinkConfig(url="https://example.com/hook"),
            FileSinkConfig(path="/tmp/test.jsonl"),
        ]
        dispatcher = SinkDispatcher(configs, role)
        assert dispatcher.count == 2

    def test_dispatch_calls_all_sinks(self):
        role = RoleDefinition.model_validate(_make_role_data())
        dispatcher = SinkDispatcher([], role)

        mock_sink1 = MagicMock()
        mock_sink2 = MagicMock()
        dispatcher._sinks = [mock_sink1, mock_sink2]

        result = RunResult(
            run_id="test123",
            output="result text",
            tokens_in=5,
            tokens_out=10,
            duration_ms=50,
            success=True,
        )

        dispatcher.dispatch(result, "test prompt")

        mock_sink1.send.assert_called_once()
        mock_sink2.send.assert_called_once()

        payload = mock_sink1.send.call_args[0][0]
        assert isinstance(payload, SinkPayload)
        assert payload.agent_name == "test-agent"
        assert payload.prompt == "test prompt"
        assert payload.output == "result text"

    def test_dispatch_with_trigger_info(self):
        role = RoleDefinition.model_validate(_make_role_data())
        dispatcher = SinkDispatcher([], role)

        mock_sink = MagicMock()
        dispatcher._sinks = [mock_sink]

        result = RunResult(run_id="test123", output="ok", success=True)

        dispatcher.dispatch(
            result,
            "cron prompt",
            trigger_type="cron",
            trigger_metadata={"schedule": "daily"},
        )

        payload = mock_sink.send.call_args[0][0]
        assert payload.trigger_type == "cron"
        assert payload.trigger_metadata == {"schedule": "daily"}

    def test_error_isolation(self):
        """One sink failing should not prevent others from running."""
        role = RoleDefinition.model_validate(_make_role_data())
        dispatcher = SinkDispatcher([], role)

        failing_sink = MagicMock()
        failing_sink.send.side_effect = RuntimeError("sink exploded")
        ok_sink = MagicMock()
        dispatcher._sinks = [failing_sink, ok_sink]

        result = RunResult(run_id="test123", output="ok", success=True)

        # Should not raise
        dispatcher.dispatch(result, "test")

        failing_sink.send.assert_called_once()
        ok_sink.send.assert_called_once()

    def test_build_custom_sink(self, tmp_path):
        role = RoleDefinition.model_validate(_make_role_data())
        configs = [CustomSinkConfig(module="my_mod", function="my_func")]
        dispatcher = SinkDispatcher(configs, role, role_dir=tmp_path)
        assert dispatcher.count == 1


class TestEnvVarExpansion:
    def test_webhook_url_expansion(self, monkeypatch):
        from initrunner.sinks.webhook import WebhookSink

        monkeypatch.setenv("MY_HOOK_URL", "https://hooks.example.com/abc")
        sink = WebhookSink(url="${MY_HOOK_URL}")
        assert sink._url == "https://hooks.example.com/abc"

    def test_webhook_header_expansion(self, monkeypatch):
        from initrunner.sinks.webhook import WebhookSink

        monkeypatch.setenv("API_TOKEN", "secret123")
        sink = WebhookSink(
            url="https://example.com",
            headers={"Authorization": "Bearer ${API_TOKEN}"},
        )
        assert sink._headers["Authorization"] == "Bearer secret123"

    def test_file_path_expansion(self, monkeypatch):
        from initrunner.sinks.file import FileSink

        monkeypatch.setenv("LOG_DIR", "/var/log/agents")
        sink = FileSink(path="${LOG_DIR}/results.jsonl")
        assert str(sink._path) == "/var/log/agents/results.jsonl"

    def test_unexpanded_var_kept_as_is(self):
        from initrunner.sinks.webhook import WebhookSink

        sink = WebhookSink(url="${NONEXISTENT_VAR_12345}")
        # os.path.expandvars keeps unset vars as-is
        assert sink._url == "${NONEXISTENT_VAR_12345}"
