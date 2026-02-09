"""Guided setup wizard for first-time InitRunner configuration."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import typer
from dotenv import dotenv_values, set_key
from rich.panel import Panel
from rich.prompt import Prompt

from initrunner._compat import _PROVIDER_EXTRAS, require_provider
from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS
from initrunner.cli._helpers import check_ollama_running, console, install_extra
from initrunner.config import get_global_env_path, get_home_dir
from initrunner.templates import TEMPLATES, _default_model_name

_PROVIDERS = ["openai", "anthropic", "google", "groq", "mistral", "cohere", "ollama"]

# User-friendly names -> template function keys
_SETUP_TEMPLATES = {
    "chatbot": "basic",
    "rag": "rag",
    "memory": "memory",
    "daemon": "daemon",
}

# Allow users to type a number (1-4) instead of the template name
_TEMPLATE_CHOICES = ["chatbot", "rag", "memory", "daemon"]
_TEMPLATE_NUMS = {str(i + 1): name for i, name in enumerate(_TEMPLATE_CHOICES)}

_INTERFACE_NUMS = {"1": "tui", "2": "dashboard", "3": "both", "4": "skip"}


def needs_setup() -> bool:
    """True if no API key is configured anywhere."""
    for env_var in _PROVIDER_API_KEY_ENVS.values():
        if os.environ.get(env_var):
            return False
    env_path = get_global_env_path()
    if env_path.is_file():
        values = dotenv_values(env_path)
        for env_var in _PROVIDER_API_KEY_ENVS.values():
            if values.get(env_var):
                return False
    return True


def _validate_api_key(provider: str, api_key: str) -> bool:
    """Lightweight API key validation. Returns True if key appears valid."""
    try:
        if provider == "openai":
            req = urllib.request.Request(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            urllib.request.urlopen(req, timeout=5)
            return True
        if provider == "anthropic":
            import json as _json

            body = _json.dumps(
                {
                    "model": "claude-sonnet-4-5-20250929",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                }
            ).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=body,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            urllib.request.urlopen(req, timeout=5)
            return True
    except Exception:
        return False
    # Other providers: skip validation
    return True


def _check_ollama_models() -> list[str]:
    """Query Ollama for available models. Returns list of model names."""
    try:
        resp = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


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
    template: str | None,
    skip_test: bool,
    output: Path,
    accept_risks: bool = False,
    interfaces: str | None = None,
) -> None:
    """Execute the guided setup wizard."""
    # ---------------------------------------------------------------
    # Step 0: Security disclaimer (beta)
    # ---------------------------------------------------------------
    if not accept_risks:
        console.print(
            Panel(
                "[bold yellow]Beta Software Notice[/bold yellow]\n\n"
                "InitRunner executes AI agent tools that can run code, access files, "
                "and make network requests on your machine.\n\n"
                "[bold]Recommended safeguards:[/bold]\n"
                "  \u2022 Set guardrails (max_tokens_per_run, max_tool_calls, timeout_seconds)\n"
                "  \u2022 Enable content filtering "
                "(blocked_input_patterns, blocked_output_patterns)\n"
                "  \u2022 Use the PEP 578 sandbox for untrusted tools "
                "(audit_hooks_enabled: true)\n"
                "  \u2022 Restrict network access (allowed_network_hosts, block_private_ips)\n"
                "  \u2022 Review roles before running \u2014 never run untrusted YAML\n\n"
                "See: [cyan]docs/security/security.md[/cyan] \u00b7 "
                "[cyan]docs/configuration/guardrails.md[/cyan]",
                title="\u26a0 Security",
                border_style="yellow",
            )
        )
        if not typer.confirm("I understand the risks and want to continue", default=True):
            raise typer.Exit()

    # ---------------------------------------------------------------
    # Step 1: Welcome + already-configured detection
    # ---------------------------------------------------------------
    console.print(
        Panel(
            "[bold]Welcome to InitRunner![/bold]\n"
            "This wizard will configure your provider, API key, and first agent role.",
            title="Setup",
            border_style="cyan",
        )
    )

    already_configured = not needs_setup()
    if already_configured:
        found_provider, found_key_var = None, None
        for prov, env_var in _PROVIDER_API_KEY_ENVS.items():
            if os.environ.get(env_var):
                found_provider, found_key_var = prov, env_var
                break
        if found_provider is None:
            env_path = get_global_env_path()
            if env_path.is_file():
                values = dotenv_values(env_path)
                for prov, env_var in _PROVIDER_API_KEY_ENVS.items():
                    if values.get(env_var):
                        found_provider, found_key_var = prov, env_var
                        break
        console.print(
            f"Found [cyan]{found_key_var}[/cyan] in your environment. "
            f"Using provider: [cyan]{found_provider}[/cyan]"
        )
        if provider is None:
            provider = found_provider

    # ---------------------------------------------------------------
    # Step 2: Provider selection
    # ---------------------------------------------------------------
    if provider is None:
        provider = Prompt.ask(
            "Select a model provider",
            choices=_PROVIDERS,
        )
    else:
        if provider not in _PROVIDERS:
            console.print(
                f"[red]Error:[/red] Unknown provider '{provider}'. "
                f"Choose from: {', '.join(_PROVIDERS)}"
            )
            raise typer.Exit(1)
        console.print(f"Provider: [cyan]{provider}[/cyan]")

    # ---------------------------------------------------------------
    # Step 3: Dependency check
    # ---------------------------------------------------------------
    if provider == "ollama":
        check_ollama_running()
        models = _check_ollama_models()
        if not models:
            console.print(
                "[yellow]Warning:[/yellow] No Ollama models found. "
                "Run: [bold]ollama pull llama3.2[/bold]"
            )
        else:
            console.print(f"Ollama models: {', '.join(models[:5])}")
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
                    f"pip install initrunner[{_PROVIDER_EXTRAS.get(provider, provider)}][/dim]"
                )

    # ---------------------------------------------------------------
    # Step 4: API key entry + immediate validation
    # ---------------------------------------------------------------
    env_var = _PROVIDER_API_KEY_ENVS.get(provider)
    env_path = get_global_env_path()

    if provider != "ollama" and env_var:
        if already_configured:
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

    # ---------------------------------------------------------------
    # Step 5: Role creation via template picker
    # ---------------------------------------------------------------
    if output.exists():
        console.print(f"[dim]{output} already exists, skipping role creation.[/dim]")
    else:
        if template is None:
            console.print()
            console.print("[bold]Choose a starter template:[/bold]")
            console.print("  1. chatbot  — Simple assistant, great for getting started")
            console.print("  2. rag      — Answers questions from your documents")
            console.print("  3. memory   — Remembers things across conversations")
            console.print("  4. daemon   — Runs on a schedule or watches files for changes")
            choice = Prompt.ask("Template [1-4]")
            # Accept number or name
            template = _TEMPLATE_NUMS.get(choice, choice)
            if template not in _SETUP_TEMPLATES:
                console.print(
                    f"[red]Invalid choice:[/red] '{choice}'. "
                    "Enter a number (1-4) or name (chatbot, rag, memory, daemon)."
                )
                raise typer.Exit(1)
        else:
            if template not in _SETUP_TEMPLATES:
                console.print(
                    f"[red]Error:[/red] Unknown template '{template}'. "
                    f"Choose from: {', '.join(_SETUP_TEMPLATES)}"
                )
                raise typer.Exit(1)
            console.print(f"Template: [cyan]{template}[/cyan]")

        # Map user-friendly name to template key
        if provider == "ollama":
            template_key = "ollama"
        else:
            template_key = _SETUP_TEMPLATES[template]

        builder = TEMPLATES[template_key]
        content = builder(name, provider)
        output.write_text(content)
        console.print(f"[green]Created[/green] {output}")

    # ---------------------------------------------------------------
    # Step 5b: Optional interface installation
    # ---------------------------------------------------------------
    if interfaces is None:
        console.print()
        console.print("[bold]Install an interface?[/bold]")
        console.print("  1. tui       — Terminal dashboard (Textual)")
        console.print("  2. dashboard — Web dashboard (FastAPI)")
        console.print("  3. both      — Install both")
        console.print("  4. skip      — Skip for now")
        choice = Prompt.ask("Interface [1-4]")
        interfaces = _INTERFACE_NUMS.get(choice, choice)
        if interfaces not in ("tui", "dashboard", "both", "skip"):
            console.print(f"[red]Invalid choice:[/red] '{choice}'. Skipping.")
            interfaces = "skip"

    if interfaces in ("tui", "both"):
        install_extra("tui")
    if interfaces in ("dashboard", "both"):
        install_extra("dashboard")
    if interfaces == "skip":
        console.print(
            "[dim]Install later: pip install 'initrunner[tui]' or 'initrunner[dashboard]'[/dim]"
        )

    # ---------------------------------------------------------------
    # Step 6: Test run (skippable)
    # ---------------------------------------------------------------
    if not skip_test:
        console.print()
        console.print("[bold]Running a quick test...[/bold]")
        try:
            from initrunner.agent.executor import execute_run
            from initrunner.agent.loader import _load_dotenv, load_and_build

            _load_dotenv(output.parent)
            role, agent = load_and_build(output)
            result, _ = execute_run(agent, role, "Hello, respond in one sentence.")
            if result.success:
                preview = result.output[:200]
                console.print(f"[green]Test passed![/green] Response: {preview}")
            else:
                console.print(
                    f"[yellow]Warning:[/yellow] Test run failed: {result.error}\n"
                    "Setup is still complete — check your configuration and try again."
                )
        except Exception as exc:
            console.print(
                f"[yellow]Warning:[/yellow] Test run failed: {exc}\n"
                "Setup is still complete — check your configuration and try again."
            )

    # ---------------------------------------------------------------
    # Step 7: Success summary
    # ---------------------------------------------------------------
    model_name = _default_model_name(provider)
    summary_lines = [
        f"[bold]Provider:[/bold]  {provider}",
        f"[bold]Model:[/bold]     {model_name}",
    ]
    if env_var and provider != "ollama":
        summary_lines.append(f"[bold]Config:[/bold]   {env_path}")
    summary_lines.append(f"[bold]Role:[/bold]     {output}")

    console.print()
    console.print(
        Panel(
            "\n".join(summary_lines),
            title="Setup Complete",
            border_style="green",
        )
    )

    console.print("[bold]Next steps:[/bold]")
    console.print(f'  initrunner run {output} -p "Ask me anything"')
    console.print(f"  initrunner run {output} -i          # interactive REPL")
    console.print(f"  initrunner validate {output}")
    console.print("  initrunner init --template rag     # more templates")
    console.print("  initrunner tui                     # terminal dashboard")
    console.print("  initrunner ui                      # web dashboard")
