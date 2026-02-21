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
