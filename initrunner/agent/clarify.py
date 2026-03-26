"""Agent-initiated clarification: ContextVar callback for mid-run user input."""

from __future__ import annotations

import contextvars
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

__all__ = [
    "ClarifyCallback",
    "ClarifyState",
    "get_clarify_callback",
    "make_cli_clarify_callback",
    "reset_clarify_callback",
    "set_clarify_callback",
]

ClarifyCallback = Callable[[str], str]
"""Signature: ``(question) -> answer``.  Blocks until the user responds."""

# ---------------------------------------------------------------------------
# ContextVar plumbing
# ---------------------------------------------------------------------------

_clarify_callback: contextvars.ContextVar[ClarifyCallback | None] = contextvars.ContextVar(
    "_clarify_callback", default=None
)


def set_clarify_callback(
    cb: ClarifyCallback | None,
) -> contextvars.Token[ClarifyCallback | None]:
    """Set the clarify callback for the current context."""
    return _clarify_callback.set(cb)


def reset_clarify_callback(
    token: contextvars.Token[ClarifyCallback | None],
) -> None:
    """Reset the clarify callback to its previous value."""
    _clarify_callback.reset(token)


def get_clarify_callback() -> ClarifyCallback | None:
    """Read the current clarify callback."""
    return _clarify_callback.get()


# ---------------------------------------------------------------------------
# Per-run state
# ---------------------------------------------------------------------------


@dataclass
class ClarifyState:
    """Tracks clarification usage within a single run."""

    max_clarifications: int = 3
    count: int = 0
    history: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CLI callback factory
# ---------------------------------------------------------------------------


def make_cli_clarify_callback(timeout: float = 300) -> ClarifyCallback:
    """Build a :data:`ClarifyCallback` that prompts via the Rich console.

    Input is read on a daemon thread so that *timeout* (seconds) is honoured.
    Raises :class:`TimeoutError` when the user does not respond in time.
    """
    from rich.panel import Panel

    from initrunner.runner.display import console

    def _cli_clarify(question: str) -> str:
        console.print(Panel(question, title="Agent needs clarification", border_style="yellow"))
        result_queue: queue.Queue[str | None] = queue.Queue()

        def _read_input() -> None:
            try:
                answer = console.input("[bold yellow]> [/bold yellow]").strip()
                result_queue.put(answer)
            except (EOFError, KeyboardInterrupt):
                result_queue.put(None)

        t = threading.Thread(target=_read_input, daemon=True)
        t.start()
        try:
            answer = result_queue.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"No response within {int(timeout)}s") from None
        if answer is None:
            raise TimeoutError("Input cancelled")
        return answer

    return _cli_clarify
