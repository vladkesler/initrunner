"""Tests for reasoning strategy implementations."""

from __future__ import annotations

import pytest

from initrunner.agent.reflection import ReflectionState
from initrunner.agent.schema.reasoning import (
    DEFAULT_REFLEXION_DIMENSIONS,
    ReasoningConfig,
    ReflexionDimension,
)
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
        assert "finalize_plan" in result

    def test_phase_transition(self):
        s = PlanExecuteStrategy("Continue.")
        state = ReflectionState()

        # Add items -- still planning
        state.todo.add("Step 1")
        state.todo.add("Step 2")
        prompt1 = s.build_continuation_prompt(state)
        assert "EXECUTION" not in prompt1
        assert "finalize_plan" in prompt1

        # Finalize the plan
        state.plan_finalized = True
        prompt2 = s.build_continuation_prompt(state)
        assert "EXECUTION" in prompt2

    def test_no_transition_without_finalize(self):
        s = PlanExecuteStrategy("Continue.")
        state = ReflectionState()
        state.todo.add("Step 1")
        # Stable count across many iterations -- should NOT transition
        for _ in range(5):
            prompt = s.build_continuation_prompt(state)
            assert "EXECUTION" not in prompt

    def test_finalize_plan_tool(self):
        s = PlanExecuteStrategy("Continue.")
        state = ReflectionState()
        state.todo.add("Step 1")
        toolsets = s.build_strategy_toolsets(state)
        assert len(toolsets) == 1
        assert "finalize_plan" in toolsets[0].tools  # type: ignore[union-attr]

    def test_finalize_plan_rejects_empty(self):
        s = PlanExecuteStrategy("Continue.")
        state = ReflectionState()
        toolsets = s.build_strategy_toolsets(state)
        result = toolsets[0].tools["finalize_plan"].function()  # type: ignore[union-attr]
        assert state.plan_finalized is False
        assert "at least one todo" in result.lower()

    def test_finalize_plan_accepts_nonempty(self):
        s = PlanExecuteStrategy("Continue.")
        state = ReflectionState()
        state.todo.add("Step 1")
        toolsets = s.build_strategy_toolsets(state)
        result = toolsets[0].tools["finalize_plan"].function()  # type: ignore[union-attr]
        assert state.plan_finalized is True
        assert "finalized" in result.lower()


class TestReflexionStrategy:
    def _default_dims(self, n: int = 1) -> list[ReflexionDimension]:
        return DEFAULT_REFLEXION_DIMENSIONS[:n]

    def test_post_completion_rounds(self):
        s = ReflexionStrategy("Continue.", reflection_rounds=2, dimensions=self._default_dims(2))
        assert s.post_completion_rounds() == 2

    def test_reopens_after_first_completion(self):
        s = ReflexionStrategy("Continue.", reflection_rounds=1, dimensions=self._default_dims(1))
        state = ReflectionState(completed=True, summary="Done")
        # First check: should re-open for reflexion
        assert s.should_continue(state, 1) is True
        assert state.completed is False

    def test_stops_after_all_rounds(self):
        s = ReflexionStrategy("Continue.", reflection_rounds=1, dimensions=self._default_dims(1))
        state = ReflectionState(completed=True, summary="Done")
        # First completion -> re-opens for 1 round
        s.should_continue(state, 1)
        # Build a continuation prompt (increments reflexion count)
        s.build_continuation_prompt(state)
        # Second completion -> all rounds done
        state.completed = True
        assert s.should_continue(state, 2) is False

    def test_reflexion_prompt_includes_reflection(self):
        s = ReflexionStrategy("Continue.", reflection_rounds=1, dimensions=self._default_dims(1))
        state = ReflectionState(completed=True, summary="Initial work done")
        s.should_continue(state, 1)  # Re-open
        prompt = s.build_continuation_prompt(state)
        assert "REFLECTION" in prompt
        assert "Initial work done" in prompt

    def test_dimension_specific_prompt_content(self):
        dims = [
            ReflexionDimension(name="accuracy", prompt="Verify all numbers and dates."),
            ReflexionDimension(name="tone", prompt="Check the writing tone is professional."),
        ]
        s = ReflexionStrategy("Continue.", reflection_rounds=2, dimensions=dims)
        state = ReflectionState(completed=True, summary="Draft done")
        s.should_continue(state, 1)  # Re-open

        p1 = s.build_continuation_prompt(state)
        assert "ACCURACY" in p1
        assert "Verify all numbers and dates." in p1

        state.completed = True
        s.should_continue(state, 2)
        p2 = s.build_continuation_prompt(state)
        assert "TONE" in p2
        assert "Check the writing tone is professional." in p2

    def test_dimension_cycling(self):
        dims = [ReflexionDimension(name="focus", prompt="Stay on topic.")]
        s = ReflexionStrategy("Continue.", reflection_rounds=2, dimensions=dims)
        state = ReflectionState(completed=True, summary="Done")
        s.should_continue(state, 1)

        p1 = s.build_continuation_prompt(state)
        assert "FOCUS" in p1

        state.completed = True
        s.should_continue(state, 2)
        p2 = s.build_continuation_prompt(state)
        assert "FOCUS" in p2
        assert "2/2" in p2

    def test_default_dimensions_used(self):
        config = ReasoningConfig(reflection_rounds=2)
        role = _make_test_role()
        strategy = resolve_strategy(config, role)
        assert isinstance(strategy, ReflexionStrategy)
        state = ReflectionState(completed=True, summary="Done")
        strategy.should_continue(state, 1)

        p1 = strategy.build_continuation_prompt(state)
        assert "CORRECTNESS" in p1

        state.completed = True
        strategy.should_continue(state, 2)
        p2 = strategy.build_continuation_prompt(state)
        assert "COMPLETENESS" in p2

    def test_backward_compat_prompt_format(self):
        s = ReflexionStrategy("Continue.", reflection_rounds=1, dimensions=self._default_dims(1))
        state = ReflectionState(completed=True, summary="My summary")
        s.should_continue(state, 1)
        prompt = s.build_continuation_prompt(state)
        assert "REFLECTION (1/1)" in prompt
        assert "My summary" in prompt
        assert "finish_task" in prompt


class TestStrategyToolsets:
    def test_react_no_strategy_toolsets(self):
        s = ReactStrategy("Continue.")
        state = ReflectionState()
        assert s.build_strategy_toolsets(state) == []

    def test_todo_driven_no_strategy_toolsets(self):
        s = TodoDrivenStrategy("Continue.")
        state = ReflectionState()
        assert s.build_strategy_toolsets(state) == []

    def test_reflexion_no_strategy_toolsets(self):
        s = ReflexionStrategy(
            "Continue.",
            reflection_rounds=1,
            dimensions=DEFAULT_REFLEXION_DIMENSIONS[:1],
        )
        state = ReflectionState()
        assert s.build_strategy_toolsets(state) == []


class TestBudgetInContinuationPrompt:
    def test_continuation_prompt_includes_budget(self):
        s = ReactStrategy("Keep going.")
        state = ReflectionState(
            iterations_completed=4,
            max_iterations=10,
            tokens_consumed=30000,
            token_budget=100000,
        )
        prompt = s.build_continuation_prompt(state)
        assert "BUDGET:" in prompt
        assert "Iteration: 4/10 (40%)" in prompt
        assert "Tokens: 30,000/100,000 (30%)" in prompt


def _make_test_role(tools=None, autonomy=None, reasoning=None):
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


class TestResolveStrategy:
    def _make_role(self, tools=None, autonomy=None, reasoning=None):
        return _make_test_role(tools, autonomy, reasoning)

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

    def test_custom_dimensions_in_resolve(self):
        dims = [
            ReflexionDimension(name="security", prompt="Check for vulnerabilities."),
        ]
        config = ReasoningConfig(reflection_dimensions=dims)
        role = self._make_role()
        strategy = resolve_strategy(config, role)
        assert isinstance(strategy, ReflexionStrategy)
        state = ReflectionState(completed=True, summary="Done")
        strategy.should_continue(state, 1)
        prompt = strategy.build_continuation_prompt(state)
        assert "SECURITY" in prompt
        assert "Check for vulnerabilities." in prompt


class TestReflexionDimensions:
    def test_dimensions_auto_set_rounds(self):
        dims = [
            ReflexionDimension(name="a", prompt="Check A."),
            ReflexionDimension(name="b", prompt="Check B."),
        ]
        config = ReasoningConfig(reflection_dimensions=dims)
        assert config.reflection_rounds == 2

    def test_rounds_without_dimensions(self):
        config = ReasoningConfig(reflection_rounds=2)
        assert config.reflection_dimensions is None

    def test_empty_dimensions_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            ReasoningConfig(reflection_dimensions=[])

    def test_more_than_3_dimensions_raises(self):
        dims = [ReflexionDimension(name=f"d{i}", prompt=f"P{i}") for i in range(4)]
        with pytest.raises(ValueError, match="Maximum 3"):
            ReasoningConfig(reflection_dimensions=dims)

    def test_blank_name_raises(self):
        with pytest.raises(ValueError):
            ReflexionDimension(name="", prompt="Check something.")

    def test_blank_prompt_raises(self):
        with pytest.raises(ValueError):
            ReflexionDimension(name="test", prompt="")

    def test_rounds_and_dimensions_both_set(self):
        dims = [
            ReflexionDimension(name="a", prompt="Check A."),
            ReflexionDimension(name="b", prompt="Check B."),
        ]
        config = ReasoningConfig(reflection_rounds=2, reflection_dimensions=dims)
        assert config.reflection_rounds == 2
        assert config.reflection_dimensions is not None
        assert len(config.reflection_dimensions) == 2
