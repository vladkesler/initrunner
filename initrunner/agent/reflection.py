"""Reflection state for autonomous agent execution."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlanStep:
    description: str
    status: str = "pending"  # pending | in_progress | completed | failed | skipped
    notes: str = ""


@dataclass
class ReflectionState:
    completed: bool = False
    summary: str = ""
    status: str = "completed"  # completed | blocked | failed
    steps: list[PlanStep] = field(default_factory=list)


def format_reflection_state(state: ReflectionState) -> str:
    """Render state into a string for the continuation prompt.

    Injected into every continuation prompt so the agent always sees its
    current plan/progress, even after history trimming.
    """
    if not state.steps:
        return "(No plan created yet)"
    lines = ["Current Plan:"]
    for i, step in enumerate(state.steps):
        icons = {"completed": "x", "failed": "!", "skipped": "-"}
        icon = icons.get(step.status, " ")
        lines.append(f"  {i + 1}. [{icon}] {step.description} ({step.status})")
        if step.notes:
            lines.append(f"       {step.notes}")
    return "\n".join(lines)
