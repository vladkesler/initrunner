"""Tests for the trigger system."""

import time
from unittest.mock import MagicMock, patch

from initrunner.agent.schema.triggers import (
    CronTriggerConfig,
    DiscordTriggerConfig,
    FileWatchTriggerConfig,
    SlackTriggerConfig,
    TelegramTriggerConfig,
)
from initrunner.triggers.base import (
    CONVERSATIONAL_TRIGGER_TYPES,
    ChannelAdapter,
    ChannelTriggerBridge,
    TriggerEvent,
    register_conversational_trigger_type,
)
from initrunner.triggers.cron import CronTrigger
from initrunner.triggers.dispatcher import TriggerDispatcher
from initrunner.triggers.file_watcher import FileWatchTrigger


class TestTriggerEvent:
    def test_creation(self):
        event = TriggerEvent(trigger_type="cron", prompt="test")
        assert event.trigger_type == "cron"
        assert event.prompt == "test"
        assert event.timestamp  # auto-populated
        assert event.metadata == {}

    def test_reply_fn_default_none(self):
        event = TriggerEvent(trigger_type="cron", prompt="test")
        assert event.reply_fn is None

    def test_reply_fn_can_be_set(self):
        fn = lambda text: None  # noqa: E731
        event = TriggerEvent(trigger_type="telegram", prompt="hi", reply_fn=fn)
        assert event.reply_fn is fn

    def test_backward_compatible_without_reply_fn(self):
        """Existing code that doesn't pass reply_fn still works."""
        event = TriggerEvent(
            trigger_type="cron",
            prompt="test",
            metadata={"schedule": "* * * * *"},
        )
        assert event.reply_fn is None

    def test_conversation_key_via_channel_target(self):
        register_conversational_trigger_type("telegram")
        event = TriggerEvent(
            trigger_type="telegram",
            prompt="hi",
            metadata={"channel_target": "12345"},
        )
        assert event.conversation_key == "telegram:12345"

    def test_conversation_key_discord_via_channel_target(self):
        register_conversational_trigger_type("discord")
        event = TriggerEvent(
            trigger_type="discord",
            prompt="hi",
            metadata={"channel_target": "67890"},
        )
        assert event.conversation_key == "discord:67890"

    def test_conversation_key_cron_returns_none(self):
        event = TriggerEvent(trigger_type="cron", prompt="test")
        assert event.conversation_key is None

    def test_conversation_key_missing_channel_target_returns_none(self):
        register_conversational_trigger_type("telegram")
        event = TriggerEvent(trigger_type="telegram", prompt="hi")
        assert event.conversation_key is None

    def test_conversation_key_non_conversational_returns_none(self):
        event = TriggerEvent(
            trigger_type="webhook",
            prompt="hi",
            metadata={"channel_target": "12345"},
        )
        assert event.conversation_key is None


class TestChannelTriggerBridge:
    """Tests for the ChannelTriggerBridge wrapping a ChannelAdapter."""

    @staticmethod
    def _make_mock_adapter(platform: str = "test_platform") -> MagicMock:
        adapter = MagicMock(spec=ChannelAdapter)
        adapter.platform = platform
        return adapter

    def test_registers_platform_on_construction(self):
        adapter = self._make_mock_adapter("myplatform")
        ChannelTriggerBridge(adapter, lambda e: None)
        assert "myplatform" in CONVERSATIONAL_TRIGGER_TYPES

    def test_run_delegates_to_adapter_start(self):
        adapter = self._make_mock_adapter()
        cb = lambda e: None  # noqa: E731
        bridge = ChannelTriggerBridge(adapter, cb)
        bridge._run()
        adapter.start.assert_called_once_with(cb)

    def test_stop_delegates_to_adapter_stop(self):
        adapter = self._make_mock_adapter()
        bridge = ChannelTriggerBridge(adapter, lambda e: None)
        bridge._thread = None  # no thread to join
        bridge.stop()
        adapter.stop.assert_called_once()

    def test_adapter_accessible(self):
        adapter = self._make_mock_adapter()
        bridge = ChannelTriggerBridge(adapter, lambda e: None)
        assert bridge._adapter is adapter


class TestTelegramAdapterSend:
    """Tests for TelegramAdapter.send() method."""

    def test_send_noop_before_start(self):
        from initrunner.triggers.telegram import TelegramAdapter

        adapter = TelegramAdapter(TelegramTriggerConfig())
        # Should not raise
        adapter.send("12345", "hello")

    def test_send_delegates_to_bot(self):
        from initrunner.triggers.telegram import TelegramAdapter

        adapter = TelegramAdapter(TelegramTriggerConfig())
        mock_bot = MagicMock()
        mock_loop = MagicMock()
        mock_future = MagicMock()

        adapter._bot = mock_bot
        adapter._loop = mock_loop
        adapter._ready.set()

        tg_rcts = "initrunner.triggers.telegram.asyncio.run_coroutine_threadsafe"
        with patch(tg_rcts, return_value=mock_future) as mock_rcts:
            adapter.send("12345", "hello")

        mock_rcts.assert_called_once()
        mock_future.add_done_callback.assert_called_once()

    def test_send_chunks_long_messages(self):
        from initrunner.triggers.telegram import TelegramAdapter

        adapter = TelegramAdapter(TelegramTriggerConfig())
        mock_bot = MagicMock()
        mock_loop = MagicMock()
        mock_future = MagicMock()

        adapter._bot = mock_bot
        adapter._loop = mock_loop
        adapter._ready.set()

        long_text = "x" * 5000  # exceeds 4096 limit

        tg_rcts = "initrunner.triggers.telegram.asyncio.run_coroutine_threadsafe"
        with patch(tg_rcts, return_value=mock_future) as mock_rcts:
            adapter.send("12345", long_text)

        assert mock_rcts.call_count == 2  # chunked into 2

    def test_send_never_raises(self):
        from initrunner.triggers.telegram import TelegramAdapter

        adapter = TelegramAdapter(TelegramTriggerConfig())
        adapter._bot = MagicMock()
        adapter._loop = MagicMock()
        adapter._ready.set()

        with patch(
            "initrunner.triggers.telegram.asyncio.run_coroutine_threadsafe",
            side_effect=RuntimeError("boom"),
        ):
            # Should not raise
            adapter.send("12345", "hello")


class TestDiscordAdapterSend:
    """Tests for DiscordAdapter.send() method."""

    def test_send_noop_before_start(self):
        from initrunner.triggers.discord import DiscordAdapter

        adapter = DiscordAdapter(DiscordTriggerConfig())
        # Should not raise
        adapter.send("67890", "hello")

    def test_send_delegates_to_client(self):
        from initrunner.triggers.discord import DiscordAdapter

        adapter = DiscordAdapter(DiscordTriggerConfig())
        mock_client = MagicMock()
        mock_loop = MagicMock()
        mock_future = MagicMock()

        adapter._client = mock_client
        adapter._loop = mock_loop
        adapter._ready.set()

        dc_rcts = "initrunner.triggers.discord.asyncio.run_coroutine_threadsafe"
        with patch(dc_rcts, return_value=mock_future) as mock_rcts:
            adapter.send("67890", "hello")

        mock_rcts.assert_called_once()
        mock_future.add_done_callback.assert_called_once()
        # Close the unscheduled coroutine to silence "never awaited" warning
        mock_rcts.call_args[0][0].close()

    def test_send_never_raises(self):
        from initrunner.triggers.discord import DiscordAdapter

        adapter = DiscordAdapter(DiscordTriggerConfig())
        adapter._client = MagicMock()
        adapter._loop = MagicMock()
        adapter._ready.set()

        with patch(
            "initrunner.triggers.discord.asyncio.run_coroutine_threadsafe",
            side_effect=RuntimeError("boom"),
        ):
            # Should not raise
            adapter.send("67890", "hello")


class TestCronTrigger:
    def test_start_and_stop(self):
        config = CronTriggerConfig(schedule="* * * * *", prompt="test")
        events: list[TriggerEvent] = []
        trigger = CronTrigger(config, events.append)
        trigger.start()
        time.sleep(0.2)
        trigger.stop()
        # Just verify it starts and stops cleanly

    def test_stop_event_is_respected(self):
        config = CronTriggerConfig(schedule="0 0 1 1 *", prompt="never fires")
        trigger = CronTrigger(config, lambda e: None)
        trigger.start()
        trigger.stop()
        assert trigger._stop_event.is_set()


class TestFileWatchTrigger:
    def test_start_and_stop(self, tmp_path):
        watched = tmp_path / "watched"
        watched.mkdir()
        config = FileWatchTriggerConfig(paths=[str(watched)])
        events: list[TriggerEvent] = []
        trigger = FileWatchTrigger(config, events.append)
        trigger.start()
        time.sleep(0.3)
        trigger.stop()

    def test_detects_file_change(self, tmp_path):
        watched = tmp_path / "watched"
        watched.mkdir()
        config = FileWatchTriggerConfig(
            paths=[str(watched)], extensions=[".txt"], debounce_seconds=0.1
        )
        events: list[TriggerEvent] = []
        trigger = FileWatchTrigger(config, events.append)
        trigger.start()
        time.sleep(0.3)
        (watched / "test.txt").write_text("hello")
        time.sleep(1.0)  # allow debounce + detection
        trigger.stop()
        assert len(events) >= 1
        assert "test.txt" in events[0].prompt

    def test_process_existing_fires_for_preexisting_files(self, tmp_path):
        watched = tmp_path / "watched"
        watched.mkdir()
        (watched / "a.txt").write_text("hello")
        (watched / "b.txt").write_text("world")
        config = FileWatchTriggerConfig(
            paths=[str(watched)],
            extensions=[".txt"],
            process_existing=True,
            debounce_seconds=0.1,
        )
        events: list[TriggerEvent] = []
        trigger = FileWatchTrigger(config, events.append)
        trigger.start()
        time.sleep(0.5)
        trigger.stop()
        assert len(events) >= 2
        prompts = [e.prompt for e in events]
        assert any("a.txt" in p for p in prompts)
        assert any("b.txt" in p for p in prompts)

    def test_process_existing_respects_extensions(self, tmp_path):
        watched = tmp_path / "watched"
        watched.mkdir()
        (watched / "good.txt").write_text("keep")
        (watched / "bad.log").write_text("skip")
        config = FileWatchTriggerConfig(
            paths=[str(watched)],
            extensions=[".txt"],
            process_existing=True,
            debounce_seconds=0.1,
        )
        events: list[TriggerEvent] = []
        trigger = FileWatchTrigger(config, events.append)
        trigger.start()
        time.sleep(0.5)
        trigger.stop()
        assert len(events) == 1
        assert "good.txt" in events[0].prompt
        assert all("bad.log" not in e.prompt for e in events)

    def test_process_existing_default_false(self, tmp_path):
        watched = tmp_path / "watched"
        watched.mkdir()
        (watched / "existing.txt").write_text("should not trigger")
        config = FileWatchTriggerConfig(
            paths=[str(watched)],
            extensions=[".txt"],
            debounce_seconds=0.1,
        )
        assert config.process_existing is False
        events: list[TriggerEvent] = []
        trigger = FileWatchTrigger(config, events.append)
        trigger.start()
        time.sleep(0.5)
        trigger.stop()
        assert len(events) == 0


class TestTriggerDispatcher:
    def test_empty_dispatcher(self):
        dispatcher = TriggerDispatcher([], lambda e: None)
        assert dispatcher.count == 0

    def test_context_manager(self, tmp_path):
        watched = tmp_path / "watched"
        watched.mkdir()
        configs = [FileWatchTriggerConfig(paths=[str(watched)])]
        with TriggerDispatcher(configs, lambda e: None) as d:
            assert d.count == 1

    def test_builds_cron_trigger(self):
        configs = [CronTriggerConfig(schedule="0 0 1 1 *", prompt="test")]
        dispatcher = TriggerDispatcher(configs, lambda e: None)
        assert dispatcher.count == 1

    def test_builds_telegram_trigger(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        configs = [TelegramTriggerConfig()]
        dispatcher = TriggerDispatcher(configs, lambda e: None)
        assert dispatcher.count == 1

    def test_builds_discord_trigger(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
        configs = [DiscordTriggerConfig()]
        dispatcher = TriggerDispatcher(configs, lambda e: None)
        assert dispatcher.count == 1

    def test_builds_telegram_trigger_with_user_ids(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        configs = [TelegramTriggerConfig(allowed_user_ids=[12345])]
        dispatcher = TriggerDispatcher(configs, lambda e: None)
        assert dispatcher.count == 1

    def test_builds_discord_trigger_with_user_ids(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
        configs = [DiscordTriggerConfig(allowed_user_ids=["111222333"])]
        dispatcher = TriggerDispatcher(configs, lambda e: None)
        assert dispatcher.count == 1

    def test_telegram_builder_returns_channel_bridge(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        configs = [TelegramTriggerConfig()]
        dispatcher = TriggerDispatcher(configs, lambda e: None)
        trigger = dispatcher._triggers[0]
        assert isinstance(trigger, ChannelTriggerBridge)
        assert "telegram" in CONVERSATIONAL_TRIGGER_TYPES

    def test_discord_builder_returns_channel_bridge(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
        configs = [DiscordTriggerConfig()]
        dispatcher = TriggerDispatcher(configs, lambda e: None)
        trigger = dispatcher._triggers[0]
        assert isinstance(trigger, ChannelTriggerBridge)
        assert "discord" in CONVERSATIONAL_TRIGGER_TYPES


class TestTelegramFiltering:
    """Unit tests for the Telegram filter logic inside on_message."""

    @staticmethod
    def _make_update(username, user_id, text="hello"):
        """Build a minimal mock Update object."""
        from unittest.mock import MagicMock

        update = MagicMock()
        update.message.text = text
        user = MagicMock()
        user.username = username
        user.id = user_id
        update.effective_user = user
        update.effective_chat.id = 999
        return update

    @staticmethod
    def _should_allow(config, username, user_id):
        """Simulate the filter logic from telegram.py without running async."""
        allowed_usernames = set(config.allowed_users)
        allowed_user_ids = set(config.allowed_user_ids)
        if allowed_usernames or allowed_user_ids:
            username_ok = bool(allowed_usernames and username in allowed_usernames)
            user_id_ok = bool(allowed_user_ids and user_id in allowed_user_ids)
            return username_ok or user_id_ok
        return True

    def test_telegram_allows_all_when_no_filters(self):
        cfg = TelegramTriggerConfig()
        assert self._should_allow(cfg, "anyone", 99999) is True

    def test_telegram_allows_by_username(self):
        cfg = TelegramTriggerConfig(allowed_users=["alice"])
        assert self._should_allow(cfg, "alice", 11111) is True

    def test_telegram_rejects_wrong_username(self):
        cfg = TelegramTriggerConfig(allowed_users=["alice"])
        assert self._should_allow(cfg, "bob", 22222) is False

    def test_telegram_allows_by_user_id(self):
        cfg = TelegramTriggerConfig(allowed_user_ids=[12345])
        assert self._should_allow(cfg, "anyone", 12345) is True

    def test_telegram_rejects_wrong_user_id(self):
        cfg = TelegramTriggerConfig(allowed_user_ids=[12345])
        assert self._should_allow(cfg, "anyone", 99999) is False

    def test_telegram_union_username_passes(self):
        cfg = TelegramTriggerConfig(allowed_users=["alice"], allowed_user_ids=[12345])
        assert self._should_allow(cfg, "alice", 99999) is True

    def test_telegram_union_user_id_passes(self):
        cfg = TelegramTriggerConfig(allowed_users=["alice"], allowed_user_ids=[12345])
        assert self._should_allow(cfg, "bob", 12345) is True

    def test_telegram_union_neither_rejects(self):
        cfg = TelegramTriggerConfig(allowed_users=["alice"], allowed_user_ids=[12345])
        assert self._should_allow(cfg, "bob", 99999) is False

    def test_telegram_user_without_username_allowed_by_id(self):
        cfg = TelegramTriggerConfig(allowed_user_ids=[12345])
        assert self._should_allow(cfg, None, 12345) is True


class TestDiscordFiltering:
    """Unit tests for the Discord _check_discord_access helper."""

    @staticmethod
    def _check(**kwargs):
        from initrunner.triggers.discord import _check_discord_access

        defaults = {
            "is_dm": False,
            "author_roles": set(),
            "author_id": "100",
            "channel_id": "999",
            "allowed_channels": set(),
            "allowed_roles": set(),
            "allowed_user_ids": set(),
        }
        defaults.update(kwargs)
        return _check_discord_access(**defaults)  # type: ignore[invalid-argument-type]

    def test_discord_allows_all_when_no_filters(self):
        assert self._check() is True

    def test_discord_role_only_allows_matching_role(self):
        assert self._check(allowed_roles={"Admin"}, author_roles={"Admin", "@everyone"}) is True

    def test_discord_role_only_rejects_wrong_role(self):
        assert self._check(allowed_roles={"Admin"}, author_roles={"Member", "@everyone"}) is False

    def test_discord_role_only_denies_dm(self):
        assert self._check(is_dm=True, allowed_roles={"Admin"}) is False

    def test_discord_user_id_allows_matching_id(self):
        assert self._check(allowed_user_ids={"123"}, author_id="123") is True

    def test_discord_user_id_rejects_wrong_id(self):
        assert self._check(allowed_user_ids={"123"}, author_id="456") is False

    def test_discord_user_id_allows_dm(self):
        assert self._check(is_dm=True, allowed_user_ids={"123"}, author_id="123") is True

    def test_discord_user_id_rejects_dm_wrong_id(self):
        assert self._check(is_dm=True, allowed_user_ids={"123"}, author_id="456") is False

    def test_discord_role_or_id_guild_role_passes(self):
        assert (
            self._check(
                allowed_roles={"Admin"},
                allowed_user_ids={"123"},
                author_roles={"Admin"},
                author_id="456",
            )
            is True
        )

    def test_discord_role_or_id_guild_id_passes(self):
        assert (
            self._check(
                allowed_roles={"Admin"},
                allowed_user_ids={"123"},
                author_roles={"Member"},
                author_id="123",
            )
            is True
        )

    def test_discord_role_or_id_dm_id_passes(self):
        assert (
            self._check(
                is_dm=True,
                allowed_roles={"Admin"},
                allowed_user_ids={"123"},
                author_id="123",
            )
            is True
        )

    def test_discord_role_or_id_dm_no_id_rejects(self):
        assert (
            self._check(
                is_dm=True,
                allowed_roles={"Admin"},
                allowed_user_ids={"123"},
                author_id="456",
            )
            is False
        )

    def test_discord_channel_ids_guild_allowed(self):
        assert self._check(allowed_channels={"999"}, channel_id="999") is True

    def test_discord_channel_ids_guild_rejected(self):
        assert self._check(allowed_channels={"999"}, channel_id="888") is False

    def test_discord_channel_ids_dm_not_affected(self):
        assert self._check(is_dm=True, allowed_channels={"999"}, channel_id="888") is True


class TestSlackFiltering:
    """Unit tests for the Slack _check_slack_access helper."""

    @staticmethod
    def _check(**kwargs):
        from initrunner.triggers.slack import _check_slack_access

        defaults = {
            "is_dm": False,
            "user_id": "U100",
            "channel_id": "C999",
            "allowed_channels": set(),
            "allowed_user_ids": set(),
        }
        defaults.update(kwargs)
        return _check_slack_access(**defaults)  # type: ignore[invalid-argument-type]

    def test_allows_all_when_no_filters(self):
        assert self._check() is True

    def test_user_id_allows_matching(self):
        assert self._check(allowed_user_ids={"U100"}) is True

    def test_user_id_rejects_wrong(self):
        assert self._check(allowed_user_ids={"U999"}, user_id="U100") is False

    def test_channel_allows_matching_guild(self):
        assert self._check(allowed_channels={"C999"}, channel_id="C999") is True

    def test_channel_rejects_wrong_guild(self):
        assert self._check(allowed_channels={"C999"}, channel_id="C888") is False

    def test_channel_filter_skipped_for_dm(self):
        assert self._check(is_dm=True, allowed_channels={"C999"}, channel_id="C888") is True

    def test_user_id_still_checked_in_dm(self):
        assert self._check(is_dm=True, allowed_user_ids={"U1"}, user_id="U2") is False


class TestSlackAdapterSend:
    """Tests for SlackAdapter.send() / _send_threaded()."""

    @staticmethod
    def _adapter_ready():
        from initrunner.triggers.slack import SlackAdapter

        adapter = SlackAdapter(SlackTriggerConfig())
        adapter._web_client = MagicMock()
        adapter._ready.set()
        return adapter

    def test_send_noop_before_start(self):
        from initrunner.triggers.slack import SlackAdapter

        adapter = SlackAdapter(SlackTriggerConfig())
        adapter.send("C123", "hello")  # no web client, no crash

    def test_send_delegates_to_web_client(self):
        adapter = self._adapter_ready()
        adapter.send("C123", "hello")
        adapter._web_client.chat_postMessage.assert_called_once_with(channel="C123", text="hello")

    def test_send_public_api_never_passes_thread_ts(self):
        """Public send() must not include thread_ts (ABC contract: target is opaque)."""
        adapter = self._adapter_ready()
        adapter.send("C123", "hi")
        call_kwargs = adapter._web_client.chat_postMessage.call_args.kwargs
        assert "thread_ts" not in call_kwargs

    def test_send_threaded_includes_thread_ts(self):
        adapter = self._adapter_ready()
        adapter._send_threaded("C123", "1700.0001", "reply")
        adapter._web_client.chat_postMessage.assert_called_once_with(
            channel="C123", text="reply", thread_ts="1700.0001"
        )

    def test_send_threaded_omits_thread_ts_when_none(self):
        adapter = self._adapter_ready()
        adapter._send_threaded("C123", None, "top-level")
        call_kwargs = adapter._web_client.chat_postMessage.call_args.kwargs
        assert "thread_ts" not in call_kwargs

    def test_send_chunks_long_messages(self):
        adapter = self._adapter_ready()
        big = "a" * 7000  # > 3000 limit, should chunk
        adapter.send("C123", big)
        assert adapter._web_client.chat_postMessage.call_count == 3

    def test_send_never_raises_on_slack_error(self):
        adapter = self._adapter_ready()
        adapter._web_client.chat_postMessage.side_effect = RuntimeError("api down")
        adapter.send("C123", "hi")  # must not raise


class TestSlackEventRouting:
    """Tests for SlackAdapter Socket Mode listener envelope handling."""

    @staticmethod
    def _run_listener(
        config,
        payload,
        *,
        req_type="events_api",
        bot_user_id="UBOT",
        expect_ack=True,
    ):
        """Build a minimal adapter, invoke the listener, return captured events."""
        from concurrent.futures import ThreadPoolExecutor

        from initrunner._text import safe_substitute
        from initrunner.triggers.base import TriggerEvent
        from initrunner.triggers.slack import _MENTION_RE, _check_slack_access

        events: list[TriggerEvent] = []
        allowed_channels = set(config.channel_ids)
        allowed_user_ids = set(config.allowed_user_ids)
        respond_in_thread = config.respond_in_thread
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="slack-test")
        acks: list[object] = []

        def listener(client, req):
            client.send_socket_mode_response(req.envelope_id)  # captured
            if req.type != "events_api":
                return
            if req.payload.get("type") != "event_callback":
                return
            event = req.payload.get("event") or {}
            event_type = event.get("type")
            if event_type not in ("app_mention", "message"):
                return
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
            if event_type == "message" and not is_dm:
                return
            if not _check_slack_access(
                is_dm=is_dm,
                user_id=user_id,
                channel_id=channel_id,
                allowed_channels=allowed_channels,
                allowed_user_ids=allowed_user_ids,
            ):
                return
            thread_ts = event.get("thread_ts")
            event_ts = event.get("ts")
            if thread_ts:
                channel_target = f"{channel_id}:{thread_ts}"
            elif not is_dm and respond_in_thread and event_ts:
                channel_target = f"{channel_id}:{event_ts}"
            else:
                channel_target = channel_id
            text = _MENTION_RE.sub("", event.get("text") or "").strip()
            prompt = safe_substitute(config.prompt_template, {"message": text})
            events.append(
                TriggerEvent(
                    trigger_type="slack",
                    prompt=prompt,
                    metadata={
                        "channel_target": channel_target,
                        "user": user_id,
                        "user_id": user_id,
                        "channel_id": channel_id,
                        "thread_ts": thread_ts or "",
                    },
                    principal_id=f"slack:{user_id}",
                )
            )

        mock_req = MagicMock()
        mock_req.type = req_type
        mock_req.payload = payload
        mock_req.envelope_id = "env-1"
        mock_client = MagicMock()
        mock_client.send_socket_mode_response = lambda env_id: acks.append(env_id)

        listener(mock_client, mock_req)
        executor.shutdown(wait=True)
        if expect_ack:
            assert acks == ["env-1"]
        return events

    def test_app_mention_dispatches_event(self):
        cfg = SlackTriggerConfig()
        payload = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "user": "U100",
                "channel": "C999",
                "text": "<@UBOT> hello",
                "ts": "1700.0001",
            },
        }
        events = self._run_listener(cfg, payload)
        assert len(events) == 1
        assert events[0].prompt == "hello"
        assert events[0].principal_id == "slack:U100"
        assert events[0].metadata["channel_target"] == "C999:1700.0001"

    def test_dm_message_dispatches_event(self):
        cfg = SlackTriggerConfig()
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U100",
                "channel": "D999",
                "channel_type": "im",
                "text": "yo",
                "ts": "1700.0002",
            },
        }
        events = self._run_listener(cfg, payload)
        assert len(events) == 1
        assert events[0].metadata["channel_target"] == "D999"  # DM, no thread

    def test_in_thread_message_encodes_thread_in_target(self):
        cfg = SlackTriggerConfig()
        payload = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "user": "U100",
                "channel": "C999",
                "text": "follow-up",
                "ts": "1700.0010",
                "thread_ts": "1700.0001",
            },
        }
        events = self._run_listener(cfg, payload)
        assert events[0].metadata["channel_target"] == "C999:1700.0001"

    def test_non_events_api_envelope_ignored(self):
        cfg = SlackTriggerConfig()
        events = self._run_listener(cfg, {}, req_type="slash_commands")
        assert events == []

    def test_non_event_callback_payload_ignored(self):
        cfg = SlackTriggerConfig()
        events = self._run_listener(cfg, {"type": "url_verification"})
        assert events == []

    def test_bot_message_dropped(self):
        cfg = SlackTriggerConfig()
        payload = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "user": "UBOT",  # matches bot_user_id
                "channel": "C999",
                "text": "loop",
                "ts": "1700.0003",
            },
        }
        events = self._run_listener(cfg, payload)
        assert events == []

    def test_bot_id_flag_dropped(self):
        cfg = SlackTriggerConfig()
        payload = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "user": "U100",
                "bot_id": "B1",
                "channel": "C999",
                "text": "loop",
                "ts": "1700.0004",
            },
        }
        events = self._run_listener(cfg, payload)
        assert events == []

    def test_edited_message_dropped(self):
        cfg = SlackTriggerConfig()
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "subtype": "message_changed",
                "user": "U100",
                "channel": "D999",
                "channel_type": "im",
                "text": "edit",
                "ts": "1700.0005",
            },
        }
        events = self._run_listener(cfg, payload)
        assert events == []

    def test_non_dm_message_event_dropped(self):
        """Raw `message` events only accepted for DMs; channel messages go through app_mention."""
        cfg = SlackTriggerConfig()
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U100",
                "channel": "C999",
                "channel_type": "channel",
                "text": "noise",
                "ts": "1700.0006",
            },
        }
        events = self._run_listener(cfg, payload)
        assert events == []

    def test_channel_filter_applied(self):
        cfg = SlackTriggerConfig(channel_ids=["C111"])
        payload = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "user": "U100",
                "channel": "C999",
                "text": "<@UBOT> hi",
                "ts": "1700.0007",
            },
        }
        events = self._run_listener(cfg, payload)
        assert events == []

    def test_user_filter_applied(self):
        cfg = SlackTriggerConfig(allowed_user_ids=["U1"])
        payload = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "user": "U100",
                "channel": "C999",
                "text": "<@UBOT> hi",
                "ts": "1700.0008",
            },
        }
        events = self._run_listener(cfg, payload)
        assert events == []

    def test_respond_in_thread_false_keeps_plain_channel_target(self):
        cfg = SlackTriggerConfig(respond_in_thread=False)
        payload = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "user": "U100",
                "channel": "C999",
                "text": "<@UBOT> hi",
                "ts": "1700.0009",
            },
        }
        events = self._run_listener(cfg, payload)
        assert events[0].metadata["channel_target"] == "C999"
