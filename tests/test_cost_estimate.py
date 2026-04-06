"""Tests for cost estimation from role YAML files."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from initrunner.cli.cost_cmd import app
from initrunner.services.cost import estimate_role_cost_sync

runner = CliRunner()

_RESOLVED_ROLE = """\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: test-agent
spec:
  role: "You are a helpful assistant."
  model:
    provider: openai
    name: gpt-4o
    max_tokens: 4096
  tools:
    - type: shell
      allowed_commands: [echo]
    - type: web_reader
  guardrails:
    max_tool_calls: 5
"""

_UNRESOLVED_ROLE = """\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: test-unresolved
spec:
  role: "You are a test agent."
  model:
    max_tokens: 2048
  guardrails:
    max_tool_calls: 0
"""

_TRIGGERED_ROLE = """\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: test-triggered
spec:
  role: "You monitor things."
  model:
    provider: openai
    name: gpt-4o
    max_tokens: 4096
  guardrails:
    max_tool_calls: 2
  triggers:
    - type: heartbeat
      file: /tmp/heartbeat.txt
      interval_seconds: 3600
"""


@pytest.fixture()
def resolved_role(tmp_path: Path) -> Path:
    p = tmp_path / "resolved.yaml"
    p.write_text(_RESOLVED_ROLE)
    return p


@pytest.fixture()
def unresolved_role(tmp_path: Path) -> Path:
    p = tmp_path / "unresolved.yaml"
    p.write_text(_UNRESOLVED_ROLE)
    return p


@pytest.fixture()
def triggered_role(tmp_path: Path) -> Path:
    p = tmp_path / "triggered.yaml"
    p.write_text(_TRIGGERED_ROLE)
    return p


class TestEstimateRoleCost:
    def test_resolved_model(self, resolved_role: Path) -> None:
        est = estimate_role_cost_sync(resolved_role)
        assert est.model_resolved is True
        assert est.model == "gpt-4o"
        assert est.provider == "openai"
        assert est.estimated_input_tokens > 0
        assert est.estimated_output_tokens_typical > 0
        assert est.estimated_output_tokens_max == 4096
        # genai_prices should know gpt-4o
        assert est.per_run_typical is not None
        assert est.per_run_max is not None
        assert est.per_run_max >= est.per_run_typical

    def test_unresolved_model(self, unresolved_role: Path) -> None:
        est = estimate_role_cost_sync(unresolved_role)
        assert est.model_resolved is False
        assert est.per_run_typical is None
        assert est.per_run_max is None
        assert any("unresolved" in a.lower() for a in est.assumptions)

    def test_prompt_tokens_override(self, resolved_role: Path) -> None:
        default = estimate_role_cost_sync(resolved_role)
        custom = estimate_role_cost_sync(resolved_role, prompt_tokens=1000)
        assert custom.estimated_input_tokens > default.estimated_input_tokens

    def test_trigger_projections(self, triggered_role: Path) -> None:
        est = estimate_role_cost_sync(triggered_role)
        assert est.trigger_runs_per_day is not None
        assert est.trigger_runs_per_day == 24.0  # 86400 / 3600
        assert est.daily_estimate is not None
        assert est.monthly_estimate is not None

    def test_no_triggers_no_projections(self, resolved_role: Path) -> None:
        est = estimate_role_cost_sync(resolved_role)
        assert est.trigger_runs_per_day is None
        assert est.daily_estimate is None
        assert est.monthly_estimate is None

    def test_assumptions_populated(self, resolved_role: Path) -> None:
        est = estimate_role_cost_sync(resolved_role)
        assert len(est.assumptions) > 0
        assert any("skill" in a.lower() for a in est.assumptions)


class TestEstimateCLI:
    def test_estimate_command(self, resolved_role: Path) -> None:
        result = runner.invoke(app, ["estimate", str(resolved_role)])
        assert result.exit_code == 0
        assert "Cost Estimate" in result.output
        assert "gpt-4o" in result.output

    def test_estimate_missing_file(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["estimate", str(tmp_path / "nope.yaml")])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_estimate_with_prompt_tokens(self, resolved_role: Path) -> None:
        result = runner.invoke(app, ["estimate", str(resolved_role), "--prompt-tokens", "500"])
        assert result.exit_code == 0

    def test_estimate_unresolved_model(self, unresolved_role: Path) -> None:
        result = runner.invoke(app, ["estimate", str(unresolved_role)])
        assert result.exit_code == 0
        assert "unresolved" in result.output.lower()
