"""Reflection tools for autonomous agent execution: finish_task and update_plan.

These tools are NOT registered via @register_tool. They are injected at
runtime via extra_toolsets so PydanticAI merges them with the agent's
pre-configured toolsets.
"""

from __future__ import annotations

from typing import Literal

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.reflection import PlanStep, ReflectionState
from initrunner.agent.schema import AutonomyConfig


def build_reflection_toolset(
    config: AutonomyConfig,
    state: ReflectionState,
) -> FunctionToolset:
    """Build the reflection tools: finish_task and update_plan."""
    max_plan_steps = config.max_plan_steps
    toolset = FunctionToolset()

    @toolset.tool
    def finish_task(
        summary: str,
        status: Literal["completed", "blocked", "failed"] = "completed",
    ) -> str:
        """Signal that the current task is done. Call this when you have completed
        the task, are blocked and cannot proceed, or have failed.

        Args:
            summary: A brief summary of what was accomplished or why blocked/failed.
            status: The outcome — completed, blocked, or failed.
        """
        state.completed = True
        state.summary = summary
        state.status = status
        return f"Task finished ({status})."

    @toolset.tool
    def update_plan(steps: list[dict[str, str]]) -> str:
        """Replace the current plan with a new list of steps. Each step should
        have a 'description' and optionally 'status' (pending/in_progress/completed/failed/skipped)
        and 'notes'.

        Args:
            steps: List of step dicts with keys: description, status (optional), notes (optional).
        """
        valid_statuses = {"pending", "in_progress", "completed", "failed", "skipped"}
        new_steps: list[PlanStep] = []
        for step_dict in steps[:max_plan_steps]:
            desc = step_dict.get("description", "")
            if not desc:
                continue
            step_status = step_dict.get("status", "pending")
            if step_status not in valid_statuses:
                step_status = "pending"
            notes = step_dict.get("notes", "")
            new_steps.append(PlanStep(description=desc, status=step_status, notes=notes))
        state.steps = new_steps

        counts: dict[str, int] = {}
        for s in new_steps:
            counts[s.status] = counts.get(s.status, 0) + 1
        parts = [f"{count} {status}" for status, count in sorted(counts.items())]
        return f"Plan updated: {', '.join(parts)}" if parts else "Plan cleared."

    return toolset
