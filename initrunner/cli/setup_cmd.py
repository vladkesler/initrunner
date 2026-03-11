"""Guided setup wizard for first-time InitRunner configuration."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from dotenv import dotenv_values, set_key
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from initrunner._compat import _PROVIDER_EXTRAS, require_provider
from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS
from initrunner.cli._helpers import check_ollama_running, console, install_extra
from initrunner.config import get_global_env_path, get_home_dir
from initrunner.services.setup import (
    ALL_PROVIDERS,
    BOT_TOKEN_ENVS,
    INTENT_DEFAULT_TOOLS,
    INTENT_DESCRIPTIONS,
    INTENT_TEMPLATE_MAP,
    SetupConfig,
    check_ollama_models,
    generate_role_yaml,
    needs_setup,
    provider_needs_embeddings_warning,
    run_connectivity_test,
    save_chat_yaml,
)
from initrunner.services.setup import (
    validate_api_key as _validate_api_key,
)

# Numbered lookup tables for interactive prompts
_INTENT_CHOICES = list(INTENT_DESCRIPTIONS.keys())
_INTENT_NUMS = {str(i + 1): name for i, name in enumerate(_INTENT_CHOICES)}

_INTERFACE_NUMS = {"1": "tui", "2": "dashboard", "3": "both", "4": "skip"}


def _install_provider_sdk(provider: str) -> bool:
    """Best-effort SDK install. Returns True on success."""
    extra = _PROVIDER_EXTRAS.get(provider)
    if extra is None:
        return True
    return install_extra(extra)


def _run_example_flow() -> None:
    """Browse and copy a bundled example. Self-contained flow."""
    from initrunner.examples import ExampleNotFoundError, copy_example, list_examples

    entries = list_examples()
    if not entries:
        console.print("[yellow]No examples found in catalog.[/yellow]")
        return

    table = Table(title="Bundled Examples", show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Name", style="cyan")
    table.add_column("Category", style="green")
    table.add_column("Description")

    for i, entry in enumerate(entries, 1):
        table.add_row(str(i), entry.name, entry.category, entry.description)
    console.print(table)

    choice = Prompt.ask("Select an example (number or name)")
    name = None
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(entries):
            name = entries[idx].name
    else:
        name = choice

    if name is None:
        console.print(f"[red]Invalid choice:[/red] '{choice}'.")
        raise typer.Exit(1)

    try:
        written = copy_example(name, Path("."))
    except (ExampleNotFoundError, FileExistsError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from None

    console.print()
    console.print(f"[green]Copied {len(written)} file(s):[/green]")
    for p in written:
        console.print(f"  {p}")

    console.print(
        Panel(
            "  [dim]Validate:[/dim]\n"
            f"  [bold]initrunner validate {written[0]}[/bold]\n\n"
            "  [dim]Run:[/dim]\n"
            f"  [bold]initrunner run {written[0]}[/bold]",
            title="Next steps",
            border_style="cyan",
        )
    )


def run_setup(
    *,
    provider: str | None,
    name: str,
    intent: str | None = None,
    skip_test: bool,
    output: Path,
    accept_risks: bool = False,
    interfaces: str | None = None,
    model: str | None = None,
    skip_chat_yaml: bool = False,
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
        from initrunner.services.setup import detect_existing_provider

        found = detect_existing_provider()
        if found:
            found_provider, found_key_var = found
            console.print(
                f"Found [cyan]{found_key_var}[/cyan] in your environment. "
                f"Using provider: [cyan]{found_provider}[/cyan]"
            )
            if provider is None:
                provider = found_provider

    # ---------------------------------------------------------------
    # Step 2: Intent selection (replaces template picker)
    # ---------------------------------------------------------------
    if intent is None:
        console.print()
        console.print("[bold]What do you want to build?[/bold]")
        for i, (key, desc) in enumerate(INTENT_DESCRIPTIONS.items(), 1):
            console.print(f"  {i}. {key:14s} \u2014 {desc}")
        choice = Prompt.ask(f"Intent [1-{len(INTENT_DESCRIPTIONS)}]")
        intent = _INTENT_NUMS.get(choice, choice)
        if intent not in INTENT_DESCRIPTIONS:
            console.print(
                f"[red]Invalid choice:[/red] '{choice}'. "
                f"Enter a number (1-{len(INTENT_DESCRIPTIONS)}) or intent name."
            )
            raise typer.Exit(1)
    else:
        if intent not in INTENT_DESCRIPTIONS:
            console.print(
                f"[red]Error:[/red] Unknown intent '{intent}'. "
                f"Choose from: {', '.join(INTENT_DESCRIPTIONS)}"
            )
            raise typer.Exit(1)
        console.print(f"Intent: [cyan]{intent}[/cyan]")

    # ---------------------------------------------------------------
    # from-example: separate flow, return early
    # ---------------------------------------------------------------
    if intent == "from-example":
        _run_example_flow()
        return

    # ---------------------------------------------------------------
    # Step 3: Provider selection (expanded: all 9 providers)
    # ---------------------------------------------------------------
    if provider is None:
        console.print()
        for i, prov in enumerate(ALL_PROVIDERS, 1):
            console.print(f"  {i}. {prov}")
        provider = Prompt.ask(
            "Select a model provider",
            choices=ALL_PROVIDERS,
        )
    else:
        if provider not in ALL_PROVIDERS:
            console.print(
                f"[red]Error:[/red] Unknown provider '{provider}'. "
                f"Choose from: {', '.join(ALL_PROVIDERS)}"
            )
            raise typer.Exit(1)
        console.print(f"Provider: [cyan]{provider}[/cyan]")

    # ---------------------------------------------------------------
    # Step 4: SDK check + auto-install
    # ---------------------------------------------------------------
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
                    f"pip install initrunner[{_PROVIDER_EXTRAS.get(provider, provider)}][/dim]"
                )

    # ---------------------------------------------------------------
    # Step 5: API key / credentials entry + validation
    # ---------------------------------------------------------------
    env_var = _PROVIDER_API_KEY_ENVS.get(provider)
    env_path = get_global_env_path()

    if provider == "bedrock":
        # Bedrock uses AWS credentials, not a single API key
        region = os.environ.get("AWS_DEFAULT_REGION")
        if not region:
            region = Prompt.ask("AWS region", default="us-east-1")
            os.environ["AWS_DEFAULT_REGION"] = region
        console.print(f"[green]Region:[/green] {region}")
    elif provider not in ("ollama",) and env_var:
        # Check if THIS provider's key is actually available
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

    # ---------------------------------------------------------------
    # Step 6: Model selection
    # ---------------------------------------------------------------
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
    # Step 7: Embedding config (conditional)
    # ---------------------------------------------------------------
    embedding_provider = None
    if provider_needs_embeddings_warning(provider, intent):
        console.print()
        console.print(
            f"[bold yellow]Warning:[/bold yellow] {provider} does not provide an embeddings API. "
            "RAG and memory features require [bold]OPENAI_API_KEY[/bold] for embeddings.\n"
            "You can override this in your role.yaml under "
            "[bold]spec.ingest.embeddings[/bold] or [bold]spec.memory.embeddings[/bold]."
        )
        if os.environ.get("OPENAI_API_KEY") or (
            env_path.is_file() and dotenv_values(env_path).get("OPENAI_API_KEY")
        ):
            console.print("[green]OPENAI_API_KEY detected — embeddings will work.[/green]")
            embedding_provider = "openai"
        else:
            if typer.confirm("Enter an OPENAI_API_KEY for embeddings?", default=False):
                emb_key = Prompt.ask("OPENAI_API_KEY", password=True)
                from initrunner.services.setup import save_env_key

                result = save_env_key("OPENAI_API_KEY", emb_key)
                if result:
                    console.print(f"Saved to [cyan]{result}[/cyan]")
                    embedding_provider = "openai"

    # ---------------------------------------------------------------
    # Step 8: Tool selection + configure
    # ---------------------------------------------------------------
    tools: list[dict] = []
    if not output.exists():
        from initrunner.templates import TOOL_DESCRIPTIONS, TOOL_PROMPT_FIELDS

        available_tools = list(TOOL_DESCRIPTIONS.keys())
        defaults = INTENT_DEFAULT_TOOLS.get(intent, [])

        console.print()
        console.print(
            "[bold]Add tools?[/bold] "
            "(enter tool numbers separated by comma, or press Enter for defaults)"
        )
        for i, tool_type in enumerate(available_tools, 1):
            desc = TOOL_DESCRIPTIONS[tool_type]
            marker = " *" if tool_type in defaults else ""
            console.print(f"  {i:2d}. {tool_type:12s} \u2014 {desc}{marker}")
        if defaults:
            console.print(f"  [dim]* = default for {intent}[/dim]")

        tool_input = Prompt.ask("Tools (e.g. 1,3,5)", default="")
        selected_tools: list[str] = []
        if tool_input.strip():
            for part in tool_input.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(available_tools):
                        selected_tools.append(available_tools[idx])
                elif part in available_tools:
                    selected_tools.append(part)
        else:
            selected_tools = list(defaults)

        # Configure each selected tool.
        # When user accepted defaults (empty input), use default configs silently.
        # When user explicitly picked tools, prompt for per-tool config.
        user_picked = bool(tool_input.strip())
        for tool_type in selected_tools:
            tool_config: dict = {"type": tool_type}
            fields = TOOL_PROMPT_FIELDS.get(tool_type, [])

            for field_name, prompt_text, default in fields:
                if user_picked:
                    value = Prompt.ask(f"  {tool_type} \u2014 {prompt_text}", default=default)
                else:
                    value = default

                if value.lower() in ("true", "yes", "y"):
                    tool_config[field_name] = True
                elif value.lower() in ("false", "no", "n"):
                    tool_config[field_name] = False
                else:
                    try:
                        tool_config[field_name] = int(value)
                    except ValueError:
                        tool_config[field_name] = value

            tools.append(tool_config)

        if selected_tools:
            console.print(f"  [dim]Selected: {', '.join(selected_tools)}[/dim]")

    # ---------------------------------------------------------------
    # Step 9: Intent-specific config
    # ---------------------------------------------------------------
    ingest_sources = None
    triggers = None

    if intent == "knowledge" and not output.exists():
        sources = Prompt.ask("Document sources glob", default="./docs/**/*.md")
        ingest_sources = [sources]

    if intent in ("telegram-bot", "discord-bot") and not output.exists():
        token_env = BOT_TOKEN_ENVS.get(intent)
        if token_env and not os.environ.get(token_env):
            token_val = Prompt.ask(f"Enter your {token_env}", password=True)
            if token_val.strip():
                from initrunner.services.setup import save_env_key

                result = save_env_key(token_env, token_val)
                if result:
                    console.print(f"Saved to [cyan]{result}[/cyan]")

    if intent == "daemon" and not output.exists():
        console.print()
        console.print("[bold]Trigger type:[/bold]")
        console.print("  1. file_watch — Watch files for changes")
        console.print("  2. cron       — Run on a schedule")
        trigger_choice = Prompt.ask("Trigger [1-2]", default="1")
        if trigger_choice in ("1", "file_watch"):
            watch_paths = Prompt.ask("Watch paths", default="./watched")
            triggers = [
                {
                    "type": "file_watch",
                    "paths": [watch_paths],
                    "extensions": [".md", ".txt"],
                    "prompt_template": "File changed: {path}. Summarize the changes.",
                }
            ]
        else:
            schedule = Prompt.ask("Cron schedule", default="0 */6 * * *")
            triggers = [
                {
                    "type": "cron",
                    "schedule": schedule,
                    "prompt": "Run your periodic check.",
                }
            ]

    # ---------------------------------------------------------------
    # Step 10: Interface installation
    # ---------------------------------------------------------------
    if interfaces is None:
        console.print()
        console.print("[bold]Install an interface?[/bold]")
        console.print("  1. tui       \u2014 Terminal dashboard (Textual)")
        console.print("  2. dashboard \u2014 Web dashboard (FastAPI)")
        console.print("  3. both      \u2014 Install both")
        console.print("  4. skip      \u2014 Skip for now")
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
    # Step 11: Generate role.yaml + chat.yaml
    # ---------------------------------------------------------------
    config = SetupConfig(
        intent=intent,
        provider=provider,
        model=model_name,
        name=name,
        tools=tools,
        enable_memory=intent == "memory",
        ingest_sources=ingest_sources,
        triggers=triggers,
        embedding_provider=embedding_provider,
    )

    template_key = INTENT_TEMPLATE_MAP.get(intent)

    if output.exists():
        console.print(f"[dim]{output} already exists, skipping role creation.[/dim]")
    else:
        content = generate_role_yaml(config)
        output.write_text(content)
        console.print(f"[green]Created[/green] {output}")

    # chat.yaml
    chat_yaml_path = None
    if not skip_chat_yaml:
        try:
            chat_yaml_path = save_chat_yaml(config)
            console.print(f"[green]Created[/green] {chat_yaml_path}")
        except Exception as exc:
            console.print(f"[dim]Could not create chat.yaml: {exc}[/dim]")

    # ---------------------------------------------------------------
    # Step 12: Post-generation actions
    # ---------------------------------------------------------------
    if intent == "knowledge" and output.exists() and not skip_test:
        if typer.confirm("Run ingestion now?", default=True):
            console.print("[bold]Running ingestion...[/bold]")
            from initrunner.services.setup import run_ingest_for_role

            if run_ingest_for_role(output):
                console.print("[green]Ingestion complete.[/green]")
            else:
                console.print(
                    "[yellow]Warning:[/yellow] Ingestion failed. "
                    "Run manually: [bold]initrunner ingest " + str(output) + "[/bold]"
                )

    if not skip_test:
        console.print()
        console.print("[bold]Running a quick test...[/bold]")
        success, message = run_connectivity_test(output)
        if success:
            console.print(f"[green]Test passed![/green] Response: {message}")
        else:
            console.print(
                f"[yellow]Warning:[/yellow] Test run failed: {message}\n"
                "Setup is still complete \u2014 check your configuration and try again."
            )

    # ---------------------------------------------------------------
    # Step 13: Summary + contextual next steps
    # ---------------------------------------------------------------
    summary_lines = [
        f"[bold]Intent:[/bold]    {intent}",
        f"[bold]Provider:[/bold]  {provider}",
        f"[bold]Model:[/bold]     {model_name}",
    ]
    if env_var and provider not in ("ollama", "bedrock"):
        summary_lines.append(f"[bold]Config:[/bold]   {env_path}")
    summary_lines.append(f"[bold]Role:[/bold]     {output}")
    if chat_yaml_path:
        summary_lines.append(f"[bold]Chat:[/bold]     {chat_yaml_path}")

    console.print()
    console.print(
        Panel(
            "\n".join(summary_lines),
            title="Setup Complete",
            border_style="green",
        )
    )

    _role = str(output)
    _next: list[str] = []

    if template_key == "rag":
        _next += [
            "  [dim]Index your documents first:[/dim]",
            f"  [bold]initrunner ingest {_role}[/bold]",
            "",
        ]

    if intent in ("telegram-bot", "discord-bot"):
        _next += [
            f"  [dim]Start the {intent.replace('-bot', '')} bot:[/dim]",
            f"  [bold]initrunner run {_role} --daemon[/bold]",
            "",
        ]
    elif intent == "daemon":
        _next += [
            "  [dim]Start the daemon:[/dim]",
            f"  [bold]initrunner run {_role} --daemon[/bold]",
            "",
        ]

    _next += [
        "  [dim]Create your agent:[/dim]",
        "  [bold]initrunner examples list[/bold]         [dim]# 1. browse agents[/dim]",
        "  [bold]initrunner examples copy <name>[/bold]  [dim]# 2. copy one locally[/dim]",
        "  [bold]initrunner run <name>/role.yaml[/bold]  [dim]# 3. run it[/dim]",
        "",
        "  [dim]Or run the role setup just created:[/dim]",
        f'  [bold]initrunner run {_role}[/bold] [dim]-p "Ask me anything"[/dim]',
        f"  [bold]initrunner run {_role} -i[/bold]  [dim]# interactive REPL[/dim]",
        "",
        "  [dim]Interfaces:[/dim]",
        "  [bold]initrunner tui[/bold]                   [dim]# terminal dashboard[/dim]",
        "  [bold]initrunner ui[/bold]                    [dim]# web dashboard[/dim]",
    ]

    console.print(
        Panel(
            "\n".join(_next),
            title="Next steps",
            border_style="cyan",
        )
    )
