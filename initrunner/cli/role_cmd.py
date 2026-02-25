"""Role commands: validate, init, setup."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from initrunner.cli._helpers import check_ollama_running, console, resolve_skill_dirs


def validate(
    role_file: Annotated[Path, typer.Argument(help="Path to role.yaml")],
    skill_dir: Annotated[
        Path | None, typer.Option("--skill-dir", help="Extra skill search directory")
    ] = None,
) -> None:
    """Validate a role definition file."""
    from initrunner.cli._helpers import detect_yaml_kind

    kind = detect_yaml_kind(role_file)
    if kind == "Team":
        _validate_team(role_file)
        return

    from initrunner.agent.loader import RoleLoadError, load_role

    try:
        role = load_role(role_file)
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
            f"max_memories={role.spec.memory.max_memories}",
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


def init(
    name: Annotated[str, typer.Option(help="Agent name")] = "my-agent",
    output: Annotated[Path, typer.Option(help="Output file path")] = Path("role.yaml"),
    template: Annotated[
        str, typer.Option(help="Template: basic, rag, daemon, memory, ollama, tool, api, skill")
    ] = "basic",
    provider: Annotated[str, typer.Option(help="Model provider")] = "openai",
    model: Annotated[
        str | None,
        typer.Option(help="Model name (e.g. gpt-5-mini, claude-sonnet-4-5-20250929)"),
    ] = None,
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Launch interactive wizard")
    ] = False,
) -> None:
    """Scaffold a template role.yaml, tool module, or skill.

    When called with --interactive (or -i), launches a guided wizard.
    """
    if interactive:
        from initrunner.cli.wizard import run_wizard

        run_wizard()
        return

    from initrunner.templates import TEMPLATES

    builder = TEMPLATES.get(template)
    if builder is None:
        available = ", ".join(sorted(TEMPLATES.keys()))
        console.print(f"[red]Error:[/red] Unknown template '{template}'. Use: {available}")
        raise typer.Exit(1)

    # Tool template writes a .py file
    if template == "tool":
        py_name = name.replace("-", "_")
        out_path = Path(f"{py_name}.py")
        if out_path.exists():
            console.print(f"[red]Error:[/red] {out_path} already exists. Refusing to overwrite.")
            raise typer.Exit(1)
        content = builder(py_name, provider)
        out_path.write_text(content)
        console.print(f"[green]Created[/green] {out_path} (template=tool)")
        console.print("\n[dim]Next steps:[/dim]")
        console.print(f"  1. Edit {out_path} to add your tool functions")
        console.print("  2. Reference in role.yaml:")
        console.print("     tools:")
        console.print("       - type: custom")
        console.print(f"         module: {py_name}")
        return

    # Skill template writes a directory with SKILL.md
    if template == "skill":
        skill_dir_path = Path(name)
        skill_file = skill_dir_path / "SKILL.md"
        if skill_dir_path.exists():
            console.print(
                f"[red]Error:[/red] {skill_dir_path} already exists. Refusing to overwrite."
            )
            raise typer.Exit(1)
        skill_dir_path.mkdir(parents=True)
        content = builder(name, provider)
        skill_file.write_text(content)
        console.print(f"[green]Created[/green] {skill_file} (template=skill)")
        console.print("\n[dim]Next steps:[/dim]")
        console.print(f"  1. Edit {skill_file} to configure tools and prompt")
        console.print("  2. Reference in role.yaml:")
        console.print("     skills:")
        console.print(f"       - {name}")
        return

    if output.exists():
        console.print(
            f"[red]Error:[/red] {output} already exists. Refusing to overwrite.",
            soft_wrap=True,
        )
        raise typer.Exit(1)

    if template in ("tool", "skill"):
        content = builder(name, provider)
    else:
        content = builder(name, provider, model)
    output.write_text(content)
    console.print(f"[green]Created[/green] {output} (template={template})")

    if provider not in ("openai", "ollama"):
        console.print(f"[dim]Hint: install provider with: pip install initrunner[{provider}][/dim]")

    if template == "ollama" or provider == "ollama":
        check_ollama_running()


def create(
    description: Annotated[str, typer.Argument(help="Natural language description of the agent")],
    provider: Annotated[str | None, typer.Option(help="Model provider for generation")] = None,
    output: Annotated[Path, typer.Option(help="Output file path")] = Path("role.yaml"),
    name: Annotated[str | None, typer.Option(help="Agent name (auto-derived if omitted)")] = None,
    model: Annotated[
        str | None,
        typer.Option(help="Model name (e.g. gpt-5-mini, claude-sonnet-4-5-20250929)"),
    ] = None,
    no_confirm: Annotated[bool, typer.Option("--no-confirm", help="Skip preview")] = False,
) -> None:
    """Generate a role.yaml from a natural language description using AI."""
    from initrunner.services.roles import generate_role_sync

    model_label = provider or "auto-detected"
    console.print(f"[dim]Generating role.yaml using {model_label} provider...[/dim]")

    try:
        with console.status("Generating..."):
            yaml_text = generate_role_sync(
                description,
                provider=provider,
                model_name=model,
                name_hint=name,
            )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    # Preview
    if not no_confirm:
        console.print()
        console.print("[bold]--- Generated role.yaml ---[/bold]")
        console.print(yaml_text)
        console.print("[bold]--- End ---[/bold]")
        console.print()

    if output.exists() and not no_confirm:
        if not typer.confirm(f"{output} already exists. Overwrite?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit()

    # Validate before writing
    from initrunner.services.roles import save_role_yaml_sync

    try:
        save_role_yaml_sync(output, yaml_text)
        console.print(f"[green]Created[/green] {output}")
    except (ValueError, Exception) as e:
        # Write anyway but warn
        output.write_text(yaml_text)
        console.print(f"[yellow]Warning:[/yellow] Validation issue: {e}")
        console.print(f"[green]Created[/green] {output} (may need manual fixes)")

    console.print(f"[dim]Run: initrunner validate {output}[/dim]")


def setup(
    provider: Annotated[
        str | None, typer.Option(help="Provider (skip interactive selection)")
    ] = None,
    name: Annotated[str, typer.Option(help="Agent name")] = "my-agent",
    template: Annotated[
        str | None, typer.Option(help="Template: chatbot, rag, memory, daemon")
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
) -> None:
    """Guided setup wizard for first-time configuration."""
    from initrunner.cli.setup_cmd import run_setup

    run_setup(
        provider=provider,
        name=name,
        template=template,
        skip_test=skip_test,
        output=output,
        accept_risks=accept_risks,
        interfaces=interfaces,
        model=model,
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
