"""Tests for the executor."""

from unittest.mock import MagicMock

from initrunner.agent.executor import (
    check_token_budget,
    execute_run,
    execute_run_stream,
)
from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
from initrunner.agent.schema.guardrails import Guardrails
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.audit.logger import AuditLogger


def _make_role() -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="anthropic", name="claude-sonnet-4-5-20250929"),
        ),
    )


def _make_mock_agent(output: str = "Hello!", tokens_in: int = 10, tokens_out: int = 5):
    agent = MagicMock()
    result = MagicMock()
    result.output = output

    usage = MagicMock()
    usage.input_tokens = tokens_in
    usage.output_tokens = tokens_out
    usage.total_tokens = tokens_in + tokens_out
    usage.tool_calls = 0
    result.usage.return_value = usage
    result.all_messages.return_value = [{"role": "user", "content": "hi"}]

    agent.run_sync.return_value = result
    return agent


class TestExecuteRun:
    def test_successful_run(self):
        agent = _make_mock_agent(output="Test response")
        role = _make_role()
        result, _messages = execute_run(agent, role, "Hello")

        assert result.success is True
        assert result.output == "Test response"
        assert result.tokens_in == 10
        assert result.tokens_out == 5
        assert result.total_tokens == 15
        assert result.duration_ms >= 0
        assert len(result.run_id) == 12

    def test_failed_run(self):
        agent = MagicMock()
        agent.run_sync.side_effect = ConnectionError("API error")
        role = _make_role()

        result, messages = execute_run(agent, role, "Hello")

        assert result.success is False
        assert result.error == "ConnectionError: API error"
        assert result.output == ""
        assert messages == []

    def test_audit_logging(self, tmp_path):
        db_path = tmp_path / "test_audit.db"
        agent = _make_mock_agent()
        role = _make_role()

        with AuditLogger(db_path) as logger:
            result, _ = execute_run(agent, role, "Hello", audit_logger=logger)

        assert result.success is True

        # Verify record was written
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT * FROM audit_log").fetchall()
        conn.close()
        assert len(rows) == 1

    def test_no_audit_logger(self):
        agent = _make_mock_agent()
        role = _make_role()
        result, _ = execute_run(agent, role, "Hello", audit_logger=None)
        assert result.success is True

    def test_message_history_passed(self):
        agent = _make_mock_agent()
        role = _make_role()
        history = [{"role": "user", "content": "previous"}]

        execute_run(agent, role, "Hello", message_history=history)
        agent.run_sync.assert_called_once()
        call_kwargs = agent.run_sync.call_args
        assert call_kwargs.kwargs["message_history"] == history

    def test_trigger_context_flows_to_audit(self, tmp_path):
        import json
        import sqlite3

        db_path = tmp_path / "test_audit.db"
        agent = _make_mock_agent()
        role = _make_role()

        with AuditLogger(db_path) as logger:
            execute_run(
                agent,
                role,
                "triggered prompt",
                audit_logger=logger,
                trigger_type="cron",
                trigger_metadata={"schedule": "0 9 * * 1"},
            )

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM audit_log").fetchone()
        conn.close()

        assert row["trigger_type"] == "cron"
        assert json.loads(row["trigger_metadata"]) == {"schedule": "0 9 * * 1"}

    def test_dict_output_serialized_as_json(self):
        agent = MagicMock()
        result_mock = MagicMock()
        result_mock.output = {"summary": "test", "score": 42}
        usage = MagicMock()
        usage.input_tokens = 10
        usage.output_tokens = 5
        usage.total_tokens = 15
        usage.tool_calls = 0
        result_mock.usage.return_value = usage
        result_mock.all_messages.return_value = []
        agent.run_sync.return_value = result_mock
        role = _make_role()

        result, _ = execute_run(agent, role, "Hello")

        assert result.success is True
        import json

        parsed = json.loads(result.output)
        assert parsed == {"summary": "test", "score": 42}

    def test_list_output_serialized_as_json(self):
        agent = MagicMock()
        result_mock = MagicMock()
        result_mock.output = [1, 2, 3]
        usage = MagicMock()
        usage.input_tokens = 10
        usage.output_tokens = 5
        usage.total_tokens = 15
        usage.tool_calls = 0
        result_mock.usage.return_value = usage
        result_mock.all_messages.return_value = []
        agent.run_sync.return_value = result_mock
        role = _make_role()

        result, _ = execute_run(agent, role, "Hello")

        assert result.success is True
        import json

        parsed = json.loads(result.output)
        assert parsed == [1, 2, 3]

    def test_trigger_context_defaults_to_none(self, tmp_path):
        import sqlite3

        db_path = tmp_path / "test_audit.db"
        agent = _make_mock_agent()
        role = _make_role()

        with AuditLogger(db_path) as logger:
            execute_run(agent, role, "Hello", audit_logger=logger)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM audit_log").fetchone()
        conn.close()

        assert row["trigger_type"] is None
        assert row["trigger_metadata"] is None

    def test_usage_limits_wiring(self):
        """Verify all guardrail fields are passed to UsageLimits."""
        agent = _make_mock_agent()
        role = RoleDefinition(
            apiVersion=ApiVersion.V1,
            kind=Kind.AGENT,
            metadata=Metadata(name="test-agent"),
            spec=AgentSpec(
                role="You are a test.",
                model=ModelConfig(provider="anthropic", name="claude-sonnet-4-5-20250929"),
                guardrails=Guardrails(
                    max_tokens_per_run=30000,
                    max_tool_calls=10,
                    max_request_limit=25,
                    input_tokens_limit=80000,
                    total_tokens_limit=150000,
                ),
            ),
        )

        execute_run(agent, role, "Hello")
        call_kwargs = agent.run_sync.call_args
        limits = call_kwargs.kwargs["usage_limits"]

        assert limits.output_tokens_limit == 30000
        assert limits.request_limit == 25
        assert limits.tool_calls_limit == 10
        assert limits.input_tokens_limit == 80000
        assert limits.total_tokens_limit == 150000

    def test_usage_limits_defaults_none(self):
        """When new limit fields are None, they pass through as None to UsageLimits."""
        agent = _make_mock_agent()
        role = _make_role()

        execute_run(agent, role, "Hello")
        call_kwargs = agent.run_sync.call_args
        limits = call_kwargs.kwargs["usage_limits"]

        assert limits.output_tokens_limit == 50000
        assert limits.request_limit == 30
        assert limits.tool_calls_limit == 20
        assert limits.input_tokens_limit is None
        assert limits.total_tokens_limit is None


class TestCheckTokenBudget:
    def test_no_budget(self):
        status = check_token_budget(1000, None)
        assert status.budget is None
        assert status.consumed == 1000
        assert status.remaining is None
        assert status.exceeded is False
        assert status.warning is False

    def test_under_budget(self):
        status = check_token_budget(1000, 10000)
        assert status.budget == 10000
        assert status.consumed == 1000
        assert status.remaining == 9000
        assert status.exceeded is False
        assert status.warning is False

    def test_at_warning_threshold(self):
        status = check_token_budget(8000, 10000)
        assert status.warning is True
        assert status.exceeded is False
        assert status.remaining == 2000

    def test_just_below_warning(self):
        status = check_token_budget(7999, 10000)
        assert status.warning is False
        assert status.exceeded is False

    def test_exactly_at_budget(self):
        status = check_token_budget(10000, 10000)
        assert status.exceeded is True
        assert status.warning is False
        assert status.remaining == 0

    def test_over_budget(self):
        status = check_token_budget(15000, 10000)
        assert status.exceeded is True
        assert status.warning is False
        assert status.remaining == 0

    def test_zero_consumed(self):
        status = check_token_budget(0, 10000)
        assert status.exceeded is False
        assert status.warning is False
        assert status.remaining == 10000

    def test_zero_budget(self):
        status = check_token_budget(0, 0)
        assert status.exceeded is True
        assert status.remaining == 0


class TestSkipInputValidation:
    """Tests that skip_input_validation=True skips the _validate_input_or_fail call."""

    def test_execute_run_skips_validation(self):
        from unittest.mock import patch

        agent = _make_mock_agent()
        role = _make_role()

        with patch("initrunner.agent.executor._validate_input_or_fail") as mock_validate:
            execute_run(agent, role, "Hello", skip_input_validation=True)
            mock_validate.assert_not_called()

    def test_execute_run_stream_skips_validation(self):
        from unittest.mock import patch

        agent = MagicMock()
        stream_ctx = MagicMock()
        stream_mock = MagicMock()
        stream_mock.stream_text.return_value = iter(["Hello"])
        stream_mock.all_messages.return_value = []
        usage = MagicMock()
        usage.input_tokens = 5
        usage.output_tokens = 3
        usage.total_tokens = 8
        stream_mock.usage.return_value = usage
        stream_ctx.__enter__ = MagicMock(return_value=stream_mock)
        stream_ctx.__exit__ = MagicMock(return_value=False)
        agent.run_stream_sync.return_value = stream_ctx

        role = _make_role()

        with patch("initrunner.agent.executor._validate_input_or_fail") as mock_validate:
            execute_run_stream(agent, role, "Hello", skip_input_validation=True)
            mock_validate.assert_not_called()
