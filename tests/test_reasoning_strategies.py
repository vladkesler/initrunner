"""Tests for reasoning strategy implementations."""

from __future__ import annotations

from initrunner.agent.reflection import ReflectionState
from initrunner.runner.reasoning import (
    PlanExecuteStrategy,
    ReactStrategy,
    ReflexionStrategy,
    TodoDrivenStrategy,
    resolve_strategy,
)


class TestReactStrategy:
    def test_wrap_initial_prompt_passthrough(self):
        s = ReactStrategy("Continue.")
        assert s.wrap_initial_prompt("Hello") == "Hello"

    def test_should_continue_when_not_completed(self):
        s = ReactStrategy("Continue.")
        state = ReflectionState()
        assert s.should_continue(state, 1) is True

    def test_should_stop_when_completed(self):
        s = ReactStrategy("Continue.")
        state = ReflectionState(completed=True)
        assert s.should_continue(state, 1) is False

    def test_post_completion_rounds_zero(self):
        s = ReactStrategy("Continue.")
        assert s.post_completion_rounds() == 0

    def test_continuation_prompt_includes_state(self):
        s = ReactStrategy("Keep going.")
        state = ReflectionState()
        state.todo.add("Task 1")
        prompt = s.build_continuation_prompt(state)
        assert "Keep going." in prompt
        assert "Task 1" in prompt


class TestTodoDrivenStrategy:
    def test_wrap_initial_prompt_with_auto_plan(self):
        s = TodoDrivenStrategy("Continue.", auto_plan=True)
        result = s.wrap_initial_prompt("Build a website")
        assert isinstance(result, str)
        assert "todo list" in result.lower()
        assert "Build a website" in result

    def test_wrap_initial_prompt_without_auto_plan(self):
        s = TodoDrivenStrategy("Continue.", auto_plan=False)
        result = s.wrap_initial_prompt("Build a website")
        assert result == "Build a website"

    def test_continuation_prompt_mentions_todo(self):
        s = TodoDrivenStrategy("Continue.")
        state = ReflectionState()
        prompt = s.build_continuation_prompt(state)
        assert "todo" in prompt.lower()


class TestPlanExecuteStrategy:
    def test_initial_prompt_is_planning_phase(self):
        s = PlanExecuteStrategy("Continue.")
        result = s.wrap_initial_prompt("Design a system")
        assert "PLANNING" in result
        assert "Design a system" in result

    def test_phase_transition(self):
        s = PlanExecuteStrategy("Continue.")
        state = ReflectionState()
        # First call: planning phase (no items yet)
        prompt1 = s.build_continuation_prompt(state)
        assert "planning" in prompt1.lower() or "Continue" in prompt1

        # Add items
        state.todo.add("Step 1")
        state.todo.add("Step 2")

        # Second call: still planning (items just added)
        s.build_continuation_prompt(state)

        # Third call: items unchanged, transition to execution
        prompt3 = s.build_continuation_prompt(state)
        assert "EXECUTION" in prompt3


class TestReflexionStrategy:
    def test_post_completion_rounds(self):
        s = ReflexionStrategy("Continue.", reflection_rounds=2)
        assert s.post_completion_rounds() == 2

    def test_reopens_after_first_completion(self):
        s = ReflexionStrategy("Continue.", reflection_rounds=1)
        state = ReflectionState(completed=True, summary="Done")
        # First check: should re-open for reflexion
        assert s.should_continue(state, 1) is True
        assert state.completed is False

    def test_stops_after_all_rounds(self):
        s = ReflexionStrategy("Continue.", reflection_rounds=1)
        state = ReflectionState(completed=True, summary="Done")
        # First completion -> re-opens for 1 round
        s.should_continue(state, 1)
        # Build a continuation prompt (increments reflexion count)
        s.build_continuation_prompt(state)
        # Second completion -> all rounds done
        state.completed = True
        assert s.should_continue(state, 2) is False

    def test_reflexion_prompt_includes_reflection(self):
        s = ReflexionStrategy("Continue.", reflection_rounds=1)
        state = ReflectionState(completed=True, summary="Initial work done")
        s.should_continue(state, 1)  # Re-open
        prompt = s.build_continuation_prompt(state)
        assert "REFLECTION" in prompt
        assert "Initial work done" in prompt


class TestResolveStrategy:
    def _make_role(self, tools=None, autonomy=None, reasoning=None):
        from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
        from initrunner.agent.schema.role import AgentSpec, RoleDefinition

        spec_kwargs = {
            "role": "",
            "model": ModelConfig(provider="openai", name="dummy"),
        }
        if tools:
            spec_kwargs["tools"] = tools
        if autonomy:
            spec_kwargs["autonomy"] = autonomy
        if reasoning:
            spec_kwargs["reasoning"] = reasoning

        return RoleDefinition(
            apiVersion=ApiVersion.V1,
            kind=Kind.AGENT,
            metadata=RoleMetadata(name="test", description=""),
            spec=AgentSpec(**spec_kwargs),  # type: ignore[arg-type]
        )

    def test_default_is_react(self):
        role = self._make_role()
        strategy = resolve_strategy(None, role)
        assert isinstance(strategy, ReactStrategy)

    def test_auto_detect_todo_driven(self):
        from initrunner.agent.schema.autonomy import AutonomyConfig
        from initrunner.agent.schema.tools import TodoToolConfig

        role = self._make_role(
            tools=[TodoToolConfig()],
            autonomy=AutonomyConfig(),
        )
        strategy = resolve_strategy(None, role)
        assert isinstance(strategy, TodoDrivenStrategy)

    def test_auto_detect_reflexion(self):
        from initrunner.agent.schema.reasoning import ReasoningConfig

        config = ReasoningConfig(reflection_rounds=1)
        role = self._make_role()
        strategy = resolve_strategy(config, role)
        assert isinstance(strategy, ReflexionStrategy)

    def test_explicit_pattern_overrides_auto(self):
        from initrunner.agent.schema.reasoning import ReasoningConfig

        config = ReasoningConfig(pattern="plan_execute", auto_detect=False)
        role = self._make_role()
        strategy = resolve_strategy(config, role)
        assert isinstance(strategy, PlanExecuteStrategy)
