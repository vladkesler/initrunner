"""Tests for the trigger system."""

import time

from initrunner.agent.schema.triggers import (
    CronTriggerConfig,
    DiscordTriggerConfig,
    FileWatchTriggerConfig,
    TelegramTriggerConfig,
)
from initrunner.triggers.base import TriggerEvent
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

    def test_conversation_key_telegram(self):
        event = TriggerEvent(
            trigger_type="telegram",
            prompt="hi",
            metadata={"chat_id": "12345"},
        )
        assert event.conversation_key == "telegram:12345"

    def test_conversation_key_discord(self):
        event = TriggerEvent(
            trigger_type="discord",
            prompt="hi",
            metadata={"channel_id": "67890"},
        )
        assert event.conversation_key == "discord:67890"

    def test_conversation_key_cron_returns_none(self):
        event = TriggerEvent(trigger_type="cron", prompt="test")
        assert event.conversation_key is None

    def test_conversation_key_missing_metadata_returns_none(self):
        event = TriggerEvent(trigger_type="telegram", prompt="hi")
        assert event.conversation_key is None

        event2 = TriggerEvent(trigger_type="discord", prompt="hi")
        assert event2.conversation_key is None


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
