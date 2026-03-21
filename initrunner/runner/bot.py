"""Bot runner: start a Telegram or Discord bot backed by a loaded role."""

from __future__ import annotations

import logging
import os
import threading

from pydantic_ai import Agent

from initrunner.agent.executor import RunResult, execute_run
from initrunner.agent.schema.role import RoleDefinition
from initrunner.audit.logger import AuditLogger
from initrunner.runner._conversations import ConversationStore
from initrunner.runner.budget import DaemonTokenTracker
from initrunner.runner.display import console
from initrunner.sinks.dispatcher import SinkDispatcher
from initrunner.stores.base import MemoryStoreBase
from initrunner.triggers.base import TriggerEvent

_logger = logging.getLogger(__name__)

_BOT_TOKEN_ENVS: dict[str, str] = {
    "telegram": "TELEGRAM_BOT_TOKEN",
    "discord": "DISCORD_BOT_TOKEN",
}

_SDK_PACKAGES: dict[str, tuple[str, str]] = {
    "telegram": ("telegram", "python-telegram-bot"),
    "discord": ("discord", "discord.py"),
}


def _verify_bot_sdk(platform: str) -> None:
    """Verify the platform SDK is importable, with install hint on failure."""
    import importlib

    module_name, pip_name = _SDK_PACKAGES[platform]
    try:
        importlib.import_module(module_name)
    except ImportError:
        console.print(
            f"[red]Error:[/red] {pip_name} is not installed.\n"
            f"  Install it: [bold]uv pip install {pip_name}[/bold]"
        )
        import typer

        raise typer.Exit(1) from None


def run_bot(
    agent: Agent,
    role: RoleDefinition,
    platform: str,
    *,
    allowed_users: list[str] | None = None,
    allowed_user_ids: list[str] | None = None,
    audit_logger: AuditLogger | None = None,
    sink_dispatcher: SinkDispatcher | None = None,
    memory_store: MemoryStoreBase | None = None,
) -> None:
    """Run a role-backed bot on the given platform.

    Creates the platform trigger directly, manages conversations and token
    budget, and blocks until a shutdown signal is received.
    """
    import typer

    # Validate SDK
    _verify_bot_sdk(platform)

    # Validate token
    token_env = _BOT_TOKEN_ENVS[platform]
    if not os.environ.get(token_env):
        console.print(
            f"[red]Error:[/red] {token_env} not set.\n"
            f"  Export it or add it to your .env file:\n"
            f"  export {token_env}=your-bot-token"
        )
        raise typer.Exit(1)

    # State
    conversations = ConversationStore()
    guardrails = role.spec.guardrails
    tracker = DaemonTokenTracker(
        lifetime_budget=guardrails.daemon_token_budget,
        daily_budget=guardrails.daemon_daily_token_budget,
    )
    stop = threading.Event()

    def on_trigger(event: TriggerEvent) -> None:
        """Handle each incoming bot message."""
        allowed, reason = tracker.check_before_run()
        if not allowed:
            console.print(f"\n[yellow]Budget exceeded: {reason}[/yellow]")
            return

        console.print(f"\n[dim]Bot ({event.trigger_type}):[/dim] {event.prompt[:80]}")

        conv_key = event.conversation_key
        prior_history = conversations.get(conv_key) if conv_key else None

        result, new_messages = execute_run(
            agent,
            role,
            event.prompt,
            audit_logger=audit_logger,
            message_history=prior_history,
            trigger_type=event.trigger_type,
            trigger_metadata=event.metadata or {},
            principal_id=event.principal_id,
        )

        tracker.record_usage(result.total_tokens)

        # Reply to originating channel
        if event.reply_fn is not None and result.output:
            try:
                event.reply_fn(result.output)
            except Exception:
                _logger.warning("Failed to deliver reply for %s", event.trigger_type, exc_info=True)

        # Display result
        from initrunner.runner.display import _display_result

        _display_result(result)

        # Dispatch to sinks
        if sink_dispatcher is not None:
            sink_dispatcher.dispatch(
                result,
                event.prompt,
                trigger_type=event.trigger_type,
                trigger_metadata=event.metadata,
            )

        # Capture episode
        _capture_episode(memory_store, role, result, event)

        # Store conversation history
        if conv_key and new_messages:
            from initrunner.agent.history import reduce_history
            from initrunner.agent.schema.autonomy import AutonomyConfig

            autonomy_config = role.spec.autonomy or AutonomyConfig()
            conversations.put(conv_key, reduce_history(new_messages, autonomy_config, role))

    # Create trigger with platform-specific config
    if platform == "telegram":
        from initrunner.agent.schema.triggers import TelegramTriggerConfig
        from initrunner.triggers.telegram import TelegramTrigger

        telegram_cfg = TelegramTriggerConfig(
            autonomous=True,
            allowed_users=allowed_users or [],
            allowed_user_ids=[int(uid) for uid in (allowed_user_ids or [])],
        )
        trigger = TelegramTrigger(telegram_cfg, on_trigger)
    else:
        from initrunner.agent.schema.triggers import DiscordTriggerConfig
        from initrunner.triggers.discord import DiscordTrigger

        discord_cfg = DiscordTriggerConfig(
            autonomous=True,
            allowed_user_ids=allowed_user_ids or [],
        )
        trigger = DiscordTrigger(discord_cfg, on_trigger)

    # Display header
    console.print(f"\n[bold]Bot mode[/bold] ({platform})")
    console.print(f"  Role: {role.metadata.name}")
    if guardrails.daemon_daily_token_budget:
        console.print(f"  Daily budget: {guardrails.daemon_daily_token_budget:,} tokens")
    console.print("  Press Ctrl+C to stop.\n")

    # Start trigger and block
    trigger.start()
    try:
        from initrunner._signal import install_shutdown_handler

        def _on_shutdown() -> None:
            console.print("\n[yellow]Shutting down...[/yellow]")

        install_shutdown_handler(stop, on_first_signal=_on_shutdown)

        while not stop.wait(timeout=30):
            pass
    finally:
        trigger.stop()
        console.print("Bot stopped.")


def _capture_episode(
    memory_store: MemoryStoreBase | None,
    role: RoleDefinition,
    result: RunResult,
    event: TriggerEvent,
) -> None:
    """Capture a bot message as an episodic memory."""
    if memory_store is None or role.spec.memory is None:
        return
    from initrunner.agent.memory_capture import capture_episode

    summary = f"Bot ({event.trigger_type}): {result.output[:500]}"
    capture_episode(
        memory_store,
        role,
        summary,
        category="bot_run",
        trigger_type=event.trigger_type,
    )
