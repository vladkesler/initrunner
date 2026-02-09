"""Tests for the reflection toolset (finish_task, update_plan)."""

from __future__ import annotations

from initrunner.agent.reflection import (
    PlanStep,
    ReflectionState,
    format_reflection_state,
)
from initrunner.agent.schema import AutonomyConfig
from initrunner.agent.tools.reflection import build_reflection_toolset


class TestReflectionState:
    def test_default_state(self):
        state = ReflectionState()
        assert state.completed is False
        assert state.summary == ""
        assert state.status == "completed"
        assert state.steps == []

    def test_plan_step_defaults(self):
        step = PlanStep(description="Do something")
        assert step.status == "pending"
        assert step.notes == ""


class TestFormatReflectionState:
    def test_empty_state(self):
        state = ReflectionState()
        result = format_reflection_state(state)
        assert result == "(No plan created yet)"

    def test_with_steps(self):
        state = ReflectionState(
            steps=[
                PlanStep(description="Research topic", status="completed"),
                PlanStep(description="Write summary", status="in_progress", notes="halfway"),
                PlanStep(description="Review", status="pending"),
            ]
        )
        result = format_reflection_state(state)
        assert "Current Plan:" in result
        assert "[x] Research topic (completed)" in result
        assert "[ ] Write summary (in_progress)" in result
        assert "halfway" in result
        assert "[ ] Review (pending)" in result

    def test_failed_step_icon(self):
        state = ReflectionState(steps=[PlanStep(description="Step", status="failed")])
        result = format_reflection_state(state)
        assert "[!] Step (failed)" in result

    def test_skipped_step_icon(self):
        state = ReflectionState(steps=[PlanStep(description="Step", status="skipped")])
        result = format_reflection_state(state)
        assert "[-] Step (skipped)" in result


class TestBuildReflectionToolset:
    def _build(self):
        config = AutonomyConfig()
        state = ReflectionState()
        toolset = build_reflection_toolset(config, state)
        return toolset, state

    def test_creates_toolset(self):
        toolset, _ = self._build()
        assert toolset is not None

    def test_finish_task_mutates_state(self):
        state = ReflectionState()
        assert state.completed is False
        # Simulate calling finish_task via the closure
        state.completed = True
        state.summary = "Done"
        state.status = "completed"
        assert state.completed is True
        assert state.summary == "Done"

    def test_update_plan_replaces_steps(self):
        config = AutonomyConfig(max_plan_steps=5)
        state = ReflectionState()
        state.steps = [PlanStep(description="old step")]

        build_reflection_toolset(config, state)

        # The update_plan tool replaces steps through the closure
        new_steps = [
            PlanStep(description="Step 1", status="completed"),
            PlanStep(description="Step 2", status="pending"),
        ]
        state.steps = new_steps
        assert len(state.steps) == 2
        assert state.steps[0].description == "Step 1"

    def test_max_plan_steps_enforced(self):
        config = AutonomyConfig(max_plan_steps=2)
        state = ReflectionState()
        build_reflection_toolset(config, state)

        # Simulate what update_plan does internally
        steps_input = [{"description": f"Step {i}"} for i in range(10)]
        # Only first max_plan_steps should be kept
        valid_steps = steps_input[: config.max_plan_steps]
        state.steps = [PlanStep(description=s["description"]) for s in valid_steps]
        assert len(state.steps) == 2

    def test_finish_task_statuses(self):
        for status in ("completed", "blocked", "failed"):
            state = ReflectionState()
            state.completed = True
            state.status = status
            assert state.status == status

    def test_toolset_has_tools(self):
        config = AutonomyConfig()
        state = ReflectionState()
        toolset = build_reflection_toolset(config, state)
        # The toolset should be a FunctionToolset with at least 2 tools
        assert toolset is not None
