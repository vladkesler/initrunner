"""Discord WebSocket client trigger — outbound only, no ports opened."""

from __future__ import annotations

import logging
import os
import re

from initrunner.agent.schema.triggers import DiscordTriggerConfig
from initrunner.triggers.base import TriggerBase, TriggerEvent, _chunk_text

_logger = logging.getLogger(__name__)

_DISCORD_MAX_MESSAGE = 2000


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
            # Only roles configured — DMs denied (no role context)
            return False
        if allowed_user_ids and not user_id_passed:
            # User IDs configured but sender not listed
            return False
        # If both configured: user_id match allows DM even without role check
        if allowed_roles and allowed_user_ids and not user_id_passed:
            return False
        # No identity filters at all, or user_id matched — allow
        return True

    # Channel filter — only applies to guild channels, not DMs
    if allowed_channels and channel_id not in allowed_channels:
        return False

    # Role/user_id filter for guild messages
    if allowed_roles or allowed_user_ids:
        role_passed = bool(allowed_roles and (author_roles & allowed_roles))
        if not role_passed and not user_id_passed:
            return False

    return True


class DiscordTrigger(TriggerBase):
    """Trigger that listens for Discord messages via WebSocket client."""

    def __init__(
        self,
        config: DiscordTriggerConfig,
        callback,
    ) -> None:
        super().__init__(callback)
        self._config = config

    def _run(self) -> None:
        import asyncio

        import discord  # type: ignore[import-not-found]

        token = os.environ.get(self._config.token_env)
        if not token:
            _logger.error(
                "Env var %s not set — Discord trigger not started", self._config.token_env
            )
            return

        allowed_channels = set(self._config.channel_ids)
        allowed_roles = set(self._config.allowed_roles)
        allowed_user_ids = set(self._config.allowed_user_ids)
        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_message(message: discord.Message) -> None:
            if message.author == client.user:
                return

            # Respond to DMs or mentions only
            is_dm = isinstance(message.channel, discord.DMChannel)
            is_mentioned = client.user in message.mentions
            if not is_dm and not is_mentioned:
                return

            # Build role set for guild members
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

            channel = message.channel
            loop = asyncio.get_running_loop()

            def reply_fn(text: str) -> None:
                for chunk in _chunk_text(text, _DISCORD_MAX_MESSAGE):
                    asyncio.run_coroutine_threadsafe(channel.send(chunk), loop)

            # Strip bot mention using mention ID pattern, not display name
            content = message.content
            if client.user:
                # Discord raw mentions are <@USER_ID> or <@!USER_ID>
                content = re.sub(
                    rf"<@!?{client.user.id}>",
                    "",
                    content,
                ).strip()

            prompt = self._config.prompt_template.format(message=content)
            event = TriggerEvent(
                trigger_type="discord",
                prompt=prompt,
                metadata={
                    "user": str(message.author),
                    "channel_id": str(message.channel.id),
                    "user_id": str(message.author.id),
                },
                reply_fn=reply_fn,
            )
            await asyncio.get_running_loop().run_in_executor(None, self._callback, event)

        async def run_bot() -> None:
            stop_event = self._stop_event

            async def wait_stop():
                while not stop_event.is_set():
                    await asyncio.sleep(1)
                await client.close()

            async with client:
                _logger.info("Discord bot connected")
                stop_task = asyncio.create_task(wait_stop())
                await asyncio.gather(client.start(token), stop_task)

        asyncio.run(run_bot())

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                _logger.warning("Discord trigger thread still alive after stop")
