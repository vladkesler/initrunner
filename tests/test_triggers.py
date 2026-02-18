"""Tests for the trigger system."""

import time

from initrunner.agent.schema.triggers import CronTriggerConfig, FileWatchTriggerConfig
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
