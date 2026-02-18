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
    role_file: Annotated[Path | None, typer.Option("--role", help="Role file to test")] = None,
) -> None:
    """Check provider configuration, API keys, and connectivity."""
    import os

    from initrunner._compat import require_provider
    from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS, _load_dotenv

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
    try:
        import urllib.request

        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        ollama_ready = "[green]Ready[/green]"
    except Exception:
        ollama_ready = "[dim]Not running[/dim]"

    table.add_row("ollama", "[dim]—[/dim]", "[dim]—[/dim]", ollama_ready)

    console.print(table)

    if not quickstart:
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
            from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
            from initrunner.agent.schema.guardrails import Guardrails
            from initrunner.agent.schema.role import AgentSpec, RoleDefinition
            from initrunner.services import _detect_provider
            from initrunner.templates import _default_model_name

            detected_provider = _detect_provider()
            model_name = _default_model_name(detected_provider)
            role = RoleDefinition(
                apiVersion=ApiVersion.V1,
                kind=Kind.AGENT,
                metadata=Metadata(name="doctor-quickstart"),
                spec=AgentSpec(
                    role="You are a helpful assistant.",
                    model=ModelConfig(provider=detected_provider, name=model_name),
                    guardrails=Guardrails(timeout_seconds=60),
                ),
            )
            agent = build_agent(role, role_dir=None)

        from initrunner.agent.executor import execute_run

        with console.status("Running smoke prompt...", spinner="dots"):
            result, _ = execute_run(agent, role, "Say hello in one sentence.")

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
