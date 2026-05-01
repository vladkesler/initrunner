"""Per-run cumulative token budget for one-shot CLI mode.

Reuses ``DaemonTokenTracker`` to cap total tokens spent across one
``initrunner run`` invocation, including inline-delegated sub-agents.

The tracker is shared across the parent run and any inline delegate
tool calls via a ``ContextVar``. ``ContextVar`` is required (not
``threading.local``) because ``_run_with_timeout`` submits the model
call to a ``ThreadPoolExecutor`` and propagates state via
``contextvars.copy_context()`` (see ``agent/executor_retry.py``); a
thread-local set in the CLI thread would be invisible inside the
delegate tool that fires from a pool worker.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

from initrunner.runner.budget import DaemonTokenTracker

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition

_run_budget: ContextVar[DaemonTokenTracker | None] = ContextVar("_run_budget", default=None)


def set_run_budget_tracker(tracker: DaemonTokenTracker | None) -> Token:
    """Install *tracker* as the active per-run budget; return reset token."""
    return _run_budget.set(tracker)


def reset_run_budget_tracker(token: Token) -> None:
    """Restore the previous tracker (paired with ``set_run_budget_tracker``)."""
    _run_budget.reset(token)


def get_run_budget_tracker() -> DaemonTokenTracker | None:
    """Return the active per-run tracker, or ``None`` if no budget is set."""
    return _run_budget.get()


def make_single_shot_tracker(
    role: RoleDefinition,
    override: int | None,
) -> DaemonTokenTracker | None:
    """Build a lifetime-only tracker if a per-run budget is configured.

    *override* (e.g. from ``--token-budget``) takes precedence over the
    role's ``guardrails.run_token_budget``. Returns ``None`` when neither
    is set, so callers can no-op cleanly.
    """
    budget = override if override is not None else role.spec.guardrails.run_token_budget
    if budget is None:
        return None

    model_name = role.spec.model.name if role.spec.model else ""
    provider = role.spec.model.provider if role.spec.model else ""
    return DaemonTokenTracker(
        lifetime_budget=budget,
        daily_budget=None,
        daily_cost_budget=None,
        weekly_cost_budget=None,
        model=model_name,
        provider=provider,
        timezone="UTC",
    )
