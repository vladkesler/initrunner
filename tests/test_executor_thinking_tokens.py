"""Tests for thinking-token extraction in the executor output pipeline."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from initrunner.agent.executor_models import RunResult
from initrunner.agent.executor_output import (
    _extract_thinking_tokens,
    _finalize_run_output,
    _process_agent_output,
)


def _usage(**kwargs) -> SimpleNamespace:
    base = {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "tool_calls": 0,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


class TestExtractThinkingTokens:
    def test_direct_attribute(self):
        usage = _usage(thinking_tokens=4200)
        assert _extract_thinking_tokens(usage) == 4200

    def test_details_reasoning_tokens(self):
        usage = _usage(details={"reasoning_tokens": 3100})
        assert _extract_thinking_tokens(usage) == 3100

    def test_details_thinking_tokens_key(self):
        usage = _usage(details={"thinking_tokens": 2000})
        assert _extract_thinking_tokens(usage) == 2000

    def test_direct_attribute_wins_over_details(self):
        usage = _usage(thinking_tokens=4200, details={"reasoning_tokens": 3100})
        assert _extract_thinking_tokens(usage) == 4200

    def test_missing_everything_returns_zero(self):
        usage = _usage()
        assert _extract_thinking_tokens(usage) == 0

    def test_zero_value_returns_zero(self):
        usage = _usage(thinking_tokens=0, details={})
        assert _extract_thinking_tokens(usage) == 0

    def test_details_not_a_dict_is_ignored(self):
        usage = _usage(details=None)
        assert _extract_thinking_tokens(usage) == 0


def _stub_output_validation(monkeypatch) -> None:
    """Make validate_output a no-op pass-through so role mocks stay simple."""

    def _passthrough(text, policy):
        return SimpleNamespace(blocked=False, text=text, reason=None)

    from initrunner.agent import policies

    monkeypatch.setattr(policies, "validate_output", _passthrough)


class TestFinalizeRunOutputThinkingTokens:
    def test_populates_thinking_tokens_from_details(self, monkeypatch):
        _stub_output_validation(monkeypatch)
        result = RunResult(run_id="r1")
        role = MagicMock()
        usage = _usage(details={"reasoning_tokens": 5000})

        _finalize_run_output("the answer", usage, [], result, role)

        assert result.thinking_tokens == 5000
        assert result.total_tokens == 15

    def test_zero_when_usage_has_no_thinking(self, monkeypatch):
        _stub_output_validation(monkeypatch)
        result = RunResult(run_id="r1")
        role = MagicMock()
        usage = _usage()

        _finalize_run_output("ok", usage, [], result, role)

        assert result.thinking_tokens == 0

    def test_process_agent_output_sets_thinking_tokens(self, monkeypatch):
        _stub_output_validation(monkeypatch)
        result = RunResult(run_id="r2")
        role = MagicMock()
        agent_result = MagicMock()
        agent_result.output = "done"
        agent_result.usage = _usage(thinking_tokens=1234)
        agent_result.all_messages.return_value = []

        _process_agent_output(agent_result, result, role)

        assert result.thinking_tokens == 1234


class TestRunResultDefault:
    def test_thinking_tokens_defaults_to_zero(self):
        assert RunResult(run_id="x").thinking_tokens == 0
