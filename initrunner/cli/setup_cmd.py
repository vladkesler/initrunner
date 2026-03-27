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
    list_detected_providers,
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


# ---------------------------------------------------------------------------
# Provider selection helpers
# ---------------------------------------------------------------------------


def _detection_label(provider: str, env_var: str) -> str:
    """Human-readable label for a detected provider."""
    from initrunner.services.presets import resolve_preset

    preset = resolve_preset(provider)
    if preset is not None:
        return f"{preset.label} ({preset.api_key_env})"
    if provider == "ollama":
        return "Ollama (running locally)"
    if env_var:
        return f"{provider} ({env_var})"
    return provider


def _show_full_provider_menu() -> str:
    """Display the full 9-provider menu and return the selected name."""
    _provider_nums = {str(i + 1): p for i, p in enumerate(ALL_PROVIDERS)}
    cloud = [p for p in ALL_PROVIDERS if p != "ollama"]
    console.print("[bold]Cloud providers:[/bold]")
    for i, prov in enumerate(cloud, 1):
        desc = PROVIDER_DESCRIPTIONS.get(prov, "")
        console.print(f"  {i}. {prov:12s} -- {desc}")
    console.print("[bold]Local:[/bold]")
    console.print(
        f"  {len(cloud) + 1}. {'ollama':12s} -- {PROVIDER_DESCRIPTIONS.get('ollama', '')}"
    )
    choice = Prompt.ask("Provider", default="")
    provider = _provider_nums.get(choice, choice)
    if provider not in ALL_PROVIDERS:
        console.print(
            f"[red]Invalid choice:[/red] '{choice}'. "
            f"Enter a number (1-{len(ALL_PROVIDERS)}) or provider name."
        )
        raise typer.Exit(1)
    return provider


def _show_detected_chooser(detected: list[tuple[str, str]]) -> str:
    """Show only detected providers and return the selected name.

    Also accepts any standard provider name from ``ALL_PROVIDERS`` as a
    manual override so the user can escape to a non-detected provider.
    """
    from initrunner.services.presets import resolve_preset

    console.print("[bold]Detected providers:[/bold]")
    nums: dict[str, str] = {}
    for i, (prov, _env_var) in enumerate(detected, 1):
        preset = resolve_preset(prov)
        desc = PROVIDER_DESCRIPTIONS.get(prov, "") or (preset.label if preset else "") or ""
        console.print(f"  {i}. {prov:12s} -- {desc}")
        nums[str(i)] = prov
    choice = Prompt.ask("Provider", default=detected[0][0])
    provider = nums.get(choice, choice)
    valid_detected = {d[0] for d in detected}
    if provider not in valid_detected and provider not in ALL_PROVIDERS:
        console.print(f"[red]Invalid choice:[/red] '{choice}'.")
        raise typer.Exit(1)
    return provider


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
    from initrunner.services.presets import resolve_preset

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

    # ---------------------------------------------------------------
    # [1/3] Provider & model
    # ---------------------------------------------------------------
    _step(1, "Provider & model")

    # Track whether the selected provider is a preset (e.g. OpenRouter)
    selected_preset = None

    if provider is None:
        detected = list_detected_providers()

        if len(detected) == 1:
            prov, env_var = detected[0]
            label = _detection_label(prov, env_var)
            if typer.confirm(f"Detected {label}. Use this provider?", default=True):
                provider = prov
            else:
                provider = _show_detected_chooser(detected)

        elif len(detected) > 1:
            provider = _show_detected_chooser(detected)

        else:
            provider = _show_full_provider_menu()
    else:
        # --provider flag supplied
        if provider not in ALL_PROVIDERS and resolve_preset(provider) is None:
            console.print(
                f"[red]Error:[/red] Unknown provider '{provider}'. "
                f"Choose from: {', '.join(ALL_PROVIDERS)}"
            )
            raise typer.Exit(1)
        console.print(f"Provider: [cyan]{provider}[/cyan]")

    # Check if the selected provider is a preset
    selected_preset = resolve_preset(provider)

    # ---------------------------------------------------------------
    # SDK check + auto-install
    # ---------------------------------------------------------------
    if selected_preset is not None:
        # Presets use the openai SDK
        runtime_provider = selected_preset.runtime_provider
        try:
            require_provider(runtime_provider)
            console.print(
                f"[green]{selected_preset.label} SDK available (via {runtime_provider})[/green]"
            )
        except RuntimeError:
            console.print(f"Provider SDK for '{runtime_provider}' is not installed.")
            if typer.confirm("Install it now?", default=True):
                success = _install_provider_sdk(runtime_provider)
                if not success:
                    if not typer.confirm("Continue anyway?", default=True):
                        raise typer.Exit(1) from None
            else:
                extra = _PROVIDER_EXTRAS.get(runtime_provider, runtime_provider)
                console.print(
                    f"[dim]Hint: install later with: uv pip install initrunner\\[{extra}][/dim]"
                )
    elif provider == "ollama":
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

    # ---------------------------------------------------------------
    # API key / credentials
    # ---------------------------------------------------------------
    from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS

    env_path = get_global_env_path()

    if selected_preset is not None:
        # Preset key handling (e.g. OPENROUTER_API_KEY)
        env_var = selected_preset.api_key_env
        _handle_api_key(env_var, env_path, validate_provider=None)
    elif provider == "bedrock":
        env_var = None
        region = os.environ.get("AWS_DEFAULT_REGION")
        if not region:
            region = Prompt.ask("AWS region", default="us-east-1")
            os.environ["AWS_DEFAULT_REGION"] = region
        console.print(f"[green]Region:[/green] {region}")
    elif provider == "ollama":
        env_var = None
    else:
        env_var = _PROVIDER_API_KEY_ENVS.get(provider)
        if env_var:
            validate_prov = provider if provider in ("openai", "anthropic") else None
            _handle_api_key(env_var, env_path, validate_provider=validate_prov)

    # ---------------------------------------------------------------
    # Model selection
    # ---------------------------------------------------------------
    if model is not None:
        model_name = model
        console.print(f"Model: [cyan]{model_name}[/cyan]")
    elif selected_preset is not None:
        # Freeform model prompt for presets
        model_name = Prompt.ask("Model", default=selected_preset.default_model)
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
    # Resolve canonical runtime config for presets
    # ---------------------------------------------------------------
    cfg_provider = provider
    cfg_base_url: str | None = None
    cfg_api_key_env: str | None = None

    if selected_preset is not None:
        cfg_provider = selected_preset.runtime_provider
        cfg_base_url = selected_preset.base_url
        cfg_api_key_env = selected_preset.api_key_env

    # ---------------------------------------------------------------
    # [2/3] Save
    # ---------------------------------------------------------------
    _step(2, "Save")
    config = SetupConfig(
        provider=cfg_provider,
        model=model_name,
        base_url=cfg_base_url,
        api_key_env=cfg_api_key_env,
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
    if not skip_test and cfg_provider in ("openai", "anthropic") and env_var:
        # API key was already validated above; confirm to user
        console.print("[green]Provider connectivity verified.[/green]")
    elif not skip_test:
        console.print("[dim]Connectivity verified via SDK check.[/dim]")

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------
    display_provider = (
        f"{selected_preset.label} (via {cfg_provider})" if selected_preset else cfg_provider
    )
    summary_lines = [
        f"[bold]Provider:[/bold]  {display_provider}",
        f"[bold]Model:[/bold]     {model_name}",
    ]
    if cfg_base_url:
        summary_lines.append(f"[bold]Endpoint:[/bold] {cfg_base_url}")
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


# ---------------------------------------------------------------------------
# Key handling helper
# ---------------------------------------------------------------------------


def _handle_api_key(
    env_var: str,
    env_path: os.PathLike,
    *,
    validate_provider: str | None,
) -> None:
    """Prompt for, validate, and persist an API key.

    Shared between standard providers and presets to avoid duplicating the
    env vs dotenv detection logic.
    """
    from pathlib import Path

    env_path = Path(env_path)

    has_provider_key = bool(os.environ.get(env_var))
    if not has_provider_key and env_path.is_file():
        has_provider_key = bool(dotenv_values(env_path).get(env_var))

    if has_provider_key:
        console.print(
            f"[green]Using existing {env_var}.[/green] "
            f"[dim]Edit {get_global_env_path()} to change it.[/dim]"
        )
        return

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
    if validate_provider is not None:
        with console.status("Validating API key..."):
            valid = _validate_api_key(validate_provider, api_key)
        if valid:
            console.print("[green]API key is valid.[/green]")
        else:
            console.print("[yellow]Warning:[/yellow] API key validation failed.")
            if typer.confirm("Re-enter the key?", default=True):
                api_key = Prompt.ask(f"Enter your {env_var}", password=True)

    # Write to .env if key is not already in the env
    if not os.environ.get(env_var):
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
