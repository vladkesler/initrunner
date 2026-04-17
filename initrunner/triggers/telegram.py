"""Telegram channel adapter -- outbound HTTPS only, no ports opened."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable

from initrunner._async import run_sync
from initrunner._text import safe_substitute
from initrunner.agent.schema.triggers import TelegramTriggerConfig
from initrunner.triggers.base import ChannelAdapter, TriggerEvent, _chunk_text

_logger = logging.getLogger(__name__)

_TELEGRAM_MAX_MESSAGE = 4096


def _log_async_error(future: asyncio.Future, target: str) -> None:
    if (exc := future.exception()) is not None:
        _logger.warning("Async send to %s failed: %s", target, exc)


class TelegramAdapter(ChannelAdapter):
    """Bidirectional Telegram adapter: long-polling inbound, Bot API outbound."""

    def __init__(self, config: TelegramTriggerConfig) -> None:
        self._config = config
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bot: object | None = None  # telegram.Bot, set during start()

    @property
    def platform(self) -> str:
        return "telegram"

    def start(self, callback: Callable[[TriggerEvent], None]) -> None:
        from telegram import Update  # type: ignore[unresolved-import]
        from telegram.ext import (  # type: ignore[unresolved-import]
            ApplicationBuilder,
            MessageHandler,
            filters,
        )

        from initrunner.credentials import get_resolver

        token = get_resolver().get(self._config.token_env)
        if not token:
            _logger.error(
                "%s not set (env or vault) -- Telegram adapter not started. "
                "Export the env var or run: initrunner vault set %s",
                self._config.token_env,
                self._config.token_env,
            )
            return

        allowed_usernames = set(self._config.allowed_users)
        allowed_user_ids = set(self._config.allowed_user_ids)

        async def on_message(update: Update, context) -> None:
            if update.message is None or update.message.text is None:
                return
            user = update.effective_user
            username = user.username if user else None
            user_id = user.id if user else None

            if allowed_usernames or allowed_user_ids:
                username_ok = bool(allowed_usernames and username in allowed_usernames)
                user_id_ok = bool(allowed_user_ids and user_id in allowed_user_ids)
                if not username_ok and not user_id_ok:
                    _logger.debug(
                        "Telegram message rejected: user=%s (id=%s) not in allowed list",
                        username,
                        user_id,
                    )
                    return

            if update.effective_chat is None:
                raise RuntimeError("Telegram update missing chat")
            chat_id = update.effective_chat.id
            channel_target = str(chat_id)

            def reply_fn(text: str) -> None:
                self.send(channel_target, text)

            prompt = safe_substitute(self._config.prompt_template, {"message": update.message.text})
            event = TriggerEvent(
                trigger_type="telegram",
                prompt=prompt,
                metadata={
                    "channel_target": channel_target,
                    "user": username or "",
                    "chat_id": str(chat_id),
                    "user_id": str(user_id or ""),
                },
                reply_fn=reply_fn,
                principal_id=f"telegram:{user_id}" if user_id else None,
            )
            await asyncio.get_running_loop().run_in_executor(None, callback, event)

        async def run_bot() -> None:
            self._loop = asyncio.get_running_loop()
            app = ApplicationBuilder().token(token).build()
            self._bot = app.bot
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
            await app.initialize()
            await app.start()
            if app.updater is None:
                raise RuntimeError("Telegram updater not initialized")
            await app.updater.start_polling()
            self._ready.set()
            _logger.info("Telegram bot started polling")
            while not self._stop_event.is_set():
                await asyncio.sleep(1)
            self._ready.clear()
            if app.updater is None:
                raise RuntimeError("Telegram updater not initialized")
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

        self._stop_event.clear()
        self._ready.clear()
        run_sync(run_bot())

    def stop(self) -> None:
        self._stop_event.set()

    def send(self, target: str, text: str) -> None:
        if not self._ready.is_set():
            return
        try:
            loop = self._loop
            assert loop is not None  # guarded by _ready event
            for chunk in _chunk_text(text, _TELEGRAM_MAX_MESSAGE):
                future = asyncio.run_coroutine_threadsafe(
                    self._bot.send_message(chat_id=int(target), text=chunk),  # type: ignore[union-attr]
                    loop,
                )
                future.add_done_callback(lambda f, t=target: _log_async_error(f, t))
        except Exception:
            _logger.warning("Failed to send Telegram message to %s", target, exc_info=True)
