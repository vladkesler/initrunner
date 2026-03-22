"""Reasoning strategies and run-scoped tool construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from initrunner.agent.reflection import ReflectionState
from initrunner.agent.schema.reasoning import ReasoningConfig
from initrunner.agent.schema.tools import TodoToolConfig

if TYPE_CHECKING:
    from pydantic_ai.toolsets import AbstractToolset

    from initrunner.agent.prompt import UserPrompt
    from initrunner.agent.schema.autonomy import AutonomyConfig
    from initrunner.agent.schema.role import RoleDefinition


# ---------------------------------------------------------------------------
# Strategy protocol
# ---------------------------------------------------------------------------


class ReasoningStrategy(Protocol):
    """Controls how the autonomous runner orchestrates agent reasoning."""

    def wrap_initial_prompt(self, prompt: UserPrompt) -> UserPrompt: ...

    def build_continuation_prompt(self, state: ReflectionState) -> str: ...

    def should_continue(self, state: ReflectionState, iteration: int) -> bool: ...

    def post_completion_rounds(self) -> int: ...


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------


class ReactStrategy:
    """Default ReAct: no extra orchestration."""

    def __init__(self, continuation_prompt: str) -> None:
        self._continuation = continuation_prompt

    def wrap_initial_prompt(self, prompt: UserPrompt) -> UserPrompt:
        return prompt

    def build_continuation_prompt(self, state: ReflectionState) -> str:
        from initrunner.agent.reflection import format_reflection_state

        state_text = format_reflection_state(state)
        return f"{self._continuation}\n\nCURRENT STATUS:\n{state_text}"

    def should_continue(self, state: ReflectionState, iteration: int) -> bool:
        return not state.completed

    def post_completion_rounds(self) -> int:
        return 0


class TodoDrivenStrategy:
    """Plan-first: create todo list, then work through items."""

    def __init__(self, continuation_prompt: str, auto_plan: bool = True) -> None:
        self._continuation = continuation_prompt
        self._auto_plan = auto_plan

    def wrap_initial_prompt(self, prompt: UserPrompt) -> UserPrompt:
        if not self._auto_plan:
            return prompt
        from initrunner.agent.prompt import extract_text_from_prompt

        text = extract_text_from_prompt(prompt)
        return (
            f"Before starting, create a structured todo list for this task using "
            f"add_todo or batch_add_todos. Assign priorities and dependencies. "
            f"Then begin working through items.\n\n{text}"
        )

    def build_continuation_prompt(self, state: ReflectionState) -> str:
        from initrunner.agent.reflection import format_reflection_state

        state_text = format_reflection_state(state)
        return (
            "Check your todo list. Call get_next_todo to find the next actionable "
            "item, work on it, then update its status. If all items are done, "
            "call finish_task with a summary.\n\n"
            f"CURRENT STATUS:\n{state_text}"
        )

    def should_continue(self, state: ReflectionState, iteration: int) -> bool:
        return not state.completed

    def post_completion_rounds(self) -> int:
        return 0


class PlanExecuteStrategy:
    """Two-phase: plan first, then execute."""

    def __init__(self, continuation_prompt: str) -> None:
        self._continuation = continuation_prompt
        self._phase: str = "planning"
        self._last_item_count: int = 0

    def wrap_initial_prompt(self, prompt: UserPrompt) -> UserPrompt:
        from initrunner.agent.prompt import extract_text_from_prompt

        text = extract_text_from_prompt(prompt)
        return (
            f"PHASE 1 - PLANNING: Analyze this task and create a comprehensive "
            f"todo list using batch_add_todos. Focus only on planning. "
            f"Do not execute yet.\n\n{text}"
        )

    def build_continuation_prompt(self, state: ReflectionState) -> str:
        from initrunner.agent.reflection import format_reflection_state

        state_text = format_reflection_state(state)
        current_count = len(state.todo.items)

        # Transition from planning to execution when items exist and no new ones added
        if (
            self._phase == "planning"
            and current_count > 0
            and current_count == self._last_item_count
        ):
            self._phase = "executing"

        self._last_item_count = current_count

        if self._phase == "planning":
            return (
                "Continue planning. Add more todo items if needed. When your plan "
                "is complete, the next iteration will begin execution.\n\n"
                f"CURRENT STATUS:\n{state_text}"
            )
        return (
            "PHASE 2 - EXECUTION: Work through your plan. Call get_next_todo, "
            "execute the item, update its status. Continue until all items are done.\n\n"
            f"CURRENT STATUS:\n{state_text}"
        )

    def should_continue(self, state: ReflectionState, iteration: int) -> bool:
        return not state.completed

    def post_completion_rounds(self) -> int:
        return 0


class ReflexionStrategy:
    """Post-completion self-critique rounds."""

    def __init__(self, continuation_prompt: str, reflection_rounds: int) -> None:
        self._continuation = continuation_prompt
        self._reflection_rounds = reflection_rounds
        self._base_completed = False
        self._reflexion_count = 0

    def wrap_initial_prompt(self, prompt: UserPrompt) -> UserPrompt:
        return prompt

    def build_continuation_prompt(self, state: ReflectionState) -> str:
        from initrunner.agent.reflection import format_reflection_state

        state_text = format_reflection_state(state)

        if self._base_completed:
            self._reflexion_count += 1
            return (
                f"REFLECTION ({self._reflexion_count}/{self._reflection_rounds}): "
                f"Review your work so far. What could be improved? "
                f"Are there errors or gaps? Make corrections if needed, then "
                f"call finish_task when satisfied.\n\n"
                f"Your previous summary: {state.summary}\n\n"
                f"CURRENT STATUS:\n{state_text}"
            )

        return f"{self._continuation}\n\nCURRENT STATUS:\n{state_text}"

    def should_continue(self, state: ReflectionState, iteration: int) -> bool:
        if not state.completed:
            return True
        if not self._base_completed:
            # First completion: start reflexion rounds
            self._base_completed = True
            if self._reflexion_count < self._reflection_rounds:
                state.completed = False  # Re-open for reflexion
                return True
            return False
        # In reflexion: continue if more rounds remain
        if self._reflexion_count < self._reflection_rounds:
            state.completed = False
            return True
        return False

    def post_completion_rounds(self) -> int:
        return self._reflection_rounds


# ---------------------------------------------------------------------------
# Strategy resolution
# ---------------------------------------------------------------------------


def resolve_strategy(
    config: ReasoningConfig | None,
    role: RoleDefinition,
) -> ReasoningStrategy:
    """Resolve the reasoning strategy from config + auto-detection."""
    continuation = "Continue working on the task."
    if role.spec.autonomy:
        continuation = role.spec.autonomy.continuation_prompt

    if config is None:
        config = ReasoningConfig()

    pattern = config.pattern
    has_todo = any(isinstance(t, TodoToolConfig) for t in role.spec.tools)

    # Auto-detection
    if config.auto_detect and pattern == "react":
        if has_todo and role.spec.autonomy is not None:
            pattern = "todo_driven"
        if config.reflection_rounds > 0:
            pattern = "reflexion"

    if pattern == "todo_driven":
        return TodoDrivenStrategy(continuation, auto_plan=config.auto_plan)
    if pattern == "plan_execute":
        return PlanExecuteStrategy(continuation)
    if pattern == "reflexion":
        return ReflexionStrategy(continuation, config.reflection_rounds)
    return ReactStrategy(continuation)


# ---------------------------------------------------------------------------
# Run-scoped toolset construction
# ---------------------------------------------------------------------------


def build_run_scoped_toolsets(
    role: RoleDefinition,
    reflection_state: ReflectionState,
    autonomy_config: AutonomyConfig | None = None,
) -> list[AbstractToolset]:
    """Build all run-scoped toolsets for a single agent run.

    Scans `role.spec.tools` for run-scoped configs and builds fresh
    toolsets with the provided state. Also builds a minimal finish_task
    toolset when no todo tool is configured.
    """
    from initrunner.agent.schema.tools import SpawnToolConfig, ThinkToolConfig, TodoToolConfig
    from initrunner.agent.tools._registry import ToolBuildContext, get_builder

    ctx = ToolBuildContext(role=role, role_dir=None)
    toolsets: list[AbstractToolset] = []
    has_todo = False

    for tool_config in role.spec.tools:
        if isinstance(tool_config, TodoToolConfig):
            has_todo = True
            builder = get_builder("todo")
            if builder:
                toolsets.append(builder(tool_config, ctx, reflection_state))

        elif isinstance(tool_config, ThinkToolConfig):
            builder = get_builder("think")
            if builder:
                toolsets.append(builder(tool_config, ctx))

        elif isinstance(tool_config, SpawnToolConfig):
            builder = get_builder("spawn")
            if builder:
                toolsets.append(builder(tool_config, ctx))

    # Always provide finish_task even without a todo tool
    if not has_todo:
        toolsets.append(_build_finish_task_toolset(reflection_state))

    return toolsets


def _build_finish_task_toolset(state: ReflectionState) -> AbstractToolset:
    """Minimal toolset with just finish_task for autonomous mode."""
    from pydantic_ai.toolsets.function import FunctionToolset

    toolset = FunctionToolset()

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
