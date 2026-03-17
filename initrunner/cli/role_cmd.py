"""Role commands: validate, setup."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from initrunner.cli._helpers import console, resolve_skill_dirs
from initrunner.cli._options import SkillDirOption


def validate(
    role_file: Annotated[Path, typer.Argument(help="Path to role.yaml")],
    skill_dir: SkillDirOption = None,
) -> None:
    """Validate a role definition file."""
    from initrunner.cli._helpers import detect_yaml_kind

    kind = detect_yaml_kind(role_file)
    if kind == "Team":
        _validate_team(role_file)
        return

    from initrunner.agent.loader import RoleLoadError
    from initrunner.services.discovery import load_role_sync

    try:
        role = load_role_sync(role_file)
    except RoleLoadError as e:
        console.print(f"[red]Invalid:[/red] {e}")
        raise typer.Exit(1) from None

    table = Table(title=f"Role: {role.metadata.name}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("API Version", role.apiVersion.value)
    table.add_row("Kind", role.kind.value)
    table.add_row("Name", role.metadata.name)
    table.add_row("Description", role.metadata.description or "(none)")
    table.add_row("Tags", ", ".join(role.metadata.tags) if role.metadata.tags else "(none)")
    table.add_row("Model", role.spec.model.to_model_string())
    table.add_row("Temperature", str(role.spec.model.temperature))
    table.add_row("Max Tokens", str(role.spec.model.max_tokens))
    table.add_row("Timeout", f"{role.spec.guardrails.timeout_seconds}s")
    table.add_row("Max Tokens/Run", str(role.spec.guardrails.max_tokens_per_run))
    table.add_row("Max Tool Calls", str(role.spec.guardrails.max_tool_calls))
    table.add_row("Max Requests", str(role.spec.guardrails.max_request_limit))
    if role.spec.guardrails.input_tokens_limit is not None:
        table.add_row("Input Tokens Limit", str(role.spec.guardrails.input_tokens_limit))
    if role.spec.guardrails.total_tokens_limit is not None:
        table.add_row("Total Tokens Limit", str(role.spec.guardrails.total_tokens_limit))
    if role.spec.guardrails.session_token_budget is not None:
        table.add_row("Session Token Budget", f"{role.spec.guardrails.session_token_budget:,}")
    if role.spec.guardrails.daemon_token_budget is not None:
        table.add_row("Daemon Token Budget", f"{role.spec.guardrails.daemon_token_budget:,}")
    if role.spec.guardrails.daemon_daily_token_budget is not None:
        table.add_row("Daemon Daily Budget", f"{role.spec.guardrails.daemon_daily_token_budget:,}")

    if role.spec.tools:
        table.add_row("Tools", "\n".join(t.summary() for t in role.spec.tools))
    else:
        table.add_row("Tools", "0")

    if role.spec.skills:
        from initrunner.agent.skills import SkillLoadError, resolve_skills

        extra_dirs = resolve_skill_dirs(skill_dir)
        try:
            resolved = resolve_skills(role.spec.skills, role_file.parent, extra_dirs)
            lines = []
            for rs in resolved:
                unmet = [r for r in rs.requirement_statuses if not r.met]
                tool_count = len(rs.definition.frontmatter.tools)
                line = f"{rs.definition.frontmatter.name} ({rs.source_path}, {tool_count} tools)"
                if unmet:
                    warns = ", ".join(r.detail for r in unmet)
                    line += f" [yellow]unmet: {warns}[/yellow]"
                lines.append(line)
            table.add_row("Skills", "\n".join(lines))
        except SkillLoadError as e:
            table.add_row("Skills", f"[red]{e}[/red]")
    else:
        table.add_row("Skills", "(none)")

    if role.spec.triggers:
        table.add_row("Triggers", "\n".join(tr.summary() for tr in role.spec.triggers))
    else:
        table.add_row("Triggers", "0")

    if role.spec.ingest:
        table.add_row(
            "Ingest",
            f"{len(role.spec.ingest.sources)} source(s), "
            f"chunk={role.spec.ingest.chunking.strategy}/{role.spec.ingest.chunking.chunk_size}",
        )
    else:
        table.add_row("Ingest", "(none)")

    if role.spec.memory:
        table.add_row(
            "Memory",
            f"max_sessions={role.spec.memory.max_sessions}, "
            f"max_memories={role.spec.memory.semantic.max_memories}",
        )
    else:
        table.add_row("Memory", "(none)")

    if role.spec.sinks:
        table.add_row("Sinks", "\n".join(s.summary() for s in role.spec.sinks))
    else:
        table.add_row("Sinks", "(none)")

    try:
        from initrunner._compat import require_provider

        require_provider(role.spec.model.provider)
        table.add_row("Provider Status", "[green]available[/green]")
    except RuntimeError as e:
        table.add_row("Provider Status", f"[yellow]{e}[/yellow]")

    console.print(table)
    console.print("[green]Valid[/green]")


def setup(
    provider: Annotated[
        str | None, typer.Option(help="Provider (skip interactive selection)")
    ] = None,
    name: Annotated[str, typer.Option(help="Agent name")] = "my-agent",
    intent: Annotated[
        str | None,
        typer.Option(
            help="Intent: chatbot, knowledge, memory, telegram-bot, discord-bot, "
            "api-agent, daemon, from-example"
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(help="Model name (e.g. gpt-5-mini, claude-sonnet-4-5-20250929)"),
    ] = None,
    skip_test: Annotated[bool, typer.Option("--skip-test", help="Skip connectivity test")] = False,
    output: Annotated[Path, typer.Option(help="Role output path")] = Path("role.yaml"),
    accept_risks: Annotated[
        bool,
        typer.Option("--accept-risks", "-y", help="Accept security disclaimer without prompting"),
    ] = False,
    interfaces: Annotated[
        str | None,
        typer.Option(help="Install interfaces: tui, dashboard, both, skip"),
    ] = None,
    skip_chat_yaml: Annotated[
        bool,
        typer.Option("--skip-chat-yaml", help="Skip chat.yaml generation"),
    ] = False,
) -> None:
    """Guided setup wizard for first-time configuration."""
    from initrunner.cli.setup_cmd import run_setup

    run_setup(
        provider=provider,
        name=name,
        intent=intent,
        skip_test=skip_test,
        output=output,
        accept_risks=accept_risks,
        interfaces=interfaces,
        model=model,
        skip_chat_yaml=skip_chat_yaml,
    )


def _validate_team(team_file: Path) -> None:
    """Validate a team definition file and display its info."""
    from initrunner.team.loader import TeamLoadError, load_team

    try:
        team = load_team(team_file)
    except TeamLoadError as e:
        console.print(f"[red]Invalid:[/red] {e}")
        raise typer.Exit(1) from None

    table = Table(title=f"Team: {team.metadata.name}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("API Version", team.apiVersion.value)
    table.add_row("Kind", team.kind)
    table.add_row("Name", team.metadata.name)
    table.add_row("Description", team.metadata.description or "(none)")
    table.add_row("Tags", ", ".join(team.metadata.tags) if team.metadata.tags else "(none)")
    table.add_row("Model", team.spec.model.to_model_string())
    table.add_row("Personas", str(len(team.spec.personas)))
    table.add_row("Persona Names", ", ".join(team.spec.personas.keys()))

    if team.spec.tools:
        table.add_row("Tools", "\n".join(t.summary() for t in team.spec.tools))
    else:
        table.add_row("Tools", "0")

    table.add_row("Timeout/persona", f"{team.spec.guardrails.timeout_seconds}s")
    table.add_row("Max Tokens/persona", str(team.spec.guardrails.max_tokens_per_run))
    table.add_row("Max Tool Calls/persona", str(team.spec.guardrails.max_tool_calls))
    if team.spec.guardrails.team_token_budget is not None:
        table.add_row("Team Token Budget", f"{team.spec.guardrails.team_token_budget:,}")
    if team.spec.guardrails.team_timeout_seconds is not None:
        table.add_row("Team Timeout", f"{team.spec.guardrails.team_timeout_seconds}s")
    table.add_row("Handoff Max Chars", str(team.spec.handoff_max_chars))

    try:
        from initrunner._compat import require_provider

        require_provider(team.spec.model.provider)
        table.add_row("Provider Status", "[green]available[/green]")
    except RuntimeError as e:
        table.add_row("Provider Status", f"[yellow]{e}[/yellow]")

    console.print(table)
    console.print("[green]Valid[/green]")
