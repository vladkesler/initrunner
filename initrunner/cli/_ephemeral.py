"""Ephemeral agent dispatch: zero-config REPL, one-shot, and bot modes."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from initrunner.agent.prompt import UserPrompt
from initrunner.cli._helpers import console, print_error
from initrunner.services.providers import (
    EPHEMERAL_TOOL_DEFAULTS,
    TOOL_PROFILES,
    TOOL_REQUIRED_ENVS,
)

# ---------------------------------------------------------------------------
# Tool helpers
# ---------------------------------------------------------------------------


def resolve_extra_tools(extra_types: list[str]) -> list[dict]:
    """Validate extra tool names and return full config dicts.

    Exits with code 1 if a type is unknown or required env vars are missing.
    """
    from initrunner.agent.tools._registry import get_tool_types

    registry_types = set(get_tool_types())
    result: list[dict] = []

    for name in extra_types:
        if name not in EPHEMERAL_TOOL_DEFAULTS:
            if name in registry_types:
                console.print(
                    f"[red]Error:[/red] Tool '{name}' exists in the registry but "
                    f"is not supported as an ephemeral extra tool.\n"
                    f"  Supported: {', '.join(sorted(EPHEMERAL_TOOL_DEFAULTS))}"
                )
                console.print(
                    "[dim]Hint:[/dim] This tool requires a role YAML."
                    " Create one with [bold]initrunner new[/bold]."
                )
            else:
                console.print(
                    f"[red]Error:[/red] Unknown tool type '{name}'.\n"
                    f"  Supported: {', '.join(sorted(EPHEMERAL_TOOL_DEFAULTS))}"
                )
                console.print(
                    "[dim]Hint:[/dim] Run [bold]initrunner run --list-tools[/bold]"
                    " to see all options."
                )
            raise typer.Exit(1)

        required = TOOL_REQUIRED_ENVS.get(name, [])
        for env_var in required:
            if not os.environ.get(env_var):
                console.print(
                    f"[red]Error:[/red] Tool '{name}' requires {env_var}.\n"
                    f"  Export it or add it to your .env file:\n"
                    f"  export {env_var}=your-value"
                )
                raise typer.Exit(1)

        result.append(EPHEMERAL_TOOL_DEFAULTS[name])

    return result


def check_profile_envs(selected_types: set[str] | None = None) -> set[str]:
    """Check required env vars for *selected* tools only.

    Returns tool names that should be skipped due to missing env vars.
    Prints a warning for each skipped tool. When *selected_types* is
    ``None``, inspects the full ephemeral catalog (legacy). Pass the
    attached types so a missing Slack webhook does not print under
    ``minimal`` / ``none``.
    """
    from initrunner.services.providers import check_tool_envs

    missing_map = check_tool_envs(selected_types)
    for tool_name, missing in missing_map.items():
        console.print(f"[dim]Skipping tool '{tool_name}' -- missing {', '.join(missing)}[/dim]")
    return set(missing_map)


def merge_tools(profile_tools: list[dict], extras: list[dict]) -> list[dict]:
    """Combine profile and extra tools, deduplicating by type (first wins)."""
    seen: set[str] = set()
    merged: list[dict] = []
    for tool in profile_tools + extras:
        t = tool["type"]
        if t not in seen:
            seen.add(t)
            merged.append(tool)
    return merged


def print_list_tools() -> None:
    """Print supported extra tool types and their env requirements."""
    console.print("[bold]Available extra tools for --tools:[/bold]\n")
    for name in sorted(EPHEMERAL_TOOL_DEFAULTS):
        required = TOOL_REQUIRED_ENVS.get(name)
        if required:
            env_str = ", ".join(required)
            console.print(f"  {name:<14} (requires {env_str})")
        else:
            console.print(f"  {name}")
    console.print()
    console.print("[dim]Usage: initrunner run --tools slack --tools git[/dim]")


def print_explain_profiles() -> None:
    """Print each tool profile with its included tools."""
    console.print("[bold]Tool profiles for --tool-profile:[/bold]\n")
    for name, tools in TOOL_PROFILES.items():
        if not tools:
            console.print(f"  [cyan]{name}[/cyan]: (no tools)")
        else:
            tool_names = ", ".join(t["type"] for t in tools)
            console.print(f"  [cyan]{name}[/cyan]: {tool_names}")
    console.print()
    console.print("[dim]Usage: initrunner run --tool-profile all[/dim]")


# ---------------------------------------------------------------------------
# Bot helpers
# ---------------------------------------------------------------------------


def get_bot_prompt(platform: str) -> str:
    """Build platform-specific system prompt."""
    from initrunner.services.providers import CHAT_PERSONALITY

    suffix = {
        "telegram": (
            "Never ask clarifying questions -- answer directly with your best take. "
            "Keep responses concise and well-formatted for mobile reading."
        ),
        "discord": (
            "Never ask clarifying questions -- answer directly with your best take. "
            "Keep responses concise. Use Discord markdown formatting where appropriate."
        ),
    }
    return CHAT_PERSONALITY + "\n" + suffix[platform]


def verify_bot_sdk(platform: str) -> None:
    """Verify the platform SDK is importable, with install hint on failure."""
    from initrunner._compat import MissingExtraError, require_extra

    try:
        require_extra(platform)
    except MissingExtraError as e:
        print_error(e)
        raise typer.Exit(1) from None


def build_agent_or_exit(role):
    """Build the agent, reporting a missing extra the way the role-file path does.

    ``build_agent`` wraps ``MissingExtraError`` in ``RoleLoadError`` so the
    install hint surfaces at load rather than mid-run. ``load_and_build_or_exit``
    catches it for role files; this is the ephemeral twin. Nothing an ephemeral
    role can carry needs the vector extra except memory and ingest, and memory
    is on by default, so when ingest is not in play the hint names the flag
    that turns memory off.
    """
    from initrunner._compat import MissingExtraError
    from initrunner.agent.loader import RoleLoadError, build_agent

    try:
        return build_agent(role)
    except RoleLoadError as e:
        print_error(e)
        if isinstance(e.__cause__, MissingExtraError) and role.spec.ingest is None:
            console.print(
                "[dim]Hint:[/dim] Persistent memory is what needs it."
                " Add [bold]--no-memory[/bold] to run without it."
            )
        raise typer.Exit(1) from None


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def run_ephemeral_ingest(role, provider: str) -> None:
    """Run ingestion for ephemeral mode. Auto-forces on model change."""
    from initrunner.ingestion.pipeline import run_ingest

    if role.spec.ingest is None:
        raise RuntimeError("Role has no ingest configuration")
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
            console.print("[dim]Embedding model changed -- re-ingesting...[/dim]")
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


# ---------------------------------------------------------------------------
# REPL dispatch
# ---------------------------------------------------------------------------


def dispatch_ephemeral_repl(
    *,
    provider: str | None,
    model: str | None,
    prompt: UserPrompt | None,
    interactive: bool,
    attached_tools: list[dict],
    audit_db: Path | None,
    no_audit: bool,
    with_memory: bool = True,
    resume: bool = False,
    ingest_paths: list[str] | None = None,
    name: str = "ephemeral",
    personality: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
) -> None:
    """Build ephemeral role and run as REPL or one-shot."""
    from initrunner.cli._helpers import ephemeral_context
    from initrunner.runner import run_interactive, run_single
    from initrunner.services.providers import build_quick_chat_role_sync

    try:
        role, prov, mod = build_quick_chat_role_sync(
            provider=provider,
            model=model,
            tool_defs=attached_tools,
            with_memory=with_memory,
            personality=personality,
            name=name,
            base_url=base_url,
            api_key_env=api_key_env,
        )
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    # Layer on ingest config — keep the same attached tool list (empty stays empty).
    if ingest_paths:
        from initrunner.agent.schema.ingestion import IngestConfig
        from initrunner.services.providers import build_ephemeral_role

        ingest_config = IngestConfig(sources=ingest_paths)
        build_kwargs: dict = {
            "name": name,
            "tools": attached_tools,
            "memory": role.spec.memory,
            "ingest": ingest_config,
            "tool_search": role.spec.tool_search,
            "base_url": base_url,
            "api_key_env": api_key_env,
        }
        if personality:
            build_kwargs["system_prompt"] = (
                personality + "\n"
                "Never ask clarifying questions -- answer directly with your best take. "
                "Keep responses concise."
            )
        role = build_ephemeral_role(prov, mod, **build_kwargs)
    else:
        ingest_config = None

    agent = build_agent_or_exit(role)

    console.print(f"[dim]Using {prov}:{mod}[/dim]")
    one_shot = bool(prompt) and not interactive
    if not one_shot:
        console.print(
            "[dim]Tip: for custom tools and guardrails, create a role with 'initrunner new'[/dim]"
        )

    # Run ingestion if configured
    if ingest_config is not None:
        run_ephemeral_ingest(role, prov)

    with ephemeral_context(
        role, agent, audit_db=audit_db, no_audit=no_audit, with_memory=with_memory
    ) as (
        role,
        agent,
        audit_logger,
        memory_store,
    ):
        # -p without -i: one-shot (exit after response)
        if prompt and not interactive:
            run_single(agent, role, prompt, audit_logger=audit_logger)
            return

        # -p with -i: prompt then REPL
        message_history = None
        if prompt:
            _result, message_history = run_single(agent, role, prompt, audit_logger=audit_logger)

        # REPL
        run_interactive(
            agent,
            role,
            audit_logger=audit_logger,
            message_history=message_history,
            memory_store=memory_store,
            resume=resume,
        )


# ---------------------------------------------------------------------------
# Bot dispatch
# ---------------------------------------------------------------------------


def dispatch_ephemeral_bot(
    platform: str,
    *,
    provider: str | None,
    model: str | None,
    attached_tools: list[dict],
    audit_db: Path | None,
    no_audit: bool,
    with_memory: bool = True,
    ingest_paths: list[str] | None = None,
    name: str = "ephemeral",
    personality: str | None = None,
    allowed_users: list[str] | None = None,
    allowed_user_ids: list[str] | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
) -> None:
    """Launch an ephemeral Telegram or Discord bot daemon."""
    from initrunner.services.providers import (
        _BOT_TOKEN_ENVS,
        _load_env,
        build_ephemeral_role,
        resolve_provider_and_model,
    )

    # Verify bot token
    token_env = _BOT_TOKEN_ENVS[platform]
    _load_env()
    if not os.environ.get(token_env):
        console.print(
            f"[red]Error:[/red] {token_env} not set. "
            f"Export it or add it to your .env file:\n"
            f"  export {token_env}=your-bot-token"
        )
        raise typer.Exit(1)

    verify_bot_sdk(platform)

    try:
        prov, mod = resolve_provider_and_model(provider, model)
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

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

    bot_name = name if name != "ephemeral" else f"{platform}-bot"

    from initrunner.services.providers import ephemeral_tool_search

    tool_search = ephemeral_tool_search(attached_tools)

    build_kwargs: dict = {
        "name": bot_name,
        "system_prompt": get_bot_prompt(platform)
        if not personality
        else (
            personality + "\n"
            "Never ask clarifying questions -- answer directly with your best take. "
            "Keep responses concise."
        ),
        "triggers": [trigger_config],
        "tools": attached_tools,
        "autonomy": {},
        "guardrails": {"daemon_daily_token_budget": 200_000},
        "memory": memory_config,
        "ingest": ingest_config,
        "tool_search": tool_search,
        "base_url": base_url,
        "api_key_env": api_key_env,
    }

    role = build_ephemeral_role(prov, mod, **build_kwargs)

    from initrunner.cli._helpers import create_audit_logger
    from initrunner.runner import run_daemon
    from initrunner.stores.factory import managed_memory_store

    agent = build_agent_or_exit(role)
    audit_logger = create_audit_logger(audit_db, no_audit)

    if ingest_config is not None:
        run_ephemeral_ingest(role, prov)

    with managed_memory_store(role, agent) as memory_store:
        try:
            run_daemon(agent, role, audit_logger=audit_logger, memory_store=memory_store)
        finally:
            if audit_logger is not None:
                audit_logger.close()


# ---------------------------------------------------------------------------
# Unified ephemeral dispatch
# ---------------------------------------------------------------------------


def dispatch_ephemeral(
    *,
    provider: str | None = None,
    model: str | None = None,
    prompt: str | None = None,
    interactive: bool = False,
    tool_profile: str | None = None,
    extra_tools: list[str] | None = None,
    memory: bool | None = None,
    resume: bool = False,
    ingest: list[str] | None = None,
    bot: str | None = None,
    attach: list[str] | None = None,
    allowed_users: list[str] | None = None,
    allowed_user_ids: list[str] | None = None,
    audit_db: Path | None = None,
    no_audit: bool = False,
) -> None:
    """Shared setup for ephemeral mode, then delegate to REPL or bot."""
    from initrunner.run_config import load_run_config, resolve_ingest_paths

    run_cfg = load_run_config()

    # Apply config defaults (CLI flags take precedence)
    if tool_profile is None:
        tool_profile = run_cfg.tool_profile
    if memory is None:
        memory = run_cfg.memory
    if provider is None and run_cfg.provider:
        provider = run_cfg.provider
    if model is None and run_cfg.model:
        model = run_cfg.model
    base_url = run_cfg.base_url
    api_key_env_val = run_cfg.api_key_env
    if extra_tools is None and run_cfg.tools:
        extra_tools = run_cfg.tools
    if ingest is None and run_cfg.ingest:
        ingest = resolve_ingest_paths(run_cfg.ingest)

    # Resolve model aliases
    if model is not None:
        from initrunner.model_aliases import resolve_model_alias

        resolved = resolve_model_alias(model)
        if ":" in resolved:
            alias_provider, alias_model = resolved.split(":", 1)
            if provider is None:
                provider = alias_provider
            model = alias_model

    if tool_profile not in TOOL_PROFILES:
        console.print(
            f"[red]Error:[/red] Unknown tool profile '{tool_profile}'. "
            f"Use: {', '.join(TOOL_PROFILES)}"
        )
        raise typer.Exit(1)

    # Attach the selected profile + extras only — never the full catalog.
    profile_tools = list(TOOL_PROFILES.get(tool_profile, []))
    extras = resolve_extra_tools(extra_tools) if extra_tools else []
    attached_tools = merge_tools(profile_tools, extras)

    from initrunner.services.providers import _load_env

    _load_env()
    selected_types = {t["type"] for t in attached_tools}
    skip = check_profile_envs(selected_types)
    if skip:
        attached_tools = [t for t in attached_tools if t["type"] not in skip]

    ephemeral_name = run_cfg.name
    personality = run_cfg.personality

    # Build multimodal prompt if attachments provided
    user_prompt = prompt
    if attach and prompt:
        from initrunner.agent.prompt import build_multimodal_prompt

        try:
            user_prompt = build_multimodal_prompt(prompt, attach)
        except (FileNotFoundError, ValueError) as e:
            console.print(f"[red]Attachment error:[/red] {e}")
            raise typer.Exit(1) from None

    if bot is not None:
        dispatch_ephemeral_bot(
            bot,
            provider=provider,
            model=model,
            attached_tools=attached_tools,
            audit_db=audit_db,
            no_audit=no_audit,
            with_memory=memory if memory is not None else True,
            ingest_paths=ingest,
            name=ephemeral_name,
            personality=personality,
            allowed_users=allowed_users,
            allowed_user_ids=allowed_user_ids,
            base_url=base_url,
            api_key_env=api_key_env_val,
        )
    else:
        dispatch_ephemeral_repl(
            provider=provider,
            model=model,
            prompt=user_prompt,
            interactive=interactive,
            attached_tools=attached_tools,
            audit_db=audit_db,
            no_audit=no_audit,
            with_memory=memory if memory is not None else True,
            resume=resume,
            ingest_paths=ingest,
            name=ephemeral_name,
            personality=personality,
            base_url=base_url,
            api_key_env=api_key_env_val,
        )
