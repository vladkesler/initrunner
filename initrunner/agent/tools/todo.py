"""Todo tool: priority-aware task management with dependency resolution."""

from __future__ import annotations

from typing import Literal

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.reflection import ReflectionState
from initrunner.agent.schema.tools import TodoToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool


@register_tool("todo", TodoToolConfig, run_scoped=True)
def build_todo_toolset(
    config: TodoToolConfig,
    ctx: ToolBuildContext,
    state: ReflectionState,
) -> FunctionToolset:
    """Build the todo toolset operating on the unified ReflectionState."""
    state.todo.max_items = config.max_items
    toolset = FunctionToolset()

    def _after_mutation() -> str:
        state.check_auto_complete()
        return state.todo.format()

    @toolset.tool_plain
    def add_todo(
        description: str,
        priority: str = "medium",
        depends_on: list[str] | None = None,
    ) -> str:
        """Create a new todo item.

        Args:
            description: What needs to be done.
            priority: critical, high, medium, or low.
            depends_on: List of todo IDs that must complete first.
        """
        item = state.todo.add(description, priority, depends_on)
        return f"Added: {item.id}\n{_after_mutation()}"

    @toolset.tool_plain
    def batch_add_todos(items: list[dict]) -> str:
        """Create multiple todo items at once.

        Each item: {description, priority?, depends_on?}.
        Use batch index ("0", "1", ...) in depends_on to reference items
        within the same batch.

        Args:
            items: List of todo item specifications.
        """
        created = state.todo.batch_add(items)
        ids = ", ".join(item.id for item in created)
        return f"Added {len(created)} items: {ids}\n{_after_mutation()}"

    @toolset.tool_plain
    def update_todo(
        item_id: str,
        status: str | None = None,
        notes: str | None = None,
        priority: str | None = None,
    ) -> str:
        """Update an existing todo item.

        Args:
            item_id: The ID of the todo item.
            status: pending, in_progress, completed, failed, or skipped.
            notes: Additional notes.
            priority: critical, high, medium, or low.
        """
        kwargs: dict[str, str] = {}
        if status is not None:
            kwargs["status"] = status
        if notes is not None:
            kwargs["notes"] = notes
        if priority is not None:
            kwargs["priority"] = priority
        state.todo.update(item_id, **kwargs)
        return _after_mutation()

    @toolset.tool_plain
    def remove_todo(item_id: str) -> str:
        """Remove a todo item.

        Args:
            item_id: The ID of the todo item to remove.
        """
        state.todo.remove(item_id)
        return _after_mutation()

    @toolset.tool_plain
    def list_todos(status_filter: str | None = None) -> str:
        """List all todo items, optionally filtered by status.

        Args:
            status_filter: Only show items with this status (pending, in_progress, etc).
        """
        if status_filter is None:
            return state.todo.format()
        items = [item for item in state.todo.items.values() if item.status == status_filter]
        if not items:
            return f"No items with status '{status_filter}'."
        lines = [f"Todo items ({status_filter}):"]
        for item in items:
            lines.append(f"  {item.id} [{item.priority}] {item.description}")
        return "\n".join(lines)

    @toolset.tool_plain
    def get_next_todo() -> str:
        """Get the next actionable todo item based on priority and dependencies."""
        item = state.todo.get_next()
        if item is None:
            if state.todo.is_all_done():
                return "All todo items are done."
            return "No actionable items (pending items have unfinished dependencies)."
        return (
            f"Next: {item.id} [{item.priority}] {item.description}"
            f"{' (notes: ' + item.notes + ')' if item.notes else ''}"
        )

    @toolset.tool_plain
    def finish_task(
        summary: str,
        status: Literal["completed", "blocked", "failed"] = "completed",
    ) -> str:
        """Signal that the current task is done.

        Args:
            summary: A brief summary of what was accomplished or why blocked/failed.
            status: The outcome -- completed, blocked, or failed.
        """
        state.completed = True
        state.summary = summary
        state.status = status
        return f"Task finished ({status})."

    return toolset
