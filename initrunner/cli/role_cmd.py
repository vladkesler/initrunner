"""Role commands: validate, setup, configure."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from initrunner.cli._helpers import console, resolve_skill_dirs
from initrunner.cli._options import SkillDirOption


def validate(
    role_file: Annotated[
        Path, typer.Argument(help="Agent directory, role YAML, or installed role name")
    ],
    skill_dir: SkillDirOption = None,
) -> None:
    """Validate a role definition file."""
    from initrunner.cli._helpers import detect_yaml_kind, resolve_role_path

    role_file = resolve_role_path(role_file)
    kind = detect_yaml_kind(role_file)
    if kind == "Pipeline":
        console.print(
            "[red]Error:[/red] kind: Pipeline has been removed.\n"
            "Use Team for one-shot multi-agent workflows, or Compose for long-running services."
        )
        raise typer.Exit(1)
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
    skip_run_yaml: Annotated[
        bool,
        typer.Option("--skip-run-yaml", help="Skip run.yaml generation"),
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
        model=model,
        skip_run_yaml=skip_run_yaml,
    )


def configure(
    role: Annotated[
        Path,
        typer.Argument(help="Role YAML file, directory, or installed role name"),
    ],
    provider: Annotated[
        str | None,
        typer.Option(help="Target provider (e.g. openai, anthropic, groq, ollama)"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(help="Target model name"),
    ] = None,
    reset: Annotated[
        bool,
        typer.Option("--reset", help="Remove provider override, revert to original"),
    ] = False,
) -> None:
    """Switch the LLM provider/model for a role."""
    from rich.panel import Panel
    from rich.prompt import Prompt

    from initrunner.agent.loader import RoleLoadError, load_role
    from initrunner.cli._helpers import prompt_model_selection, resolve_role_path
    from initrunner.registry import (
        clear_role_overrides,
        get_overrides_for_path,
        resolve_installed_path,
        set_role_overrides,
    )
    from initrunner.services.providers import list_available_providers

    # Resolve the path
    role_path = resolve_role_path(role)

    try:
        role_def = load_role(role_path)
    except RoleLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    # Determine if this is an installed role (registry-backed) or local file
    installed_path = None
    try:
        installed_path = resolve_installed_path(str(role))
    except Exception:
        pass
    is_installed = installed_path is not None

    current_overrides = get_overrides_for_path(role_path) if is_installed else {}
    effective_provider = current_overrides.get("provider", role_def.spec.model.provider)
    effective_model = current_overrides.get("model", role_def.spec.model.name)
    original_provider = role_def.spec.model.provider
    original_model = role_def.spec.model.name

    # Handle --reset
    if reset:
        if not is_installed:
            console.print("[yellow]Warning:[/yellow] --reset only applies to installed roles.")
            raise typer.Exit(1)
        clear_role_overrides(str(role))
        console.print(
            f"Removed provider override. Using original: "
            f"[cyan]{original_provider} / {original_model}[/cyan]"
        )
        return

    # Show current config
    features = []
    if role_def.spec.tools:
        features.append("tools")
    if role_def.spec.ingest:
        features.append("ingest (RAG)")
    if role_def.spec.memory:
        features.append("memory")
    if role_def.spec.triggers:
        features.append("triggers")

    lines = [
        f"  Name:      [bold]{role_def.metadata.name}[/bold]",
        f"  Provider:  [cyan]{effective_provider}[/cyan]"
        + ("  (override)" if current_overrides else ""),
        f"  Model:     {effective_model}",
    ]
    if current_overrides:
        lines.append(f"  Original:  {original_provider} / {original_model}")
    if features:
        lines.append(f"  Features:  {', '.join(features)}")

    console.print(Panel("\n".join(lines), title="Current Configuration", border_style="cyan"))

    # Non-interactive mode
    if provider is not None:
        if model is None:
            from initrunner.templates import _default_model_name

            model = _default_model_name(provider)

        if is_installed:
            set_role_overrides(str(role), {"provider": provider, "model": model})
        else:
            _update_role_yaml(role_path, provider, model)

        console.print(f"Updated {role_def.metadata.name}: [cyan]{provider} / {model}[/cyan]")
        return

    # Interactive mode -- show available providers
    available = list_available_providers()
    if not available:
        console.print(
            "[yellow]No providers configured.[/yellow] Run [bold]initrunner setup[/bold] first."
        )
        raise typer.Exit(1)

    console.print("\nAvailable providers:")
    for i, dp in enumerate(available, 1):
        current_tag = "    (current)" if dp.provider == effective_provider else ""
        console.print(f"  {i}. {dp.provider:10s} [{dp.model}]{current_tag}")

    raw = Prompt.ask(
        f"\nSwitch provider [1-{len(available)}, Enter to keep]",
        default="",
    )

    if not raw.strip():
        console.print("  No change.")
        return

    idx = int(raw) - 1 if raw.strip().isdigit() else -1
    if not (0 <= idx < len(available)):
        console.print(f"[red]Invalid choice:[/red] '{raw}'")
        raise typer.Exit(1)

    chosen_provider = available[idx].provider
    chosen_model = prompt_model_selection(chosen_provider)

    if is_installed:
        set_role_overrides(str(role), {"provider": chosen_provider, "model": chosen_model})
    else:
        _update_role_yaml(role_path, chosen_provider, chosen_model)

    console.print(
        f"Updated {role_def.metadata.name}: [cyan]{chosen_provider} / {chosen_model}[/cyan]"
    )


def _update_role_yaml(role_path: Path, provider: str, model: str) -> None:
    """Rewrite the model block in a local role YAML file."""
    import yaml

    data = yaml.safe_load(role_path.read_text())
    if "spec" in data and "model" in data["spec"]:
        old_provider = data["spec"]["model"].get("provider", "")
        data["spec"]["model"]["provider"] = provider
        data["spec"]["model"]["name"] = model
        # Only clear provider-specific fields when the provider actually changes
        if provider != old_provider:
            data["spec"]["model"].pop("base_url", None)
            data["spec"]["model"].pop("api_key_env", None)
    role_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


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
    # Build persona display with inline overrides
    persona_parts = []
    for pname, pcfg in team.spec.personas.items():
        extras = []
        if pcfg.model:
            extras.append(f"model={pcfg.model.to_model_string()}")
        if pcfg.tools:
            extras.append(f"{len(pcfg.tools)} tools ({pcfg.tools_mode})")
        if pcfg.environment:
            extras.append(f"{len(pcfg.environment)} env vars")
        if extras:
            persona_parts.append(f"{pname} [{', '.join(extras)}]")
        else:
            persona_parts.append(pname)
    table.add_row("Persona Names", ", ".join(persona_parts))
    table.add_row("Strategy", team.spec.strategy)

    if team.spec.tools:
        table.add_row("Tools", "\n".join(t.summary() for t in team.spec.tools))
    else:
        table.add_row("Tools", "0")

    # Shared memory / documents
    if team.spec.shared_memory.enabled:
        max_mem = team.spec.shared_memory.max_memories
        table.add_row("Shared Memory", f"enabled (max={max_mem})")
    else:
        table.add_row("Shared Memory", "(disabled)")

    if team.spec.shared_documents.enabled:
        n_src = len(team.spec.shared_documents.sources)
        table.add_row("Shared Documents", f"enabled ({n_src} sources)")
    else:
        table.add_row("Shared Documents", "(disabled)")

    # Observability
    if team.spec.observability:
        table.add_row("Observability", team.spec.observability.backend)
    else:
        table.add_row("Observability", "(none)")

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
