"""Telegram long-polling trigger — outbound HTTPS only, no ports opened."""

from __future__ import annotations

import logging
import os

from initrunner.agent.schema.triggers import TelegramTriggerConfig
from initrunner.triggers.base import TriggerBase, TriggerEvent, _chunk_text

_logger = logging.getLogger(__name__)

_TELEGRAM_MAX_MESSAGE = 4096


class TelegramTrigger(TriggerBase):
    """Trigger that listens for Telegram messages via long-polling."""

    def __init__(
        self,
        config: TelegramTriggerConfig,
        callback,
    ) -> None:
        super().__init__(callback)
        self._config = config

    def _run(self) -> None:
        import asyncio

        from telegram import Update  # type: ignore[unresolved-import]
        from telegram.ext import (  # type: ignore[unresolved-import]
            ApplicationBuilder,
            MessageHandler,
            filters,
        )

        token = os.environ.get(self._config.token_env)
        if not token:
            _logger.error(
                "Env var %s not set — Telegram trigger not started", self._config.token_env
            )
            return

        allowed_usernames = set(self._config.allowed_users)
        allowed_user_ids = set(self._config.allowed_user_ids)
        loop: asyncio.AbstractEventLoop | None = None

        async def on_message(update: Update, context) -> None:
            if update.message is None or update.message.text is None:
                return
            user = update.effective_user
            username = user.username if user else None
            user_id = user.id if user else None

            # Union semantics: match either username OR user ID. Empty = allow all.
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

            chat_id = update.effective_chat.id
            bot = context.bot

            def reply_fn(text: str) -> None:
                if loop is None:
                    _logger.error("Event loop not available — cannot send Telegram reply")
                    return
                for chunk in _chunk_text(text, _TELEGRAM_MAX_MESSAGE):
                    asyncio.run_coroutine_threadsafe(
                        bot.send_message(chat_id=chat_id, text=chunk),
                        loop,
                    )

            prompt = self._config.prompt_template.format(message=update.message.text)
            event = TriggerEvent(
                trigger_type="telegram",
                prompt=prompt,
                metadata={
                    "user": username or "",
                    "chat_id": str(chat_id),
                    "user_id": str(user_id or ""),
                },
                reply_fn=reply_fn,
            )
            await asyncio.get_running_loop().run_in_executor(None, self._callback, event)

        async def run_bot() -> None:
            nonlocal loop
            loop = asyncio.get_running_loop()
            app = ApplicationBuilder().token(token).build()
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
            await app.initialize()
            await app.start()
            await app.updater.start_polling()
            _logger.info("Telegram bot started polling")
            # Block until stop signal
            while not self._stop_event.is_set():
                await asyncio.sleep(1)
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

        asyncio.run(run_bot())

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                _logger.warning("Telegram trigger thread still alive after stop")
