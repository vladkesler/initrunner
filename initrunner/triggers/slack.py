"""Slack channel adapter -- Socket Mode inbound, Web API outbound, no ports opened."""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from initrunner._compat import require_extra
from initrunner._text import safe_substitute
from initrunner.agent.schema.triggers import SlackTriggerConfig
from initrunner.triggers.base import ChannelAdapter, TriggerEvent, _chunk_text

_logger = logging.getLogger(__name__)

_SLACK_MAX_MESSAGE = 3000
_MENTION_RE = re.compile(r"<@[UW][A-Z0-9]+>")


def _log_dispatch_error(future: Future) -> None:
    if (exc := future.exception()) is not None:
        _logger.warning("Slack dispatch failed: %s", exc)


def _check_slack_access(
    *,
    is_dm: bool,
    user_id: str,
    channel_id: str,
    allowed_channels: set[str],
    allowed_user_ids: set[str],
) -> bool:
    """Return True if the message should be processed, False to drop it.

    Pure function extracted so it can be unit-tested without a live socket.
    """
    if allowed_user_ids and user_id not in allowed_user_ids:
        return False
    if not is_dm and allowed_channels and channel_id not in allowed_channels:
        return False
    return True


class SlackAdapter(ChannelAdapter):
    """Bidirectional Slack adapter: Socket Mode inbound, Web API outbound."""

    def __init__(self, config: SlackTriggerConfig) -> None:
        self._config = config
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._socket_client: object | None = None
        self._web_client: object | None = None
        self._bot_user_id: str | None = None
        self._dispatch_executor: ThreadPoolExecutor | None = None

    @property
    def platform(self) -> str:
        return "slack"

    def start(self, callback: Callable[[TriggerEvent], None]) -> None:
        require_extra("slack_sdk")
        from slack_sdk import WebClient  # type: ignore[import-not-found]
        from slack_sdk.socket_mode import SocketModeClient  # type: ignore[import-not-found]
        from slack_sdk.socket_mode.response import (  # type: ignore[import-not-found]
            SocketModeResponse,
        )

        from initrunner.credentials import get_resolver

        resolver = get_resolver()
        app_token = resolver.get(self._config.app_token_env)
        bot_token = resolver.get(self._config.bot_token_env)
        if not app_token or not bot_token:
            _logger.error(
                "Slack tokens missing (need %s for Socket Mode and %s for replies) -- "
                "Slack adapter not started. Export env vars or run: "
                "initrunner vault set %s / initrunner vault set %s",
                self._config.app_token_env,
                self._config.bot_token_env,
                self._config.app_token_env,
                self._config.bot_token_env,
            )
            return

        web_client = WebClient(token=bot_token)
        try:
            auth = web_client.auth_test()
            self._bot_user_id = auth["user_id"]
        except Exception:
            _logger.warning("Slack auth.test failed -- adapter not started", exc_info=True)
            return

        self._web_client = web_client
        socket_client = SocketModeClient(app_token=app_token, web_client=web_client)
        self._socket_client = socket_client

        allowed_channels = set(self._config.channel_ids)
        allowed_user_ids = set(self._config.allowed_user_ids)
        respond_in_thread = self._config.respond_in_thread
        bot_user_id = self._bot_user_id
        dispatch_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="slack-dispatch")
        self._dispatch_executor = dispatch_executor

        def listener(client, req) -> None:  # type: ignore[no-untyped-def]
            client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

            if req.type != "events_api":
                return
            if req.payload.get("type") != "event_callback":
                return
            event = req.payload.get("event") or {}
            event_type = event.get("type")
            if event_type not in ("app_mention", "message"):
                return

            # Drop bot's own messages, edits, deletes
            if event.get("bot_id"):
                return
            if event.get("subtype"):
                return
            if bot_user_id and event.get("user") == bot_user_id:
                return

            channel_id = event.get("channel")
            user_id = event.get("user")
            if not channel_id or not user_id:
                return

            is_dm = event.get("channel_type") == "im"
            # For message events, only accept DMs (app_mention handles channel mentions)
            if event_type == "message" and not is_dm:
                return

            if not _check_slack_access(
                is_dm=is_dm,
                user_id=user_id,
                channel_id=channel_id,
                allowed_channels=allowed_channels,
                allowed_user_ids=allowed_user_ids,
            ):
                _logger.debug("Slack message rejected: user=%s channel=%s", user_id, channel_id)
                return

            thread_ts = event.get("thread_ts")
            event_ts = event.get("ts")
            if thread_ts:
                reply_thread_ts: str | None = thread_ts
                channel_target = f"{channel_id}:{thread_ts}"
            elif not is_dm and respond_in_thread and event_ts:
                reply_thread_ts = event_ts
                channel_target = f"{channel_id}:{event_ts}"
            else:
                reply_thread_ts = None
                channel_target = channel_id

            def reply_fn(text: str, _ch=channel_id, _tts=reply_thread_ts) -> None:
                self._send_threaded(_ch, _tts, text)

            text = event.get("text") or ""
            text = _MENTION_RE.sub("", text).strip()

            prompt = safe_substitute(self._config.prompt_template, {"message": text})
            trigger_event = TriggerEvent(
                trigger_type="slack",
                prompt=prompt,
                metadata={
                    "channel_target": channel_target,
                    "user": user_id,
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "thread_ts": thread_ts or "",
                },
                reply_fn=reply_fn,
                principal_id=f"slack:{user_id}",
            )
            fut = dispatch_executor.submit(callback, trigger_event)
            fut.add_done_callback(_log_dispatch_error)

        socket_client.socket_mode_request_listeners.append(listener)

        self._stop_event.clear()
        self._ready.clear()
        try:
            socket_client.connect()
            self._ready.set()
            _logger.info("Slack Socket Mode connected")
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=1)
        finally:
            self._ready.clear()
            try:
                socket_client.close()
            except Exception:
                _logger.debug("Slack socket close failed", exc_info=True)
            dispatch_executor.shutdown(wait=False, cancel_futures=True)
            self._dispatch_executor = None

    def stop(self) -> None:
        self._stop_event.set()

    def send(self, target: str, text: str) -> None:
        self._send_threaded(target, None, text)

    def _send_threaded(self, channel_id: str, thread_ts: str | None, text: str) -> None:
        if not self._ready.is_set():
            return
        web_client = self._web_client
        if web_client is None:
            return
        try:
            for chunk in _chunk_text(text, _SLACK_MAX_MESSAGE):
                kwargs: dict[str, object] = {"channel": channel_id, "text": chunk}
                if thread_ts:
                    kwargs["thread_ts"] = thread_ts
                web_client.chat_postMessage(**kwargs)  # type: ignore[attr-defined]
        except Exception:
            _logger.warning("Failed to send Slack message to %s", channel_id, exc_info=True)
