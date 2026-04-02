"""Reflection state for autonomous agent execution."""

from __future__ import annotations

from dataclasses import dataclass, field

from initrunner.agent.reasoning import TodoList


@dataclass
class ReflectionState:
    completed: bool = False
    summary: str = ""
    status: str = "completed"  # completed | blocked | failed
    plan_finalized: bool = False
    todo: TodoList = field(default_factory=TodoList)
    # Budget awareness (populated by autonomous runner each iteration)
    iterations_completed: int = 0
    max_iterations: int = 0
    tokens_consumed: int = 0
    token_budget: int | None = None
    elapsed_seconds: float = 0.0
    timeout_seconds: int | None = None

    def check_auto_complete(self) -> None:
        """Set completed=True if every todo item is terminal."""
        if self.todo.items and self.todo.is_all_done():
            self.completed = True
            self.status = "completed"


def format_reflection_state(state: ReflectionState) -> str:
    """Render state into a string for the continuation prompt.

    Injected into every continuation prompt so the agent always sees its
    current plan/progress, even after history trimming.
    """
    parts = [state.todo.format()]

    if state.max_iterations > 0:
        lines: list[str] = []
        pct = int(state.iterations_completed * 100 / state.max_iterations)
        lines.append(f"- Iteration: {state.iterations_completed}/{state.max_iterations} ({pct}%)")
        if state.token_budget is not None:
            pct_t = int(state.tokens_consumed * 100 / state.token_budget)
            lines.append(f"- Tokens: {state.tokens_consumed:,}/{state.token_budget:,} ({pct_t}%)")
        if state.timeout_seconds is not None:
            elapsed_int = int(state.elapsed_seconds)
            pct_e = int(state.elapsed_seconds * 100 / state.timeout_seconds)
            lines.append(f"- Time: {elapsed_int}s/{state.timeout_seconds}s ({pct_e}%)")
        parts.append("BUDGET:\n" + "\n".join(lines))

    return "\n\n".join(parts)
