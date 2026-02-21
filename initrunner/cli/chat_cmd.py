"""Chat command: zero-config REPL and one-command bot launcher."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console

# Extra tools that can be added via --tools with safe ephemeral defaults.
_EPHEMERAL_EXTRA_TOOL_DEFAULTS: dict[str, dict] = {
    "datetime": {"type": "datetime"},
    "web_reader": {"type": "web_reader"},
    "search": {"type": "search"},
    "python": {"type": "python"},
    "filesystem": {"type": "filesystem", "root_path": ".", "read_only": True},
    "slack": {"type": "slack", "webhook_url": "${SLACK_WEBHOOK_URL}"},
    "git": {"type": "git", "repo_path": ".", "read_only": True},
    "shell": {"type": "shell"},
}

# Environment variables required for certain extra tools.
_TOOL_REQUIRED_ENVS: dict[str, list[str]] = {
    "slack": ["SLACK_WEBHOOK_URL"],
}

# Tool profile definitions
_TOOL_PROFILES: dict[str, list[dict]] = {
    "none": [],
    "minimal": [
        {"type": "datetime"},
        {"type": "web_reader"},
    ],
    "all": list(_EPHEMERAL_EXTRA_TOOL_DEFAULTS.values()),
}


def _resolve_extra_tools(extra_types: list[str]) -> list[dict]:
    """Validate extra tool names and return full config dicts.

    Exits with code 1 if a type is unknown or required env vars are missing.
    """
    from initrunner.agent.tools._registry import get_tool_types

    registry_types = set(get_tool_types())
    result: list[dict] = []

    for name in extra_types:
        if name not in _EPHEMERAL_EXTRA_TOOL_DEFAULTS:
            if name in registry_types:
                console.print(
                    f"[red]Error:[/red] Tool '{name}' exists in the registry but "
                    f"is not supported as a chat extra tool.\n"
                    f"  Supported: {', '.join(sorted(_EPHEMERAL_EXTRA_TOOL_DEFAULTS))}"
                )
            else:
                console.print(
                    f"[red]Error:[/red] Unknown tool type '{name}'.\n"
                    f"  Supported: {', '.join(sorted(_EPHEMERAL_EXTRA_TOOL_DEFAULTS))}"
                )
            raise typer.Exit(1)

        # Check required env vars
        required = _TOOL_REQUIRED_ENVS.get(name, [])
        for env_var in required:
            if not os.environ.get(env_var):
                console.print(
                    f"[red]Error:[/red] Tool '{name}' requires {env_var}.\n"
                    f"  Export it or add it to your .env file:\n"
                    f"  export {env_var}=your-value"
                )
                raise typer.Exit(1)

        result.append(_EPHEMERAL_EXTRA_TOOL_DEFAULTS[name])

    return result


def _check_profile_envs() -> None:
    """Check required env vars for all tools in the ``all`` profile.

    Exits with code 1 and an actionable message on the first missing var.
    """
    for tool_name, env_vars in _TOOL_REQUIRED_ENVS.items():
        for env_var in env_vars:
            if not os.environ.get(env_var):
                console.print(
                    f"[red]Error:[/red] Tool '{tool_name}' requires {env_var}.\n"
                    f"  Export it or add it to your .env file:\n"
                    f"  export {env_var}=your-value"
                )
                raise typer.Exit(1)


def _merge_tools(profile_tools: list[dict], extras: list[dict]) -> list[dict]:
    """Combine profile and extra tools, deduplicating by type (first wins)."""
    seen: set[str] = set()
    merged: list[dict] = []
    for tool in profile_tools + extras:
        t = tool["type"]
        if t not in seen:
            seen.add(t)
            merged.append(tool)
    return merged


def _print_list_tools() -> None:
    """Print supported extra tool types and their env requirements."""
    console.print("[bold]Available extra tools for --tools:[/bold]\n")
    for name in sorted(_EPHEMERAL_EXTRA_TOOL_DEFAULTS):
        required = _TOOL_REQUIRED_ENVS.get(name)
        if required:
            env_str = ", ".join(required)
            console.print(f"  {name:<14} (requires {env_str})")
        else:
            console.print(f"  {name}")
    console.print()
    console.print("[dim]Usage: initrunner chat --tools slack --tools git[/dim]")


def chat(
    role_file: Annotated[
        Path | None,
        typer.Argument(help="Path to role.yaml (omit for auto-detect mode)"),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Model provider (overrides auto-detection)"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model name (overrides auto-detection)"),
    ] = None,
    prompt: Annotated[
        str | None,
        typer.Option("-p", "--prompt", help="Send prompt then enter REPL"),
    ] = None,
    telegram: Annotated[
        bool,
        typer.Option("--telegram", help="Launch as Telegram bot"),
    ] = False,
    discord: Annotated[
        bool,
        typer.Option("--discord", help="Launch as Discord bot"),
    ] = False,
    tool_profile: Annotated[
        str,
        typer.Option("--tool-profile", help="Tool profile: minimal, all, none"),
    ] = "minimal",
    audit_db: Annotated[
        Path | None,
        typer.Option(help="Path to audit database"),
    ] = None,
    extra_tools: Annotated[
        list[str] | None,
        typer.Option("--tools", help="Extra tool types to enable (repeatable)"),
    ] = None,
    list_tools: Annotated[
        bool,
        typer.Option("--list-tools", help="List available extra tool types and exit"),
    ] = False,
    no_audit: Annotated[
        bool,
        typer.Option(help="Disable audit logging"),
    ] = False,
) -> None:
    """Start an ephemeral chat REPL or launch a bot.

    Without arguments, auto-detects your API provider and starts a REPL.
    With a role file, loads it and starts interactive mode.
    With --telegram or --discord, launches a bot daemon.
    """
    if list_tools:
        _print_list_tools()
        raise typer.Exit(0)

    if telegram and discord:
        console.print("[red]Error:[/red] --telegram and --discord are mutually exclusive.")
        raise typer.Exit(1)

    if tool_profile not in _TOOL_PROFILES:
        console.print(
            f"[red]Error:[/red] Unknown tool profile '{tool_profile}'. "
            f"Use: {', '.join(_TOOL_PROFILES)}"
        )
        raise typer.Exit(1)

    if tool_profile == "all":
        from initrunner.services.providers import _load_env

        _load_env()
        _check_profile_envs()

    # Resolve extra tools (validates names and env vars, exits on error)
    extras = _resolve_extra_tools(extra_tools) if extra_tools else []

    bot_mode = "telegram" if telegram else "discord" if discord else None

    if role_file is not None:
        if extras:
            console.print("[dim]Info:[/dim] --tools ignored because role file defines tools.")
        _chat_with_role_file(role_file, prompt=prompt, audit_db=audit_db, no_audit=no_audit)
    elif bot_mode is not None:
        _chat_bot_mode(
            bot_mode,
            provider=provider,
            model=model,
            tool_profile=tool_profile,
            extra_tools=extras,
            audit_db=audit_db,
            no_audit=no_audit,
        )
    else:
        _chat_auto_detect(
            provider=provider,
            model=model,
            prompt=prompt,
            tool_profile=tool_profile,
            extra_tools=extras,
            audit_db=audit_db,
            no_audit=no_audit,
        )


def _chat_with_role_file(
    role_file: Path,
    *,
    prompt: str | None,
    audit_db: Path | None,
    no_audit: bool,
) -> None:
    """Mode A: chat with an existing role.yaml file."""
    from initrunner.cli._helpers import command_context
    from initrunner.runner import run_interactive, run_single

    with command_context(
        role_file,
        audit_db=audit_db,
        no_audit=no_audit,
        with_memory=True,
    ) as (role, agent, audit_logger, memory_store, _sink_dispatcher):
        message_history = None
        if prompt:
            _result, message_history = run_single(agent, role, prompt, audit_logger=audit_logger)

        run_interactive(
            agent,
            role,
            audit_logger=audit_logger,
            message_history=message_history,
            memory_store=memory_store,
        )


def _chat_auto_detect(
    *,
    provider: str | None,
    model: str | None,
    prompt: str | None,
    tool_profile: str,
    extra_tools: list[dict],
    audit_db: Path | None,
    no_audit: bool,
) -> None:
    """Mode B: auto-detect provider, build ephemeral role, start REPL."""
    from initrunner.agent.loader import build_agent
    from initrunner.cli._helpers import ephemeral_context
    from initrunner.runner import run_interactive, run_single
    from initrunner.services.providers import detect_provider_and_model

    detected = detect_provider_and_model()
    if detected is None and provider is None:
        console.print(
            "[red]Error:[/red] No API key found. Run [bold]initrunner setup[/bold] "
            "or set an API key environment variable."
        )
        raise typer.Exit(1)

    prov = provider or detected.provider  # type: ignore[union-attr]
    mod = model or detected.model  # type: ignore[union-attr]

    if provider and not model and detected:
        # Provider overridden but no model specified — use default for that provider
        from initrunner.templates import _default_model_name

        mod = _default_model_name(provider)
    elif provider and not model and not detected:
        from initrunner.templates import _default_model_name

        mod = _default_model_name(provider)

    from initrunner.services.providers import build_ephemeral_role

    profile_tools = _TOOL_PROFILES.get(tool_profile, [])
    tools = _merge_tools(profile_tools, extra_tools)
    role = build_ephemeral_role(prov, mod, tools=tools if tools else None)
    agent = build_agent(role)

    console.print(f"[dim]Using {prov}:{mod}[/dim]")

    with ephemeral_context(role, agent, audit_db=audit_db, no_audit=no_audit) as (
        role,
        agent,
        audit_logger,
        memory_store,
    ):
        message_history = None
        if prompt:
            _result, message_history = run_single(agent, role, prompt, audit_logger=audit_logger)

        run_interactive(
            agent,
            role,
            audit_logger=audit_logger,
            message_history=message_history,
            memory_store=memory_store,
        )


def _get_bot_prompt(platform: str) -> str:
    """Build platform-specific system prompt (lazy import)."""
    from initrunner.services.providers import CHAT_PERSONALITY

    suffix = {
        "telegram": (
            "Never ask clarifying questions — answer directly with your best take. "
            "Keep responses concise and well-formatted for mobile reading."
        ),
        "discord": (
            "Never ask clarifying questions — answer directly with your best take. "
            "Keep responses concise. Use Discord markdown formatting where appropriate."
        ),
    }
    return CHAT_PERSONALITY + "\n" + suffix[platform]


def _chat_bot_mode(
    platform: str,
    *,
    provider: str | None,
    model: str | None,
    tool_profile: str,
    extra_tools: list[dict],
    audit_db: Path | None,
    no_audit: bool,
) -> None:
    """Mode C: launch a Telegram or Discord bot daemon."""
    from initrunner.services.providers import (
        _BOT_TOKEN_ENVS,
        build_ephemeral_role,
        detect_provider_and_model,
    )

    # Verify bot token
    token_env = _BOT_TOKEN_ENVS[platform]
    from initrunner.services.providers import _load_env

    _load_env()
    if not os.environ.get(token_env):
        console.print(
            f"[red]Error:[/red] {token_env} not set. "
            f"Export it or add it to your .env file:\n"
            f"  export {token_env}=your-bot-token"
        )
        raise typer.Exit(1)

    # Verify SDK is installed
    _verify_bot_sdk(platform)

    # Detect provider
    detected = detect_provider_and_model()
    if detected is None and provider is None:
        console.print(
            "[red]Error:[/red] No API key found. Run [bold]initrunner setup[/bold] "
            "or set an API key environment variable."
        )
        raise typer.Exit(1)

    prov = provider or detected.provider  # type: ignore[union-attr]
    mod = model or detected.model  # type: ignore[union-attr]

    if provider and not model:
        from initrunner.templates import _default_model_name

        mod = _default_model_name(provider)

    # Build trigger config
    trigger: dict = {"type": platform, "autonomous": True}
    if platform == "telegram":
        trigger["token_env"] = "TELEGRAM_BOT_TOKEN"
    else:
        trigger["token_env"] = "DISCORD_BOT_TOKEN"

    from initrunner.agent.schema.triggers import (
        DiscordTriggerConfig,
        TelegramTriggerConfig,
    )

    trigger_config = (
        TelegramTriggerConfig(**trigger)
        if platform == "telegram"
        else DiscordTriggerConfig(**trigger)
    )

    profile_tools = _TOOL_PROFILES.get(tool_profile, [])
    tools = _merge_tools(profile_tools, extra_tools)
    role = build_ephemeral_role(
        prov,
        mod,
        name=f"{platform}-bot",
        system_prompt=_get_bot_prompt(platform),
        triggers=[trigger_config],
        tools=tools if tools else None,
        autonomy={},  # Default AutonomyConfig values
        guardrails={"daemon_daily_token_budget": 200_000},
    )

    from initrunner.agent.loader import build_agent
    from initrunner.cli._helpers import create_audit_logger
    from initrunner.runner import run_daemon

    agent = build_agent(role)
    audit_logger = create_audit_logger(audit_db, no_audit)

    try:
        run_daemon(agent, role, audit_logger=audit_logger)
    finally:
        if audit_logger is not None:
            audit_logger.close()


def _verify_bot_sdk(platform: str) -> None:
    """Verify the platform SDK is importable, with install hint on failure."""
    if platform == "telegram":
        try:
            import telegram  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            console.print(
                "[red]Error:[/red] python-telegram-bot is not installed.\n"
                "  Install it: [bold]pip install initrunner[telegram][/bold]"
            )
            raise typer.Exit(1) from None
    elif platform == "discord":
        try:
            import discord  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            console.print(
                "[red]Error:[/red] discord.py is not installed.\n"
                "  Install it: [bold]pip install initrunner[discord][/bold]"
            )
            raise typer.Exit(1) from None
