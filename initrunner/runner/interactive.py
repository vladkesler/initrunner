"""Interactive REPL runner with multi-turn conversation history."""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models import Model

from initrunner.agent.executor import check_token_budget
from initrunner.agent.memory_ops import finalize_turn, load_session
from initrunner.agent.schema import RoleDefinition
from initrunner.audit.logger import AuditLogger
from initrunner.runner.display import _display_budget_warning, _display_save_warning, console
from initrunner.runner.single import run_single
from initrunner.sinks.dispatcher import SinkDispatcher
from initrunner.stores.base import MemoryStoreBase


def run_interactive(
    agent: Agent,
    role: RoleDefinition,
    *,
    audit_logger: AuditLogger | None = None,
    message_history: list | None = None,
    memory_store: MemoryStoreBase | None = None,
    resume: bool = False,
    sink_dispatcher: SinkDispatcher | None = None,
    model_override: Model | str | None = None,
) -> None:
    """Run an interactive REPL with multi-turn conversation history."""
    agent_name = role.metadata.name

    # Resume previous session if requested
    if resume:
        loaded = load_session(role)
        if loaded:
            message_history = loaded
            console.print(f"[dim]Resumed session with {len(loaded)} messages.[/dim]")
        else:
            console.print("[dim]No previous session found.[/dim]")

    from initrunner._ids import generate_id

    session_id = generate_id()

    session_budget = role.spec.guardrails.session_token_budget
    cumulative_tokens = 0

    console.print(f"[bold]Interactive mode[/bold] — agent: [cyan]{agent_name}[/cyan]")
    if session_budget is not None:
        console.print(f"  Session token budget: [cyan]{session_budget:,}[/cyan]")
    console.print("Type [bold]exit[/bold] or [bold]quit[/bold] to leave.\n")

    while True:
        # Check session budget before accepting input
        budget_status = check_token_budget(cumulative_tokens, session_budget)
        if budget_status.exceeded:
            console.print(
                "[yellow]Session token budget exhausted. Stopping further execution.[/yellow]"
            )
            break
        if budget_status.warning:
            assert session_budget is not None
            pct = int(cumulative_tokens / session_budget * 100)
            console.print(
                f"[yellow]Warning: {pct}% of session token budget consumed "
                f"({cumulative_tokens:,}/{session_budget:,})[/yellow]"
            )

        try:
            prompt = console.input("[bold]> [/bold]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nGoodbye!")
            break

        if not prompt:
            continue
        if prompt.lower() in ("exit", "quit"):
            console.print("Goodbye!")
            break

        result, message_history = run_single(
            agent,
            role,
            prompt,
            audit_logger=audit_logger,
            message_history=message_history,
            sink_dispatcher=sink_dispatcher,
            model_override=model_override,
        )

        cumulative_tokens += result.total_tokens
        budget_status = check_token_budget(cumulative_tokens, session_budget)
        _display_budget_warning(budget_status, cumulative_tokens, session_budget)

        if message_history:
            turn_result = finalize_turn(role, session_id, message_history, memory_store)
            message_history = turn_result.messages
            if not turn_result.save_ok:
                _display_save_warning()

    # Prune old sessions on exit
    from initrunner.runner import maybe_prune_sessions

    maybe_prune_sessions(role, memory_store)
