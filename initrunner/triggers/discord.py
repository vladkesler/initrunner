"""Discord WebSocket client trigger — outbound only, no ports opened."""

from __future__ import annotations

import logging
import os
import re

from initrunner.agent.schema.triggers import DiscordTriggerConfig
from initrunner.triggers.base import TriggerBase, TriggerEvent, _chunk_text

_logger = logging.getLogger(__name__)

_DISCORD_MAX_MESSAGE = 2000


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

            # When allowed_roles is set, deny DMs (no role context available)
            if allowed_roles and is_dm:
                return

            # Channel filter
            if allowed_channels and str(message.channel.id) not in allowed_channels:
                return

            # Role filter (guild messages only — DMs already denied above when roles set)
            if allowed_roles and isinstance(message.author, discord.Member):
                user_roles = {r.name for r in message.author.roles}
                if not user_roles & allowed_roles:
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
