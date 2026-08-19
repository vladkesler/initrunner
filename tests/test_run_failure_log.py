"""Tests for the operator-facing run-failure log line."""

from __future__ import annotations

import logging

import pytest

from initrunner.agent.executor_models import ErrorCategory, RunResult
from initrunner.agent.executor_output import _log_run_failure
from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.role import AgentSpec, RoleDefinition


@pytest.fixture()
def _propagate(monkeypatch):
    monkeypatch.setattr(logging.getLogger("initrunner"), "propagate", True)


@pytest.fixture()
def role():
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="logger-test"),
        spec=AgentSpec(
            role="You are a test agent.",
            model=ModelConfig(provider="anthropic", name="claude-sonnet-4-5-20250929"),
        ),
    )


@pytest.mark.usefixtures("_propagate")
class TestLogRunFailure:
    def test_failure_is_logged_with_category(self, caplog, role):
        result = RunResult(
            run_id="abc123",
            success=False,
            error="Model API error: status_code: 401",
            error_category=ErrorCategory.AUTH,
        )
        with caplog.at_level(logging.WARNING, logger="initrunner.agent.run"):
            _log_run_failure(result, role)
        assert "run abc123 of agent 'logger-test' failed [auth]" in caplog.text
        assert "status_code: 401" in caplog.text

    def test_success_is_not_logged(self, caplog, role):
        result = RunResult(run_id="abc123", success=True, output="fine")
        with caplog.at_level(logging.WARNING, logger="initrunner.agent.run"):
            _log_run_failure(result, role)
        assert caplog.text == ""

    def test_missing_category_reads_unknown(self, caplog, role):
        result = RunResult(run_id="abc123", success=False, error="boom")
        with caplog.at_level(logging.WARNING, logger="initrunner.agent.run"):
            _log_run_failure(result, role)
        assert "[unknown]: boom" in caplog.text

    def test_missing_error_has_placeholder(self, caplog, role):
        result = RunResult(run_id="abc123", success=False)
        with caplog.at_level(logging.WARNING, logger="initrunner.agent.run"):
            _log_run_failure(result, role)
        assert "no error detail" in caplog.text

    def test_secrets_are_scrubbed(self, caplog, role):
        secret = "sk-proj-" + "a" * 32
        result = RunResult(
            run_id="abc123",
            success=False,
            error=f"Incorrect API key provided: {secret}",
            error_category=ErrorCategory.AUTH,
        )
        with caplog.at_level(logging.WARNING, logger="initrunner.agent.run"):
            _log_run_failure(result, role)
        assert secret not in caplog.text
        assert "[REDACTED]" in caplog.text
