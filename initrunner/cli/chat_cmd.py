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


def _check_profile_envs() -> set[str]:
    """Check required env vars for all tools in the ``all`` profile.

    Returns tool names that should be skipped due to missing env vars.
    Prints a warning for each skipped tool.
    """
    skip: set[str] = set()
    for tool_name, env_vars in _TOOL_REQUIRED_ENVS.items():
        missing = [v for v in env_vars if not os.environ.get(v)]
        if missing:
            env_list = ", ".join(missing)
            console.print(f"[dim]Skipping tool '{tool_name}' — missing {env_list}[/dim]")
            skip.add(tool_name)
    return skip


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
        str | None,
        typer.Option("--tool-profile", help="Tool profile: minimal, all, none"),
    ] = None,
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
    memory: Annotated[
        bool | None,
        typer.Option("--memory/--no-memory", help="Enable/disable persistent memory"),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume previous session"),
    ] = False,
    ingest: Annotated[
        list[str] | None,
        typer.Option("--ingest", help="Paths/globs to ingest for RAG (repeatable)"),
    ] = None,
    allowed_users: Annotated[
        list[str] | None,
        typer.Option("--allowed-users", help="Restrict bot to these usernames (repeatable)"),
    ] = None,
    allowed_user_ids: Annotated[
        list[str] | None,
        typer.Option("--allowed-user-ids", help="Restrict bot to these user IDs (repeatable)"),
    ] = None,
) -> None:
    """Start an ephemeral chat REPL or launch a bot.

    Without arguments, auto-detects your API provider and starts a REPL
    with persistent memory enabled by default.
    With a role file, loads it and starts interactive mode.
    With --telegram or --discord, launches a bot daemon.
    """
    if list_tools:
        _print_list_tools()
        raise typer.Exit(0)

    if telegram and discord:
        console.print("[red]Error:[/red] --telegram and --discord are mutually exclusive.")
        raise typer.Exit(1)

    if (allowed_users or allowed_user_ids) and not (telegram or discord):
        console.print(
            "[red]Error:[/red] --allowed-users/--allowed-user-ids requires --telegram or --discord."
        )
        raise typer.Exit(1)

    # Load chat.yaml config (only applied when no role_file)
    from initrunner.cli.chat_config import load_chat_config

    chat_cfg = load_chat_config()

    # Apply chat.yaml defaults for ephemeral modes (no role_file)
    if role_file is None:
        if tool_profile is None:
            tool_profile = chat_cfg.tool_profile
        if memory is None:
            memory = chat_cfg.memory
        if provider is None and chat_cfg.provider:
            provider = chat_cfg.provider
        if model is None and chat_cfg.model:
            model = chat_cfg.model
        if extra_tools is None and chat_cfg.tools:
            extra_tools = chat_cfg.tools
        if ingest is None and chat_cfg.ingest:
            from initrunner.cli.chat_config import resolve_ingest_paths

            ingest = resolve_ingest_paths(chat_cfg.ingest)
    else:
        # With role file: chat.yaml not applied
        if tool_profile is None:
            tool_profile = "minimal"
        if memory is None:
            memory = True

    if tool_profile not in _TOOL_PROFILES:
        console.print(
            f"[red]Error:[/red] Unknown tool profile '{tool_profile}'. "
            f"Use: {', '.join(_TOOL_PROFILES)}"
        )
        raise typer.Exit(1)

    # Compute profile tools early so we can filter for missing env vars.
    profile_tools = list(_TOOL_PROFILES.get(tool_profile, []))

    # Always load env and check for missing tool env vars so tool search
    # can register every available tool (minus those with unset credentials).
    from initrunner.services.providers import _load_env

    _load_env()
    skip = _check_profile_envs()
    if skip and tool_profile == "all":
        profile_tools = [t for t in profile_tools if t["type"] not in skip]

    # Resolve extra tools (validates names and env vars, exits on error)
    extras = _resolve_extra_tools(extra_tools) if extra_tools else []

    # Build the full set of ephemeral tools (skipping those with missing env)
    # and determine which ones the agent sees immediately (always_available).
    all_ephemeral_tools = [
        t for t in _EPHEMERAL_EXTRA_TOOL_DEFAULTS.values() if t["type"] not in skip
    ]
    from initrunner.agent.tools.registry import resolve_func_names

    always_available = resolve_func_names(_merge_tools(profile_tools, extras))

    bot_mode = "telegram" if telegram else "discord" if discord else None

    # Resolve ephemeral name from chat.yaml (only for non-role-file modes)
    ephemeral_name = chat_cfg.name if role_file is None else "ephemeral-chat"
    # Resolve personality from chat.yaml
    personality = chat_cfg.personality if role_file is None else None

    if role_file is not None:
        if extras:
            console.print("[dim]Info:[/dim] --tools ignored because role file defines tools.")
        _chat_with_role_file(
            role_file, prompt=prompt, audit_db=audit_db, no_audit=no_audit, resume=resume
        )
    elif bot_mode is not None:
        _chat_bot_mode(
            bot_mode,
            provider=provider,
            model=model,
            profile_tools=profile_tools,
            extra_tools=extras,
            all_tools=all_ephemeral_tools,
            always_available=always_available,
            audit_db=audit_db,
            no_audit=no_audit,
            with_memory=memory if memory is not None else True,
            ingest_paths=ingest,
            name=ephemeral_name,
            personality=personality,
            allowed_users=allowed_users,
            allowed_user_ids=allowed_user_ids,
        )
    else:
        _chat_auto_detect(
            provider=provider,
            model=model,
            prompt=prompt,
            profile_tools=profile_tools,
            extra_tools=extras,
            all_tools=all_ephemeral_tools,
            always_available=always_available,
            audit_db=audit_db,
            no_audit=no_audit,
            with_memory=memory if memory is not None else True,
            resume=resume,
            ingest_paths=ingest,
            name=ephemeral_name,
            personality=personality,
        )


def _chat_with_role_file(
    role_file: Path,
    *,
    prompt: str | None,
    audit_db: Path | None,
    no_audit: bool,
    resume: bool = False,
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
            resume=resume,
        )


def _chat_auto_detect(
    *,
    provider: str | None,
    model: str | None,
    prompt: str | None,
    profile_tools: list[dict],
    extra_tools: list[dict],
    all_tools: list[dict],
    always_available: list[str],
    audit_db: Path | None,
    no_audit: bool,
    with_memory: bool = True,
    resume: bool = False,
    ingest_paths: list[str] | None = None,
    name: str = "ephemeral-chat",
    personality: str | None = None,
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

    # Build memory config
    memory_config = None
    if with_memory:
        from initrunner.agent.schema.memory import MemoryConfig

        memory_config = MemoryConfig()

    # Build ingest config
    ingest_config = None
    if ingest_paths:
        from initrunner.agent.schema.ingestion import IngestConfig

        ingest_config = IngestConfig(sources=ingest_paths)

    from initrunner.agent.schema.role import ToolSearchConfig

    tool_search = ToolSearchConfig(enabled=True, always_available=always_available)

    build_kwargs: dict = {
        "name": name,
        "tools": all_tools if all_tools else None,
        "memory": memory_config,
        "ingest": ingest_config,
        "tool_search": tool_search,
    }
    if personality:
        build_kwargs["system_prompt"] = (
            personality + "\n"
            "Never ask clarifying questions — answer directly with your best take. "
            "Keep responses concise."
        )

    role = build_ephemeral_role(prov, mod, **build_kwargs)
    agent = build_agent(role)

    console.print(f"[dim]Using {prov}:{mod}[/dim]")

    # Run ingestion if configured
    if ingest_config is not None:
        _run_ephemeral_ingest(role, prov)

    with ephemeral_context(
        role, agent, audit_db=audit_db, no_audit=no_audit, with_memory=with_memory
    ) as (
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
            resume=resume,
        )


def _run_ephemeral_ingest(role, provider: str) -> None:
    """Run ingestion for ephemeral chat mode. Auto-forces on model change."""
    from initrunner.ingestion.pipeline import run_ingest

    assert role.spec.ingest is not None
    resource_limits = role.spec.security.resources

    try:
        with console.status("[dim]Ingesting documents...[/dim]"):
            stats = run_ingest(
                role.spec.ingest,
                role.metadata.name,
                provider=provider,
                base_dir=Path.cwd(),
                max_file_size_mb=resource_limits.max_file_size_mb,
                max_total_ingest_mb=resource_limits.max_total_ingest_mb,
            )
    except Exception as exc:
        from initrunner.stores.base import EmbeddingModelChangedError

        if isinstance(exc, EmbeddingModelChangedError):
            console.print("[dim]Embedding model changed — re-ingesting...[/dim]")
            with console.status("[dim]Re-ingesting documents...[/dim]"):
                stats = run_ingest(
                    role.spec.ingest,
                    role.metadata.name,
                    provider=provider,
                    base_dir=Path.cwd(),
                    force=True,
                    max_file_size_mb=resource_limits.max_file_size_mb,
                    max_total_ingest_mb=resource_limits.max_total_ingest_mb,
                )
        else:
            raise

    total = stats.new + stats.updated + stats.skipped + stats.errored
    if total > 0:
        console.print(
            f"[dim]Ingested {total} file(s): "
            f"{stats.new} new, {stats.updated} updated, "
            f"{stats.skipped} unchanged, {stats.errored} error(s)[/dim]"
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
    profile_tools: list[dict],
    extra_tools: list[dict],
    all_tools: list[dict],
    always_available: list[str],
    audit_db: Path | None,
    no_audit: bool,
    with_memory: bool = True,
    ingest_paths: list[str] | None = None,
    name: str = "ephemeral-chat",
    personality: str | None = None,
    allowed_users: list[str] | None = None,
    allowed_user_ids: list[str] | None = None,
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
        if allowed_users:
            trigger["allowed_users"] = allowed_users
        if allowed_user_ids:
            trigger["allowed_user_ids"] = [int(uid) for uid in allowed_user_ids]
    else:
        trigger["token_env"] = "DISCORD_BOT_TOKEN"
        if allowed_user_ids:
            trigger["allowed_user_ids"] = allowed_user_ids

    from initrunner.agent.schema.triggers import (
        DiscordTriggerConfig,
        TelegramTriggerConfig,
    )

    trigger_config = (
        TelegramTriggerConfig(**trigger)
        if platform == "telegram"
        else DiscordTriggerConfig(**trigger)
    )

    # Build memory config
    memory_config = None
    if with_memory:
        from initrunner.agent.schema.memory import MemoryConfig

        memory_config = MemoryConfig()

    # Build ingest config
    ingest_config = None
    if ingest_paths:
        from initrunner.agent.schema.ingestion import IngestConfig

        ingest_config = IngestConfig(sources=ingest_paths)

    bot_name = name if name != "ephemeral-chat" else f"{platform}-bot"

    from initrunner.agent.schema.role import ToolSearchConfig

    tool_search = ToolSearchConfig(enabled=True, always_available=always_available)

    build_kwargs: dict = {
        "name": bot_name,
        "system_prompt": _get_bot_prompt(platform)
        if not personality
        else (
            personality + "\n"
            "Never ask clarifying questions — answer directly with your best take. "
            "Keep responses concise."
        ),
        "triggers": [trigger_config],
        "tools": all_tools if all_tools else None,
        "autonomy": {},
        "guardrails": {"daemon_daily_token_budget": 200_000},
        "memory": memory_config,
        "ingest": ingest_config,
        "tool_search": tool_search,
    }

    role = build_ephemeral_role(prov, mod, **build_kwargs)

    from initrunner.agent.loader import build_agent
    from initrunner.cli._helpers import create_audit_logger, resolve_memory_path
    from initrunner.runner import run_daemon

    agent = build_agent(role)
    audit_logger = create_audit_logger(audit_db, no_audit)

    # Run ingestion if configured
    if ingest_config is not None:
        _run_ephemeral_ingest(role, prov)

    # Set up memory store for daemon
    memory_store = None
    mem_path = None
    if with_memory and role.spec.memory is not None:
        from initrunner.stores.factory import (
            create_memory_store,
            register_memory_store,
        )

        mem_path = resolve_memory_path(role)
        memory_store = create_memory_store(role.spec.memory.store_backend, mem_path)
        register_memory_store(mem_path, memory_store)
        agent._memory_store = memory_store  # type: ignore[attr-defined]

    try:
        run_daemon(agent, role, audit_logger=audit_logger, memory_store=memory_store)
    finally:
        if memory_store is not None:
            from initrunner.stores.factory import unregister_memory_store

            assert mem_path is not None
            unregister_memory_store(mem_path)
            memory_store.close()
        if audit_logger is not None:
            audit_logger.close()


def _verify_bot_sdk(platform: str) -> None:
    """Verify the platform SDK is importable, with install hint on failure."""
    if platform == "telegram":
        try:
            import telegram  # type: ignore[unresolved-import]  # noqa: F401
        except ImportError:
            console.print(
                "[red]Error:[/red] python-telegram-bot is not installed.\n"
                "  Install it: [bold]pip install initrunner[telegram][/bold]"
            )
            raise typer.Exit(1) from None
    elif platform == "discord":
        try:
            import discord  # type: ignore[unresolved-import]  # noqa: F401
        except ImportError:
            console.print(
                "[red]Error:[/red] discord.py is not installed.\n"
                "  Install it: [bold]pip install initrunner[discord][/bold]"
            )
            raise typer.Exit(1) from None
