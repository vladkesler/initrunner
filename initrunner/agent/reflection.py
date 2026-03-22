"""Reflection state for autonomous agent execution."""

from __future__ import annotations

from dataclasses import dataclass, field

from initrunner.agent.reasoning import TodoList


@dataclass
class ReflectionState:
    completed: bool = False
    summary: str = ""
    status: str = "completed"  # completed | blocked | failed
    todo: TodoList = field(default_factory=TodoList)

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
    return state.todo.format()
