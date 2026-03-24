"""Doctor command: provider configuration check and quickstart smoke test."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from initrunner.cli._helpers import console


def doctor(
    quickstart: Annotated[
        bool, typer.Option("--quickstart", help="Run a smoke prompt to verify end-to-end")
    ] = False,
    role_file: Annotated[
        Path | None, typer.Option("--role", help="Agent directory or role YAML file to test")
    ] = None,
) -> None:
    """Check provider configuration, API keys, and connectivity."""
    import os

    from initrunner._compat import require_provider
    from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS, _load_dotenv

    if role_file is not None:
        from initrunner.cli._helpers import resolve_role_path

        role_file = resolve_role_path(role_file)

    # Load .env so that .env-only setups are detected
    if role_file is not None:
        _load_dotenv(role_file.parent)
    else:
        _load_dotenv(Path.cwd())

    # ----- Step 1: Config scan (always) -----
    table = Table(title="Provider Status")
    table.add_column("Provider", style="cyan")
    table.add_column("API Key")
    table.add_column("SDK")
    table.add_column("Status")

    for provider, env_var in _PROVIDER_API_KEY_ENVS.items():
        key_set = bool(os.environ.get(env_var))
        key_status = "[green]Set[/green]" if key_set else "[dim]Missing[/dim]"

        sdk_status = "[dim]—[/dim]"
        if key_set:
            try:
                require_provider(provider)
                sdk_status = "[green]OK[/green]"
            except RuntimeError:
                sdk_status = "[yellow]Missing[/yellow]"

        if key_set:
            status = "[green]Ready[/green]"
        else:
            status = "[dim]Not configured[/dim]"

        table.add_row(provider, key_status, sdk_status, status)

    # Ollama row
    from initrunner.services.providers import is_ollama_running

    ollama_ready = "[green]Ready[/green]" if is_ollama_running() else "[dim]Not running[/dim]"

    table.add_row("ollama", "[dim]—[/dim]", "[dim]—[/dim]", ollama_ready)

    # Docker row
    try:
        from initrunner.agent.docker_sandbox import check_docker_available

        docker_status = (
            "[green]Ready[/green]" if check_docker_available() else "[dim]Not available[/dim]"
        )
    except Exception:
        docker_status = "[dim]Not available[/dim]"
    table.add_row("docker", "[dim]—[/dim]", "[dim]—[/dim]", docker_status)

    console.print(table)

    # ----- Embedding Providers -----
    from initrunner.ingestion.embeddings import _PROVIDER_EMBEDDING_KEY_DEFAULTS

    embed_table = Table(title="Embedding Providers")
    embed_table.add_column("Provider", style="cyan")
    embed_table.add_column("Embedding Key Env")
    embed_table.add_column("Status")

    for emb_provider, emb_env in _PROVIDER_EMBEDDING_KEY_DEFAULTS.items():
        emb_key_set = bool(os.environ.get(emb_env))
        emb_status = "[green]Set[/green]" if emb_key_set else "[dim]Missing[/dim]"
        embed_table.add_row(emb_provider, emb_env, emb_status)

    embed_table.add_row("ollama", "[dim]—[/dim]", "[dim]No key needed[/dim]")

    console.print()
    console.print(embed_table)
    console.print(
        "[dim]Note: Anthropic uses OpenAI embeddings (OPENAI_API_KEY) for RAG/memory.[/dim]"
    )

    # ----- Role Validation (when --role provided) -----
    has_role_errors = False
    if role_file is not None:
        has_role_errors = _check_role_health(role_file)

    if not quickstart or has_role_errors:
        if has_role_errors:
            raise typer.Exit(1)
        return

    # ----- Step 2: Smoke test (--quickstart) -----
    console.print()
    console.print("[bold]Running quickstart smoke test...[/bold]")

    try:
        if role_file is not None:
            from initrunner.agent.loader import load_and_build

            role, agent = load_and_build(role_file)
        else:
            from initrunner.agent.loader import build_agent
            from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
            from initrunner.agent.schema.guardrails import Guardrails
            from initrunner.agent.schema.role import AgentSpec, RoleDefinition
            from initrunner.services.roles import _detect_provider
            from initrunner.templates import _default_model_name

            detected_provider = _detect_provider()
            model_name = _default_model_name(detected_provider)
            role = RoleDefinition(
                apiVersion=ApiVersion.V1,
                kind=Kind.AGENT,
                metadata=RoleMetadata(name="doctor-quickstart", spec_version=2),
                spec=AgentSpec(
                    role="You are a helpful assistant.",
                    model=ModelConfig(provider=detected_provider, name=model_name),
                    guardrails=Guardrails(timeout_seconds=60),
                ),
            )
            agent = build_agent(role, role_dir=None)

        from initrunner.services.execution import execute_run_sync

        with console.status("Running smoke prompt...", spinner="dots"):
            result, _ = execute_run_sync(agent, role, "Say hello in one sentence.")

        if result.success:
            preview = result.output[:200]
            console.print(
                Panel(
                    f"[green]Smoke test passed![/green]\n\n"
                    f"[bold]Response:[/bold] {preview}\n"
                    f"[bold]Tokens:[/bold] {result.total_tokens} | "
                    f"[bold]Duration:[/bold] {result.duration_ms}ms",
                    title="Quickstart Result",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel(
                    f"[red]Smoke test failed:[/red] {result.error}",
                    title="Quickstart Result",
                    border_style="red",
                )
            )
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as exc:
        console.print(
            Panel(
                f"[red]Smoke test error:[/red] {exc}",
                title="Quickstart Result",
                border_style="red",
            )
        )
        raise typer.Exit(1) from None


def _check_role_health(path: Path) -> bool:
    """Validate a role file and display results. Returns True if errors found."""
    from initrunner._yaml import load_raw_yaml
    from initrunner.deprecations import CURRENT_ROLE_SPEC_VERSION, inspect_role_data

    console.print()

    # Stage 1: parse YAML
    try:
        raw = load_raw_yaml(path, ValueError)
    except Exception as exc:
        console.print(
            Panel(
                f"[red]Cannot read role file:[/red] {exc}",
                title="Role Validation",
                border_style="red",
            )
        )
        return True

    # Stage 2: inspect (non-raising except future version)
    try:
        inspection = inspect_role_data(raw)
    except ValueError as exc:
        console.print(
            Panel(
                f"[red]{exc}[/red]",
                title="Role Validation",
                border_style="red",
            )
        )
        return True

    role_name = raw.get("metadata", {}).get("name", path.stem)
    has_errors = False

    # Display deprecation hits
    if inspection.hits:
        hit_table = Table(
            title=f"Role Validation: {role_name} "
            f"(spec_version: {inspection.spec_version}, "
            f"current: {CURRENT_ROLE_SPEC_VERSION})"
        )
        hit_table.add_column("ID", style="cyan")
        hit_table.add_column("Severity")
        hit_table.add_column("Issue")
        hit_table.add_column("Status")

        for hit in inspection.hits:
            severity_style = "red" if hit.severity == "error" else "yellow"
            hit_table.add_row(
                hit.id,
                f"[{severity_style}]{hit.severity}[/{severity_style}]",
                hit.message,
                "[green]auto-fixed[/green]" if hit.auto_fixed else "[red]manual fix[/red]",
            )
            if hit.severity == "error":
                has_errors = True

        console.print(hit_table)

    # Display schema errors
    if inspection.schema_error:
        has_errors = True
        console.print(
            Panel(
                f"[red]{inspection.schema_error}[/red]",
                title="Schema Error",
                border_style="red",
            )
        )

    # Summary
    if not has_errors:
        if inspection.spec_version < CURRENT_ROLE_SPEC_VERSION:
            console.print("[green]Role is valid.[/green]")
            console.print(
                f"[dim]spec_version {inspection.spec_version} is behind "
                f"current {CURRENT_ROLE_SPEC_VERSION}.[/dim]"
            )
        else:
            console.print("[green]Role is valid and up to date.[/green]")

    return has_errors
