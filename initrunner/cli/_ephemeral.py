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
                    "[dim]Hint:[/dim] This tool requires a role YAML."
                    " Create one with [bold]initrunner new[/bold]."
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


def parse_tools_flag(values: list[str]) -> tuple[str | None, list[str]]:
    """Split ``--tools`` values into (profile, tool types).

    One flag carries what used to be split across ``--tool-profile`` and
    ``--tools``: each value is a profile name (``none``/``minimal``/``all``) or
    a tool type, repeatable and/or comma-separated. Returns ``(None, [])`` when
    nothing was given, so the caller falls back to ``run.yaml``.
    """
    tokens: list[str] = []
    for value in values:
        for raw in value.split(","):
            token = raw.strip()
            if token and token not in tokens:
                tokens.append(token)

    profiles = [t for t in tokens if t in TOOL_PROFILES]
    if len(profiles) > 1:
        console.print(
            f"[red]Error:[/red] --tools names more than one profile"
            f" ({', '.join(profiles)}). Pick one of: {', '.join(TOOL_PROFILES)}"
        )
        raise typer.Exit(1)

    types: list[str] = []
    for token in tokens:
        if token in TOOL_PROFILES:
            continue
        if token not in EPHEMERAL_TOOL_DEFAULTS:
            _print_unknown_tool(token)
            raise typer.Exit(1)
        types.append(token)

    return (profiles[0] if profiles else None), types


def _print_unknown_tool(name: str) -> None:
    """Explain an unusable ``--tools`` value, listing what is usable."""
    from initrunner.agent.tools._registry import get_tool_types

    if name in set(get_tool_types()):
        console.print(
            f"[red]Error:[/red] Tool '{name}' exists in the registry but"
            " is not supported as an ephemeral extra tool."
        )
        console.print(
            "[dim]Hint:[/dim] This tool requires a role YAML."
            " Create one with [bold]initrunner new[/bold]."
        )
    else:
        console.print(f"[red]Error:[/red] Unknown tool '{name}' for --tools.")
    console.print(f"  Profiles: {', '.join(TOOL_PROFILES)}")
    console.print(f"  Tools:    {', '.join(sorted(EPHEMERAL_TOOL_DEFAULTS))}")


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


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


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
        cause = e.__cause__
        if isinstance(cause, MissingExtraError) and cause.extra:
            if role.spec.ingest is None:
                # Print the way out before the prompt, so declining still
                # leaves the user with something to do.
                console.print(
                    "[dim]Hint:[/dim] Persistent memory is what needs it."
                    " Add [bold]--no-memory[/bold] to run without it."
                )
            from initrunner.cli._helpers._extras import offer_install

            offer_install([cause.extra], needed_by="this run")
        print_error(e)
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
# Unified ephemeral dispatch
# ---------------------------------------------------------------------------


def dispatch_ephemeral(
    *,
    model: str | None = None,
    prompt: str | None = None,
    interactive: bool = False,
    tools: list[str] | None = None,
    memory: bool | None = None,
    resume: bool = False,
    ingest: list[str] | None = None,
    attach: list[str] | None = None,
    no_audit: bool = False,
) -> None:
    """Shared setup for ephemeral mode, then run a one-shot or the REPL."""
    from initrunner.run_config import load_run_config, resolve_ingest_paths

    run_cfg = load_run_config()

    # One flag carries both the profile and any extra tool types; whichever the
    # user did not name falls back to run.yaml.
    flag_profile, flag_types = parse_tools_flag(tools) if tools else (None, [])
    tool_profile = flag_profile or run_cfg.tool_profile
    extra_tools = flag_types or run_cfg.tools

    if memory is None:
        memory = run_cfg.memory
    provider = run_cfg.provider or None
    if model is None and run_cfg.model:
        model = run_cfg.model
    base_url = run_cfg.base_url
    api_key_env_val = run_cfg.api_key_env
    if ingest is None and run_cfg.ingest:
        ingest = resolve_ingest_paths(run_cfg.ingest)

    # An explicit provider:model (or an alias resolving to one) wins over
    # run.yaml's provider; a bare model name keeps the configured or detected
    # provider.
    if model is not None:
        from initrunner.model_aliases import resolve_model_alias

        resolved = resolve_model_alias(model)
        if ":" in resolved:
            provider, model = resolved.split(":", 1)
        else:
            model = resolved

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

    dispatch_ephemeral_repl(
        provider=provider,
        model=model,
        prompt=user_prompt,
        interactive=interactive,
        attached_tools=attached_tools,
        audit_db=None,
        no_audit=no_audit,
        with_memory=memory if memory is not None else True,
        resume=resume,
        ingest_paths=ingest,
        name=ephemeral_name,
        personality=personality,
        base_url=base_url,
        api_key_env=api_key_env_val,
    )
