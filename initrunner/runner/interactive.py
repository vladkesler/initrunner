"""Interactive REPL runner with multi-turn conversation history."""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models import Model

from initrunner.agent.executor import check_token_budget
from initrunner.agent.memory_ops import finalize_turn, load_session
from initrunner.agent.prompt import UserPrompt, build_multimodal_prompt
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
    pending_attachments: list[str] = []

    console.print(f"[bold]Interactive mode[/bold] — agent: [cyan]{agent_name}[/cyan]")
    if session_budget is not None:
        console.print(f"  Session token budget: [cyan]{session_budget:,}[/cyan]")
    console.print("Type [bold]exit[/bold] or [bold]quit[/bold] to leave.")
    console.print(
        "Commands: [bold]/attach <path_or_url>[/bold], "
        "[bold]/attachments[/bold], [bold]/clear-attachments[/bold]\n"
    )

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
            if pending_attachments:
                prompt_prefix = f"[dim]\\[{len(pending_attachments)} file(s)] [/dim][bold]> [/bold]"
            else:
                prompt_prefix = "[bold]> [/bold]"
            raw_input = console.input(prompt_prefix).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nGoodbye!")
            break

        if not raw_input:
            continue
        if raw_input.lower() in ("exit", "quit"):
            console.print("Goodbye!")
            break

        # Handle REPL commands
        if raw_input.startswith("/attach "):
            attachment = raw_input[len("/attach ") :].strip()
            if attachment:
                pending_attachments.append(attachment)
                console.print(f"[dim]Queued attachment: {attachment}[/dim]")
            else:
                console.print("[yellow]Usage: /attach <path_or_url>[/yellow]")
            continue
        if raw_input == "/attachments":
            if pending_attachments:
                for i, a in enumerate(pending_attachments, 1):
                    console.print(f"  {i}. {a}")
            else:
                console.print("[dim]No attachments queued.[/dim]")
            continue
        if raw_input == "/clear-attachments":
            pending_attachments.clear()
            console.print("[dim]Attachments cleared.[/dim]")
            continue

        # Build prompt (multimodal if attachments are queued)
        user_prompt: UserPrompt
        if pending_attachments:
            try:
                user_prompt = build_multimodal_prompt(raw_input, pending_attachments)
            except (FileNotFoundError, ValueError) as e:
                console.print(f"[red]Attachment error:[/red] {e}")
                continue
            pending_attachments.clear()
        else:
            user_prompt = raw_input

        result, message_history = run_single(
            agent,
            role,
            user_prompt,
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

    # Consolidation at session exit
    if memory_store is not None and role.spec.memory is not None:
        if role.spec.memory.consolidation.interval == "after_session":
            from initrunner.agent.memory_consolidation import maybe_consolidate

            maybe_consolidate(memory_store, role)
