"""Tests for autonomous agent execution (agentic loop)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from initrunner.agent.executor import AutonomousResult, RunResult
from initrunner.agent.history import trim_message_history
from initrunner.agent.reflection import (
    PlanStep,
    ReflectionState,
    format_reflection_state,
)
from initrunner.agent.schema import (
    AgentSpec,
    ApiVersion,
    AutonomyConfig,
    CronTriggerConfig,
    FileWatchTriggerConfig,
    Guardrails,
    Kind,
    Metadata,
    ModelConfig,
    RoleDefinition,
    WebhookTriggerConfig,
)


def _make_role(
    *,
    autonomy: AutonomyConfig | None = None,
    max_iterations: int = 10,
    autonomous_token_budget: int | None = None,
) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test agent.",
            model=ModelConfig(provider="openai", name="gpt-4o-mini"),
            autonomy=autonomy,
            guardrails=Guardrails(
                max_iterations=max_iterations,
                autonomous_token_budget=autonomous_token_budget,
            ),
        ),
    )


class TestAutonomyConfig:
    def test_defaults(self):
        config = AutonomyConfig()
        assert config.max_history_messages == 40
        assert config.max_plan_steps == 20
        assert config.iteration_delay_seconds == 0
        assert config.max_scheduled_per_run == 3
        assert config.max_scheduled_total == 50
        assert config.max_schedule_delay_seconds == 86400
        assert "finish_task" in config.continuation_prompt

    def test_custom_values(self):
        config = AutonomyConfig(
            max_history_messages=20,
            max_plan_steps=5,
            iteration_delay_seconds=1.0,
        )
        assert config.max_history_messages == 20
        assert config.max_plan_steps == 5
        assert config.iteration_delay_seconds == 1.0


class TestGuardrailsAutonomousFields:
    def test_max_iterations_default(self):
        g = Guardrails()
        assert g.max_iterations == 10

    def test_max_iterations_custom(self):
        g = Guardrails(max_iterations=20)
        assert g.max_iterations == 20

    def test_autonomous_token_budget_default_none(self):
        g = Guardrails()
        assert g.autonomous_token_budget is None

    def test_autonomous_token_budget_custom(self):
        g = Guardrails(autonomous_token_budget=100000)
        assert g.autonomous_token_budget == 100000

    def test_autonomous_timeout_seconds_default_none(self):
        g = Guardrails()
        assert g.autonomous_timeout_seconds is None

    def test_autonomous_timeout_seconds_custom(self):
        g = Guardrails(autonomous_timeout_seconds=1800)
        assert g.autonomous_timeout_seconds == 1800


class TestAutonomousWallClockTimeout:
    def test_timeout_terminates_loop(self):
        """Autonomous loop should terminate with 'timeout' when time limit is hit."""
        from unittest.mock import MagicMock, patch

        role = _make_role(max_iterations=100)
        # Set a very short timeout (1 second)
        role.spec.guardrails.autonomous_timeout_seconds = 1

        agent = MagicMock()

        # Make execute_run sleep so the timeout triggers
        call_count = 0

        def slow_execute_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            import time

            time.sleep(0.6)
            return (
                RunResult(run_id=f"r{call_count}", total_tokens=10, tool_calls=1),
                [],
            )

        with (
            patch("initrunner.runner.autonomous.execute_run", side_effect=slow_execute_run),
            patch("initrunner.runner.autonomous._display_autonomous_header"),
            patch("initrunner.runner.autonomous._display_iteration_result"),
            patch("initrunner.runner.autonomous._display_autonomous_summary"),
            patch("initrunner.runner.autonomous.console"),
        ):
            from initrunner.runner.autonomous import run_autonomous

            result = run_autonomous(agent, role, "do something")

        assert result.final_status == "timeout"
        assert result.iteration_count < 100


class TestTriggerAutonomousFlag:
    def test_cron_trigger_default(self):
        config = CronTriggerConfig(schedule="*/5 * * * *", prompt="check")
        assert config.autonomous is False

    def test_cron_trigger_autonomous(self):
        config = CronTriggerConfig(schedule="*/5 * * * *", prompt="check", autonomous=True)
        assert config.autonomous is True

    def test_file_watch_trigger_default(self):
        config = FileWatchTriggerConfig(paths=["/tmp"])
        assert config.autonomous is False

    def test_webhook_trigger_default(self):
        config = WebhookTriggerConfig()
        assert config.autonomous is False


class TestAgentSpecAutonomy:
    def test_autonomy_default_none(self):
        role = _make_role()
        assert role.spec.autonomy is None

    def test_autonomy_with_config(self):
        config = AutonomyConfig(max_plan_steps=5)
        role = _make_role(autonomy=config)
        assert role.spec.autonomy is not None
        assert role.spec.autonomy.max_plan_steps == 5


class TestAutonomousResult:
    def test_default_values(self):
        result = AutonomousResult(
            run_id="test-123",
            iterations=[],
        )
        assert result.run_id == "test-123"
        assert result.final_output == ""
        assert result.final_status == "completed"
        assert result.success is True
        assert result.error is None
        assert result.iteration_count == 0

    def test_with_iterations(self):
        r1 = RunResult(run_id="r1", tokens_in=10, tokens_out=5, total_tokens=15, tool_calls=2)
        r2 = RunResult(run_id="r2", tokens_in=20, tokens_out=10, total_tokens=30, tool_calls=1)
        result = AutonomousResult(
            run_id="auto-1",
            iterations=[r1, r2],
            total_tokens_in=30,
            total_tokens_out=15,
            total_tokens=45,
            total_tool_calls=3,
            iteration_count=2,
        )
        assert result.iteration_count == 2
        assert result.total_tokens == 45

    def test_error_status(self):
        result = AutonomousResult(
            run_id="auto-err",
            iterations=[],
            final_status="error",
            success=False,
            error="Something broke",
        )
        assert result.success is False
        assert result.error == "Something broke"


class TestTrimHistoryPreserveFirst:
    def test_preserves_first_message(self):
        from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

        msgs = [
            ModelRequest(parts=[UserPromptPart(content="original task")]),
            ModelResponse(parts=[TextPart(content="resp 1")]),
            ModelRequest(parts=[UserPromptPart(content="prompt 2")]),
            ModelResponse(parts=[TextPart(content="resp 2")]),
            ModelRequest(parts=[UserPromptPart(content="prompt 3")]),
            ModelResponse(parts=[TextPart(content="resp 3")]),
            ModelRequest(parts=[UserPromptPart(content="prompt 4")]),
            ModelResponse(parts=[TextPart(content="resp 4")]),
        ]

        trimmed = trim_message_history(msgs, 4, preserve_first=True)
        assert len(trimmed) <= 4
        # First message should be preserved
        first_part = trimmed[0].parts[0]
        assert isinstance(first_part, UserPromptPart)
        assert first_part.content == "original task"

    def test_no_trim_when_under_limit(self):
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        msgs = [
            ModelRequest(parts=[UserPromptPart(content="msg 1")]),
            ModelRequest(parts=[UserPromptPart(content="msg 2")]),
        ]
        result = trim_message_history(msgs, 10, preserve_first=True)
        assert len(result) == 2

    def test_preserve_first_false_default(self):
        from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

        msgs = [
            ModelRequest(parts=[UserPromptPart(content="first")]),
            ModelResponse(parts=[TextPart(content="r1")]),
            ModelRequest(parts=[UserPromptPart(content="second")]),
            ModelResponse(parts=[TextPart(content="r2")]),
            ModelRequest(parts=[UserPromptPart(content="third")]),
        ]
        result = trim_message_history(msgs, 3)
        # Default: no preservation of first
        assert len(result) <= 3


class TestReflectionStateIntegration:
    def test_state_persists_across_mutations(self):
        """ReflectionState should be mutable across iterations."""
        state = ReflectionState()

        # Iteration 1: create plan
        state.steps = [
            PlanStep(description="Step 1", status="in_progress"),
            PlanStep(description="Step 2", status="pending"),
        ]

        # Iteration 2: update progress
        state.steps[0].status = "completed"
        state.steps[1].status = "in_progress"

        formatted = format_reflection_state(state)
        assert "Step 1 (completed)" in formatted
        assert "Step 2 (in_progress)" in formatted

        # Iteration 3: finish
        state.completed = True
        state.summary = "All done"
        assert state.completed is True

    def test_format_state_shows_notes(self):
        state = ReflectionState(
            steps=[
                PlanStep(description="Research", status="completed", notes="Found 3 sources"),
            ]
        )
        result = format_reflection_state(state)
        assert "Found 3 sources" in result


class TestAutonomousRoleValidation:
    def test_role_with_full_autonomy(self, tmp_path: Path):
        """A role YAML with autonomy config should parse correctly."""
        yaml_content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: auto-agent
              description: An autonomous agent
            spec:
              role: You are a research agent.
              model:
                provider: openai
                name: gpt-4o-mini
              autonomy:
                max_plan_steps: 10
                max_history_messages: 30
                iteration_delay_seconds: 0.5
              guardrails:
                max_iterations: 15
                autonomous_token_budget: 200000
        """)
        from initrunner.agent.schema import RoleDefinition

        role = RoleDefinition.model_validate(__import__("yaml").safe_load(yaml_content))
        assert role.spec.autonomy is not None
        assert role.spec.autonomy.max_plan_steps == 10
        assert role.spec.guardrails.max_iterations == 15
        assert role.spec.guardrails.autonomous_token_budget == 200000

    def test_trigger_with_autonomous_flag(self):
        """Trigger configs should accept autonomous flag."""
        import yaml

        raw = yaml.safe_load(
            textwrap.dedent("""\
            type: cron
            schedule: "*/10 * * * *"
            prompt: "Check for updates"
            autonomous: true
        """)
        )
        config = CronTriggerConfig.model_validate(raw)
        assert config.autonomous is True


class TestRunAutonomousCLIValidation:
    """Test CLI validation for autonomous mode flags."""

    def test_autonomous_requires_prompt(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["run", "nonexistent.yaml", "--autonomous"])
        assert result.exit_code != 0
        assert "requires --prompt" in result.output or result.exit_code == 1

    def test_autonomous_and_interactive_exclusive(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(
            app, ["run", "nonexistent.yaml", "--autonomous", "--interactive", "-p", "test"]
        )
        assert result.exit_code != 0
