"""Discord WebSocket channel adapter -- outbound only, no ports opened."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from collections.abc import Callable

from initrunner._async import run_sync
from initrunner._text import safe_substitute
from initrunner.agent.schema.triggers import DiscordTriggerConfig
from initrunner.triggers.base import ChannelAdapter, TriggerEvent, _chunk_text

_logger = logging.getLogger(__name__)

_DISCORD_MAX_MESSAGE = 2000


def _log_async_error(future: asyncio.Future, target: str) -> None:
    if (exc := future.exception()) is not None:
        _logger.warning("Async send to %s failed: %s", target, exc)


def _check_discord_access(
    *,
    is_dm: bool,
    author_roles: set[str],
    author_id: str,
    channel_id: str,
    allowed_channels: set[str],
    allowed_roles: set[str],
    allowed_user_ids: set[str],
) -> bool:
    """Return True if the message should be processed, False to drop it.

    This is extracted from the on_message handler so it can be unit-tested
    without a real Discord client.
    """
    user_id_passed = bool(allowed_user_ids and author_id in allowed_user_ids)

    # DM handling: roles require guild context, user IDs work everywhere
    if is_dm:
        if allowed_roles and not allowed_user_ids:
            # Only roles configured -- DMs denied (no role context)
            return False
        if allowed_user_ids and not user_id_passed:
            # User IDs configured but sender not listed
            return False
        # If both configured: user_id match allows DM even without role check
        if allowed_roles and allowed_user_ids and not user_id_passed:
            return False
        # No identity filters at all, or user_id matched -- allow
        return True

    # Channel filter -- only applies to guild channels, not DMs
    if allowed_channels and channel_id not in allowed_channels:
        return False

    # Role/user_id filter for guild messages
    if allowed_roles or allowed_user_ids:
        role_passed = bool(allowed_roles and (author_roles & allowed_roles))
        if not role_passed and not user_id_passed:
            return False

    return True


class DiscordAdapter(ChannelAdapter):
    """Bidirectional Discord adapter: WebSocket inbound, REST API outbound."""

    def __init__(self, config: DiscordTriggerConfig) -> None:
        self._config = config
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: object | None = None  # discord.Client, set during start()

    @property
    def platform(self) -> str:
        return "discord"

    def start(self, callback: Callable[[TriggerEvent], None]) -> None:
        import discord  # type: ignore[unresolved-import]

        token = os.environ.get(self._config.token_env)
        if not token:
            _logger.error(
                "Env var %s not set -- Discord adapter not started", self._config.token_env
            )
            return

        allowed_channels = set(self._config.channel_ids)
        allowed_roles = set(self._config.allowed_roles)
        allowed_user_ids = set(self._config.allowed_user_ids)
        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        self._client = client

        @client.event
        async def on_ready() -> None:
            self._ready.set()

        @client.event
        async def on_message(message: discord.Message) -> None:
            if message.author == client.user:
                return

            is_dm = isinstance(message.channel, discord.DMChannel)
            is_mentioned = client.user in message.mentions
            if not is_dm and not is_mentioned:
                return

            author_roles: set[str] = set()
            if isinstance(message.author, discord.Member):
                author_roles = {r.name for r in message.author.roles}

            if not _check_discord_access(
                is_dm=is_dm,
                author_roles=author_roles,
                author_id=str(message.author.id),
                channel_id=str(message.channel.id),
                allowed_channels=allowed_channels,
                allowed_roles=allowed_roles,
                allowed_user_ids=allowed_user_ids,
            ):
                _logger.debug(
                    "Discord message rejected: user=%s (id=%s)",
                    message.author,
                    message.author.id,
                )
                return

            channel_target = str(message.channel.id)

            def reply_fn(text: str) -> None:
                self.send(channel_target, text)

            content = message.content
            if client.user:
                content = re.sub(
                    rf"<@!?{client.user.id}>",
                    "",
                    content,
                ).strip()

            prompt = safe_substitute(self._config.prompt_template, {"message": content})
            event = TriggerEvent(
                trigger_type="discord",
                prompt=prompt,
                metadata={
                    "channel_target": channel_target,
                    "user": str(message.author),
                    "channel_id": str(message.channel.id),
                    "user_id": str(message.author.id),
                },
                reply_fn=reply_fn,
                principal_id=f"discord:{message.author.id}",
                principal_roles=[r.name for r in message.author.roles]
                if isinstance(message.author, discord.Member)
                else [],
            )
            await asyncio.get_running_loop().run_in_executor(None, callback, event)

        async def run_bot() -> None:
            self._loop = asyncio.get_running_loop()
            stop_event = self._stop_event

            async def wait_stop():
                while not stop_event.is_set():
                    await asyncio.sleep(1)
                self._ready.clear()
                await client.close()

            async with client:
                _logger.info("Discord bot connected")
                stop_task = asyncio.create_task(wait_stop())
                await asyncio.gather(client.start(token), stop_task)

        self._stop_event.clear()
        self._ready.clear()
        run_sync(run_bot())

    def stop(self) -> None:
        self._stop_event.set()

    def send(self, target: str, text: str) -> None:
        if not self._ready.is_set():
            return
        try:
            client = self._client

            async def _send_to_channel() -> None:
                ch = client.get_channel(int(target))  # type: ignore[union-attr]
                if ch is None:
                    ch = await client.fetch_channel(int(target))  # type: ignore[union-attr]
                for chunk in _chunk_text(text, _DISCORD_MAX_MESSAGE):
                    await ch.send(chunk)

            coro = _send_to_channel()
            try:
                future = asyncio.run_coroutine_threadsafe(coro, self._loop)
                future.add_done_callback(lambda f, t=target: _log_async_error(f, t))
            except Exception:
                coro.close()
                raise
        except Exception:
            _logger.warning("Failed to send Discord message to %s", target, exc_info=True)
