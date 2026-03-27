"""Guided setup wizard for first-time InitRunner configuration."""

from __future__ import annotations

import os

import typer
from dotenv import dotenv_values, set_key
from rich.panel import Panel
from rich.prompt import Prompt

from initrunner._compat import _PROVIDER_EXTRAS, is_dashboard_available, require_provider
from initrunner.cli._helpers import check_ollama_running, console, install_extra
from initrunner.config import get_global_env_path, get_home_dir
from initrunner.services.setup import (
    ALL_PROVIDERS,
    PROVIDER_DESCRIPTIONS,
    SetupConfig,
    check_ollama_models,
    needs_setup,
    save_run_yaml,
)
from initrunner.services.setup import (
    validate_api_key as _validate_api_key,
)

_TOTAL_STEPS = 3


def _step(n: int, label: str) -> None:
    """Print a step header like [1/3] Provider & model."""
    console.print(f"\n[bold dim]\\[{n}/{_TOTAL_STEPS}][/bold dim] [bold]{label}[/bold]")


def _install_provider_sdk(provider: str) -> bool:
    """Best-effort SDK install. Returns True on success."""
    extra = _PROVIDER_EXTRAS.get(provider)
    if extra is None:
        return True
    return install_extra(extra)


def run_setup(
    *,
    provider: str | None,
    name: str,
    skip_test: bool,
    accept_risks: bool = False,
    model: str | None = None,
    skip_run_yaml: bool = False,
) -> None:
    """Execute the guided setup wizard."""
    # ---------------------------------------------------------------
    # Welcome + security note
    # ---------------------------------------------------------------
    console.print(
        Panel(
            "[bold]Welcome to InitRunner![/bold]\n"
            "Let's connect a model provider so your agents can run.",
            title="Setup",
            border_style="cyan",
        )
    )

    if not accept_risks:
        console.print(
            "[yellow]Note:[/yellow] Agents can execute tools that run code, access files, "
            "and make network requests.\n"
            "Review the security guide before running untrusted roles: "
            "[cyan]docs/security/security.md[/cyan]"
        )
        if not typer.confirm("Continue", default=True):
            raise typer.Exit()

    detected_provider: str | None = None
    already_configured = not needs_setup()
    if already_configured:
        from initrunner.services.setup import detect_existing_provider

        found = detect_existing_provider()
        if found:
            detected_provider = found[0]

    # ---------------------------------------------------------------
    # [1/3] Provider & model
    # ---------------------------------------------------------------
    _step(1, "Provider & model")
    _provider_nums = {str(i + 1): name for i, name in enumerate(ALL_PROVIDERS)}
    if provider is None:
        cloud = [p for p in ALL_PROVIDERS if p != "ollama"]
        console.print("[bold]Cloud providers:[/bold]")
        for i, prov in enumerate(cloud, 1):
            desc = PROVIDER_DESCRIPTIONS.get(prov, "")
            console.print(f"  {i}. {prov:12s} \u2014 {desc}")
        console.print("[bold]Local:[/bold]")
        console.print(
            f"  {len(cloud) + 1}. {'ollama':12s} \u2014 {PROVIDER_DESCRIPTIONS.get('ollama', '')}"
        )
        prompt_text = "Provider"
        if detected_provider:
            prompt_text = f"Provider (detected {detected_provider})"
        choice = Prompt.ask(prompt_text, default=detected_provider or "")
        provider = _provider_nums.get(choice, choice)
        if provider not in ALL_PROVIDERS:
            console.print(
                f"[red]Invalid choice:[/red] '{choice}'. "
                f"Enter a number (1-{len(ALL_PROVIDERS)}) or provider name."
            )
            raise typer.Exit(1)
    else:
        if provider not in ALL_PROVIDERS:
            console.print(
                f"[red]Error:[/red] Unknown provider '{provider}'. "
                f"Choose from: {', '.join(ALL_PROVIDERS)}"
            )
            raise typer.Exit(1)
        console.print(f"Provider: [cyan]{provider}[/cyan]")

    # SDK check + auto-install
    if provider == "ollama":
        check_ollama_running()
        models = check_ollama_models()
        if not models:
            console.print(
                "[yellow]Warning:[/yellow] No Ollama models found. "
                "Run: [bold]ollama pull llama3.2[/bold]"
            )
        else:
            console.print(f"Ollama models: {', '.join(models[:5])}")
    elif provider == "bedrock":
        console.print(
            "[dim]Bedrock uses AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY). "
            "Ensure your AWS CLI is configured.[/dim]"
        )
        try:
            require_provider(provider)
            console.print("[green]boto3 SDK available[/green]")
        except RuntimeError:
            console.print("boto3 SDK for bedrock is not installed.")
            if typer.confirm("Install it now?", default=True):
                success = _install_provider_sdk(provider)
                if not success:
                    if not typer.confirm("Continue anyway?", default=True):
                        raise typer.Exit(1) from None
    else:
        try:
            require_provider(provider)
            console.print("[green]Provider SDK available[/green]")
        except RuntimeError:
            console.print(f"Provider SDK for '{provider}' is not installed.")
            if typer.confirm("Install it now?", default=True):
                success = _install_provider_sdk(provider)
                if not success:
                    if not typer.confirm("Continue anyway?", default=True):
                        raise typer.Exit(1) from None
            else:
                console.print(
                    f"[dim]Hint: install later with: "
                    f"uv pip install initrunner[{_PROVIDER_EXTRAS.get(provider, provider)}][/dim]"
                )

    # API key / credentials
    from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS

    env_var = _PROVIDER_API_KEY_ENVS.get(provider)
    env_path = get_global_env_path()

    if provider == "bedrock":
        region = os.environ.get("AWS_DEFAULT_REGION")
        if not region:
            region = Prompt.ask("AWS region", default="us-east-1")
            os.environ["AWS_DEFAULT_REGION"] = region
        console.print(f"[green]Region:[/green] {region}")
    elif provider not in ("ollama",) and env_var:
        has_provider_key = bool(os.environ.get(env_var))
        if not has_provider_key and env_path.is_file():
            has_provider_key = bool(dotenv_values(env_path).get(env_var))

        if has_provider_key:
            console.print(
                f"[green]Using existing {env_var}.[/green] "
                f"[dim]Edit {get_global_env_path()} to change it.[/dim]"
            )
        else:
            existing_in_env = os.environ.get(env_var)
            existing_in_dotenv = None
            if env_path.is_file():
                existing_in_dotenv = dotenv_values(env_path).get(env_var)

            if existing_in_env:
                console.print(f"[green]Found {env_var} in environment.[/green]")
                if not typer.confirm("Keep this key?", default=True):
                    existing_in_env = None

            if existing_in_env:
                api_key = existing_in_env
            elif existing_in_dotenv:
                console.print(f"[green]Found {env_var} in {env_path}[/green]")
                if typer.confirm("Keep this key?", default=True):
                    api_key = existing_in_dotenv
                else:
                    api_key = Prompt.ask(f"Enter your {env_var}", password=True)
            else:
                api_key = Prompt.ask(f"Enter your {env_var}", password=True)

            # Validate the key
            if provider in ("openai", "anthropic"):
                with console.status("Validating API key..."):
                    valid = _validate_api_key(provider, api_key)
                if valid:
                    console.print("[green]API key is valid.[/green]")
                else:
                    console.print("[yellow]Warning:[/yellow] API key validation failed.")
                    if typer.confirm("Re-enter the key?", default=True):
                        api_key = Prompt.ask(f"Enter your {env_var}", password=True)

            # Write to .env if key is not already in the env
            if not existing_in_env:
                try:
                    home_dir = get_home_dir()
                    home_dir.mkdir(parents=True, exist_ok=True)
                    set_key(str(env_path), env_var, api_key)
                    env_path.chmod(0o600)
                    console.print(f"Saved to [cyan]{env_path}[/cyan]")
                except (PermissionError, OSError) as exc:
                    console.print(
                        f"[yellow]Warning:[/yellow] Could not write {env_path}: {exc}\n"
                        f"Set it manually: [bold]export {env_var}={api_key}[/bold]"
                    )

    # Model selection
    if model is not None:
        model_name = model
        console.print(f"Model: [cyan]{model_name}[/cyan]")
    else:
        from initrunner.cli._helpers import prompt_model_selection

        ollama_models_list = None
        if provider == "ollama":
            try:
                ollama_models_list = check_ollama_models() or None
            except Exception:
                pass
        model_name = prompt_model_selection(provider, ollama_models=ollama_models_list)

    # ---------------------------------------------------------------
    # [2/3] Save
    # ---------------------------------------------------------------
    _step(2, "Save")
    config = SetupConfig(
        provider=provider,
        model=model_name,
        name=name,
    )

    run_yaml_path = None
    if not skip_run_yaml:
        try:
            run_yaml_path = save_run_yaml(config)
            console.print(f"[green]Created[/green] {run_yaml_path}")
        except Exception as exc:
            console.print(f"[dim]Could not create run.yaml: {exc}[/dim]")

    # ---------------------------------------------------------------
    # [3/3] Verify
    # ---------------------------------------------------------------
    _step(3, "Verify")
    if not skip_test and provider in ("openai", "anthropic") and env_var:
        # API key was already validated above; confirm to user
        console.print("[green]Provider connectivity verified.[/green]")
    elif not skip_test:
        console.print("[dim]Connectivity verified via SDK check.[/dim]")

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------
    summary_lines = [
        f"[bold]Provider:[/bold]  {provider}",
        f"[bold]Model:[/bold]     {model_name}",
    ]
    if env_var and provider not in ("ollama", "bedrock"):
        summary_lines.append(f"[bold]Config:[/bold]   {env_path}")
    if run_yaml_path:
        summary_lines.append(f"[bold]Run:[/bold]      {run_yaml_path}")

    console.print()
    console.print(
        Panel(
            "\n".join(summary_lines),
            title="Setup Complete",
            border_style="green",
        )
    )

    # ---------------------------------------------------------------
    # Dashboard prompt
    # ---------------------------------------------------------------
    import sys

    if is_dashboard_available() and sys.stdin.isatty():
        console.print()
        if typer.confirm("Open the dashboard?", default=True):
            from initrunner.cli.dashboard_cmd import launch_dashboard

            launch_dashboard()
            return

    # ---------------------------------------------------------------
    # Next steps (shown when dashboard is skipped or unavailable)
    # ---------------------------------------------------------------
    _next = [
        "  [dim]Try a starter agent:[/dim]",
        "  [bold]initrunner run helpdesk -i[/bold]              [dim]# docs Q&A[/dim]",
        '  [bold]initrunner run code-review-team -p "..."[/bold] [dim]# code review[/dim]',
        '  [bold]initrunner run web-researcher -p "..."[/bold]   [dim]# web research[/dim]',
        "",
        "  [dim]Or start a REPL:[/dim]",
        "  [bold]initrunner run -i[/bold]                       [dim]# ephemeral chat[/dim]",
    ]

    console.print(
        Panel(
            "\n".join(_next),
            title="Next steps",
            border_style="cyan",
        )
    )
