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

        from telegram import Update  # type: ignore[import-not-found]
        from telegram.ext import (  # type: ignore[import-not-found]
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

        allowed = set(self._config.allowed_users)
        loop: asyncio.AbstractEventLoop | None = None

        async def on_message(update: Update, context) -> None:
            if update.message is None or update.message.text is None:
                return
            user = update.effective_user
            username = user.username if user else None
            if allowed and username not in allowed:
                return

            chat_id = update.effective_chat.id  # type: ignore[union-attr]
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
                metadata={"user": username or "", "chat_id": str(chat_id)},
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
            await app.updater.start_polling()  # type: ignore[union-attr]
            _logger.info("Telegram bot started polling")
            # Block until stop signal
            while not self._stop_event.is_set():
                await asyncio.sleep(1)
            await app.updater.stop()  # type: ignore[union-attr]
            await app.stop()
            await app.shutdown()

        asyncio.run(run_bot())

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                _logger.warning("Telegram trigger thread still alive after stop")
