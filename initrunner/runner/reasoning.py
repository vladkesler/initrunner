"""Reasoning strategies and run-scoped tool construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from initrunner._log import get_logger
from initrunner.agent.reflection import ReflectionState
from initrunner.agent.schema.reasoning import (
    DEFAULT_REFLEXION_DIMENSIONS,
    ReasoningConfig,
    ReflexionDimension,
)
from initrunner.agent.schema.tools import TodoToolConfig
from initrunner.eval.judge import run_judge_sync

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

    def build_strategy_toolsets(self, state: ReflectionState) -> list[AbstractToolset]: ...


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

    def build_strategy_toolsets(self, state: ReflectionState) -> list[AbstractToolset]:
        return []


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

    def build_strategy_toolsets(self, state: ReflectionState) -> list[AbstractToolset]:
        return []


class PlanExecuteStrategy:
    """Two-phase: plan first, then execute via explicit finalize_plan() tool."""

    def __init__(self, continuation_prompt: str) -> None:
        self._continuation = continuation_prompt

    def wrap_initial_prompt(self, prompt: UserPrompt) -> UserPrompt:
        from initrunner.agent.prompt import extract_text_from_prompt

        text = extract_text_from_prompt(prompt)
        return (
            f"PHASE 1 - PLANNING: Analyze this task and create a comprehensive "
            f"todo list using batch_add_todos. Focus only on planning. "
            f"Do not execute yet. When your plan is complete, call "
            f"finalize_plan().\n\n{text}"
        )

    def build_continuation_prompt(self, state: ReflectionState) -> str:
        from initrunner.agent.reflection import format_reflection_state

        state_text = format_reflection_state(state)

        if state.plan_finalized:
            return (
                "PHASE 2 - EXECUTION: Work through your plan. Call get_next_todo, "
                "execute the item, update its status. Continue until all items "
                "are done.\n\n"
                f"CURRENT STATUS:\n{state_text}"
            )
        return (
            "Continue planning. Add more todo items if needed. When your plan "
            "is complete, call finalize_plan() to begin execution.\n\n"
            f"CURRENT STATUS:\n{state_text}"
        )

    def should_continue(self, state: ReflectionState, iteration: int) -> bool:
        return not state.completed

    def post_completion_rounds(self) -> int:
        return 0

    def build_strategy_toolsets(self, state: ReflectionState) -> list[AbstractToolset]:
        from pydantic_ai.toolsets.function import FunctionToolset

        toolset = FunctionToolset()

        @toolset.tool_plain
        def finalize_plan() -> str:
            """Signal that planning is complete and execution should begin.

            Call this after you have added all todo items and are satisfied
            with the plan. The next iteration will switch to execution phase.
            """
            if not state.todo.items:
                return "Create at least one todo item before finalizing the plan."
            state.plan_finalized = True
            return "Plan finalized. Switching to execution phase."

        return [toolset]


_MAX_CONSECUTIVE_JUDGE_FAILURES = 2


class ReflexionStrategy:
    """Post-completion self-critique rounds, optionally gated by an eval judge.

    When ``success_criteria`` are supplied, each reflexion round runs an
    LLM-as-judge against the latest summary before composing the next prompt.
    A round that passes every criterion is recorded as verified and the loop
    advances to the next dimension (or finishes early once all rounds clear).
    A round that fails injects the per-criterion reasons into the next prompt
    so the agent can address them directly. The judge call is best-effort: if
    it raises, the round falls back to the plain dimension prompt, and after
    two consecutive judge failures the judge is disabled for the rest of the
    run so a broken judge cannot stall reflexion.
    """

    def __init__(
        self,
        continuation_prompt: str,
        reflection_rounds: int,
        dimensions: list[ReflexionDimension],
        success_criteria: list[str] | None = None,
        judge_model: str = "openai:gpt-4o-mini",
    ) -> None:
        self._continuation = continuation_prompt
        self._reflection_rounds = reflection_rounds
        self._dimensions = dimensions
        self._success_criteria = success_criteria
        self._judge_model = judge_model
        self._base_completed = False
        self._reflexion_count = 0
        self._consecutive_judge_failures = 0
        self._judge_disabled = False

    def wrap_initial_prompt(self, prompt: UserPrompt) -> UserPrompt:
        return prompt

    def build_continuation_prompt(self, state: ReflectionState) -> str:
        from initrunner.agent.reflection import format_reflection_state

        state_text = format_reflection_state(state)

        if not self._base_completed:
            return f"{self._continuation}\n\nCURRENT STATUS:\n{state_text}"

        if self._success_criteria and not self._judge_disabled:
            verified_prompt = self._verify_and_build(state, state_text)
            if verified_prompt is not None:
                return verified_prompt

        return self._build_dimension_prompt(state, state_text)

    def _verify_and_build(self, state: ReflectionState, state_text: str) -> str | None:
        """Run the judge and, on a passing verdict, build the verified prompt.

        Returns the verified-round prompt when all criteria pass, or ``None``
        to signal the caller should fall through to the plain dimension prompt
        (criteria failed, or the judge raised). Stores every verdict on
        ``state.judge_verdicts`` for auditing.
        """
        assert self._success_criteria is not None
        try:
            verdict = run_judge_sync(state.summary, self._success_criteria, self._judge_model)
        except Exception as e:
            self._consecutive_judge_failures += 1
            if self._consecutive_judge_failures >= _MAX_CONSECUTIVE_JUDGE_FAILURES:
                self._judge_disabled = True
            get_logger("reasoning").warning(
                "Reflexion judge evaluation failed: %s. Continuing with dimension prompt.", e
            )
            return None

        self._consecutive_judge_failures = 0
        state.judge_verdicts.append(
            {
                "round": self._reflexion_count + 1,
                "all_passed": verdict.all_passed,
                "criteria_results": [
                    {"criterion": cr.criterion, "passed": cr.passed, "reason": cr.reason}
                    for cr in verdict.criteria_results
                ],
            }
        )

        if not verdict.all_passed:
            return None

        # Verified: advance the round counter past this dimension.
        self._reflexion_count += 1
        if self._reflexion_count >= self._reflection_rounds:
            state.completed = True
            return (
                "All verification criteria passed. The task is verified as complete. "
                "Call finish_task to confirm.\n\n"
                f"CURRENT STATUS:\n{state_text}"
            )

        dim = self._dimensions[self._reflexion_count % len(self._dimensions)]
        return (
            f"REFLECTION ({self._reflexion_count + 1}/{self._reflection_rounds}) "
            f"-- {dim.name.upper()} [VERIFIED]:\n"
            f"{dim.prompt}\n\n"
            "The previous round passed every verification criterion. "
            "Continue to the next dimension, then call finish_task when satisfied.\n\n"
            f"Your previous summary: {state.summary}\n\n"
            f"CURRENT STATUS:\n{state_text}"
        )

    def _build_dimension_prompt(self, state: ReflectionState, state_text: str) -> str:
        self._reflexion_count += 1
        dim = self._dimensions[(self._reflexion_count - 1) % len(self._dimensions)]
        judge_context = self._format_failed_criteria(state)
        return (
            f"REFLECTION ({self._reflexion_count}/{self._reflection_rounds}) "
            f"-- {dim.name.upper()}:\n"
            f"{dim.prompt}\n\n"
            f"Make corrections if needed, then call finish_task when satisfied."
            f"{judge_context}\n\n"
            f"Your previous summary: {state.summary}\n\n"
            f"CURRENT STATUS:\n{state_text}"
        )

    @staticmethod
    def _format_failed_criteria(state: ReflectionState) -> str:
        """Render the most recent failed-criteria reasons for the agent."""
        if not state.judge_verdicts:
            return ""
        last = state.judge_verdicts[-1]
        if last.get("all_passed"):
            return ""
        failed = [cr for cr in last.get("criteria_results", []) if not cr.get("passed")]
        if not failed:
            return ""
        lines = ["\n\nJudge feedback on the previous round:"]
        for cr in failed:
            lines.append(f"- {cr['criterion']}: {cr['reason']}")
        lines.append("Address these issues in your revision.")
        return "\n".join(lines)

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

    def build_strategy_toolsets(self, state: ReflectionState) -> list[AbstractToolset]:
        return []


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
        if config.reflection_dimensions is not None:
            dims = list(config.reflection_dimensions)
        else:
            dims = DEFAULT_REFLEXION_DIMENSIONS[: config.reflection_rounds]
        return ReflexionStrategy(
            continuation,
            config.reflection_rounds,
            dims,
            success_criteria=config.success_criteria,
            judge_model=_resolve_judge_model(role),
        )
    return ReactStrategy(continuation)


_DEFAULT_JUDGE_MODEL = "openai:gpt-4o-mini"


def _resolve_judge_model(role: RoleDefinition) -> str:
    """Pick the judge model for verified reflexion.

    Reuses the role's own configured model so verification stays on the same
    provider the agent already authenticates against, falling back to a small
    default only when the role leaves its model unset.
    """
    model = role.spec.model
    if model is not None and model.is_resolved():
        return model.to_model_string()
    return _DEFAULT_JUDGE_MODEL


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
    from initrunner.agent.runtime_sandbox import resolve_backend
    from initrunner.agent.schema.tools import (
        ClarifyToolConfig,
        SpawnToolConfig,
        ThinkToolConfig,
        TodoToolConfig,
    )
    from initrunner.agent.tools._registry import ToolBuildContext, get_builder

    backend = resolve_backend(role.spec.security.sandbox, agent_name=role.metadata.name)
    ctx = ToolBuildContext(role=role, role_dir=None, sandbox_backend=backend)
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

        elif isinstance(tool_config, ClarifyToolConfig):
            builder = get_builder("clarify")
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
