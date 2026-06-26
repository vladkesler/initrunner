"""Interactive REPL runner with multi-turn conversation history."""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import Model

from initrunner.agent.executor import check_token_budget
from initrunner.agent.memory_ops import finalize_turn, load_session
from initrunner.agent.prompt import UserPrompt, build_multimodal_prompt
from initrunner.agent.schema.role import RoleDefinition
from initrunner.audit.logger import AuditLogger
from initrunner.runner.display import _display_budget_warning, _display_save_warning, console
from initrunner.runner.reload import AgentHandle
from initrunner.runner.single import run_single, run_single_stream
from initrunner.sinks.dispatcher import SinkDispatcher
from initrunner.stores.base import MemoryStoreBase


def _prompt_and_resume(
    agent: Agent,
    role: RoleDefinition,
    result,
    message_history: list,
    *,
    audit_logger: AuditLogger | None,
    model_override: Model | str | None,
) -> tuple:
    """Inline y/N prompt for every pending approval, then resume.

    Unlike the daemon/API path this never persists: the REPL holds the
    message history in memory across the pause and resume, so we don't
    need to round-trip through the audit DB.
    """
    from rich.prompt import Confirm

    from initrunner.agent.executor import execute_run_resume

    console.print(
        f"\n[yellow]Run {result.run_id} paused — "
        f"{len(result.pending_approvals)} tool call(s) need approval.[/yellow]"
    )
    approvals: dict[str, bool] = {}
    for p in result.pending_approvals:
        console.print(
            f"\n  [bold]{p.tool_name}[/bold]  [magenta]{p.tool_call_id}[/magenta]\n  {p.arguments}"
        )
        approvals[p.tool_call_id] = Confirm.ask("  Approve?", default=False)

    return execute_run_resume(
        agent,
        role,
        run_id=result.run_id,
        message_history=message_history,
        approvals=approvals,
        audit_logger=audit_logger,
        model_override=model_override,
    )


def _attach_tool(handle: AgentHandle, module: str):
    """Append a ``type: custom`` config for *module* and rebuild via the handle.

    Reloads an already-imported module so edits are picked up, replaces any
    existing custom config for the same module (rather than duplicating), and
    rebuilds through the standard agent build path so the new tool is re-wrapped
    in the policy/permission/approval/sandbox layers.
    """
    import importlib
    import sys

    from initrunner.agent.schema.tools import CustomToolConfig

    _agent, role = handle.current()
    if module in sys.modules:
        try:
            importlib.reload(sys.modules[module])
        except Exception:
            pass  # A fresh import happens in build_custom_toolset regardless.

    cfg = CustomToolConfig(type="custom", module=module)
    kept = [
        t
        for t in role.spec.tools
        if not (getattr(t, "type", None) == "custom" and getattr(t, "module", None) == module)
    ]
    new_spec = role.spec.model_copy(update={"tools": [*kept, cfg]})
    new_role = role.model_copy(update={"spec": new_spec})
    return handle.rebuild_from_role(new_role)


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
    stream: bool = False,
    reload_handle: AgentHandle | None = None,
    role_path: Path | None = None,
    extra_skill_dirs: list[Path] | None = None,
    load_model_override: str | None = None,
    tool_dev: bool = False,
) -> None:
    """Run an interactive REPL with multi-turn conversation history."""
    agent_name = role.metadata.name

    # Resume previous session if requested
    if resume:
        loaded = load_session(role)
        if loaded:
            message_history = loaded
            console.print(f"[dim]Resumed session with {len(loaded)} messages.[/dim]")

            if memory_store is not None:
                from initrunner.agent.memory_ops import auto_recall_for_resume

                context = auto_recall_for_resume(role, loaded, store=memory_store)
                if context:
                    agent._resume_context = context  # type: ignore[attr-defined]
                    console.print("[dim]Loaded relevant memories from previous sessions.[/dim]")
        else:
            console.print("[dim]No previous session found.[/dim]")

    from initrunner._ids import generate_id

    session_id = generate_id()

    # A single handle owns the live (agent, role) pair so /reload (and the A2
    # /tool hot-attach) can rebuild and swap them between turns while the loop
    # keeps message_history intact. Reuse the resume-populated agent above.
    handle = reload_handle or AgentHandle(
        agent,
        role,
        role_dir=(role_path.parent if role_path is not None else None),
        role_path=role_path,
        extra_skill_dirs=extra_skill_dirs,
        load_model_override=load_model_override,
    )

    session_budget = role.spec.guardrails.session_token_budget
    cumulative_tokens = 0
    pending_attachments: list[str] = []

    console.print(f"[bold]Interactive mode[/bold] — agent: [cyan]{agent_name}[/cyan]")
    if session_budget is not None:
        console.print(f"  Session token budget: [cyan]{session_budget:,}[/cyan]")
    console.print("Type [bold]exit[/bold] or [bold]quit[/bold] to leave.")
    console.print(
        "Commands: [bold]/attach <path_or_url>[/bold], "
        "[bold]/attachments[/bold], [bold]/clear-attachments[/bold], "
        "[bold]/tool add <module>[/bold], [bold]/reload[/bold]\n"
    )

    while True:
        # Refresh from the handle so a /reload (or /tool attach) applied between
        # turns takes effect, including an edited session token budget.
        agent, role = handle.current()
        session_budget = role.spec.guardrails.session_token_budget

        # Check session budget before accepting input
        budget_status = check_token_budget(cumulative_tokens, session_budget)
        if budget_status.exceeded:
            console.print(
                "[yellow]Session token budget exhausted. Stopping further execution.[/yellow]"
            )
            console.print(
                "[dim]Hint:[/dim] Increase [bold]guardrails.session_token_budget[/bold]"
                " in your role YAML, or start a new session."
            )
            break
        if budget_status.warning and session_budget is not None:
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
        if raw_input == "/reload":
            result = handle.reload_from_disk()
            agent, role = handle.current()
            console.print(f"[{'green' if result.ok else 'yellow'}]{result.summary}[/]")
            if result.error:
                console.print(f"[dim]{result.error}[/dim]")
            continue
        if raw_input.startswith("/tool add"):
            module = raw_input[len("/tool add") :].strip()
            if not module:
                console.print("[yellow]Usage: /tool add <module>[/yellow]")
                continue
            result = _attach_tool(handle, module)
            agent, role = handle.current()
            console.print(f"[{'green' if result.ok else 'yellow'}]{result.summary}[/]")
            if result.ok:
                console.print(f"[dim]Attached custom tool module '{module}'.[/dim]")
            if result.error:
                console.print(f"[dim]{result.error}[/dim]")
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

        _run_fn = run_single_stream if stream else run_single
        result, message_history = _run_fn(
            agent,
            role,
            user_prompt,
            audit_logger=audit_logger,
            message_history=message_history,
            sink_dispatcher=sink_dispatcher,
            model_override=model_override,
            show_thinking=not tool_dev,
        )

        while result.status == "paused":
            result, message_history = _prompt_and_resume(
                agent,
                role,
                result,
                message_history,
                audit_logger=audit_logger,
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
