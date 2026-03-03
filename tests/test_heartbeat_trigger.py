"""Tests for the heartbeat trigger."""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from initrunner.agent.schema.triggers import HeartbeatTriggerConfig
from initrunner.triggers.base import TriggerEvent
from initrunner.triggers.heartbeat import (
    HeartbeatTrigger,
    _build_prompt,
    _count_open_items,
)

# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestHeartbeatSchema:
    def test_defaults(self):
        config = HeartbeatTriggerConfig(file="tasks.md")
        assert config.type == "heartbeat"
        assert config.interval_seconds == 3600
        assert config.active_hours is None
        assert config.timezone == "UTC"
        assert config.autonomous is False

    def test_interval_gt_0(self):
        with pytest.raises(ValidationError):
            HeartbeatTriggerConfig(file="tasks.md", interval_seconds=0)

    def test_negative_interval_rejected(self):
        with pytest.raises(ValidationError):
            HeartbeatTriggerConfig(file="tasks.md", interval_seconds=-1)

    def test_active_hours_must_be_two_elements(self):
        with pytest.raises(ValidationError, match="exactly 2"):
            HeartbeatTriggerConfig(file="tasks.md", active_hours=[9])

    def test_active_hours_three_elements_rejected(self):
        with pytest.raises(ValidationError, match="exactly 2"):
            HeartbeatTriggerConfig(file="tasks.md", active_hours=[9, 12, 17])

    def test_active_hours_out_of_range(self):
        with pytest.raises(ValidationError, match="0-23"):
            HeartbeatTriggerConfig(file="tasks.md", active_hours=[25, 6])

    def test_active_hours_valid(self):
        config = HeartbeatTriggerConfig(file="tasks.md", active_hours=[9, 17])
        assert config.active_hours == [9, 17]

    def test_active_hours_midnight_spanning(self):
        config = HeartbeatTriggerConfig(file="tasks.md", active_hours=[22, 6])
        assert config.active_hours == [22, 6]

    def test_invalid_timezone_rejected(self):
        with pytest.raises(ValidationError, match="Invalid timezone"):
            HeartbeatTriggerConfig(file="tasks.md", timezone="Not/A/Timezone")

    def test_valid_timezone(self):
        config = HeartbeatTriggerConfig(file="tasks.md", timezone="America/New_York")
        assert config.timezone == "America/New_York"

    def test_summary(self):
        config = HeartbeatTriggerConfig(file="tasks.md", interval_seconds=600)
        assert "tasks.md" in config.summary()
        assert "600" in config.summary()


# ---------------------------------------------------------------------------
# Active-hours logic
# ---------------------------------------------------------------------------


class TestIsActive:
    def _trigger(self, *, active_hours=None, timezone="UTC"):
        config = HeartbeatTriggerConfig(
            file="tasks.md", active_hours=active_hours, timezone=timezone
        )
        return HeartbeatTrigger(config, lambda e: None)

    def test_always_active_when_none(self):
        trigger = self._trigger()
        now = datetime(2026, 1, 15, 14, 0, tzinfo=ZoneInfo("UTC"))
        assert trigger._is_active(now) is True

    def test_normal_window_inside(self):
        trigger = self._trigger(active_hours=[9, 17])
        now = datetime(2026, 1, 15, 12, 0, tzinfo=ZoneInfo("UTC"))
        assert trigger._is_active(now) is True

    def test_normal_window_outside_before(self):
        trigger = self._trigger(active_hours=[9, 17])
        now = datetime(2026, 1, 15, 7, 0, tzinfo=ZoneInfo("UTC"))
        assert trigger._is_active(now) is False

    def test_normal_window_outside_after(self):
        trigger = self._trigger(active_hours=[9, 17])
        now = datetime(2026, 1, 15, 18, 0, tzinfo=ZoneInfo("UTC"))
        assert trigger._is_active(now) is False

    def test_normal_window_at_start(self):
        trigger = self._trigger(active_hours=[9, 17])
        now = datetime(2026, 1, 15, 9, 0, tzinfo=ZoneInfo("UTC"))
        assert trigger._is_active(now) is True

    def test_normal_window_at_end(self):
        trigger = self._trigger(active_hours=[9, 17])
        now = datetime(2026, 1, 15, 17, 0, tzinfo=ZoneInfo("UTC"))
        assert trigger._is_active(now) is False

    def test_midnight_spanning_late_night(self):
        trigger = self._trigger(active_hours=[22, 6])
        now = datetime(2026, 1, 15, 23, 0, tzinfo=ZoneInfo("UTC"))
        assert trigger._is_active(now) is True

    def test_midnight_spanning_early_morning(self):
        trigger = self._trigger(active_hours=[22, 6])
        now = datetime(2026, 1, 15, 3, 0, tzinfo=ZoneInfo("UTC"))
        assert trigger._is_active(now) is True

    def test_midnight_spanning_afternoon(self):
        trigger = self._trigger(active_hours=[22, 6])
        now = datetime(2026, 1, 15, 14, 0, tzinfo=ZoneInfo("UTC"))
        assert trigger._is_active(now) is False


# ---------------------------------------------------------------------------
# File reading and checklist helpers
# ---------------------------------------------------------------------------


class TestReadChecklist:
    def test_reads_file(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [ ] Do something\n- [x] Done\n- [ ] Another\n")
        config = HeartbeatTriggerConfig(file=str(f))
        trigger = HeartbeatTrigger(config, lambda e: None)
        content = trigger._read_checklist()
        assert content is not None
        assert "Do something" in content

    def test_missing_file_returns_none(self, tmp_path):
        config = HeartbeatTriggerConfig(file=str(tmp_path / "missing.md"))
        trigger = HeartbeatTrigger(config, lambda e: None)
        assert trigger._read_checklist() is None

    def test_truncation_at_64kb(self, tmp_path):
        f = tmp_path / "big.md"
        f.write_text("x" * 70000)
        config = HeartbeatTriggerConfig(file=str(f))
        trigger = HeartbeatTrigger(config, lambda e: None)
        content = trigger._read_checklist()
        assert content is not None
        assert content.endswith("[truncated]")
        assert len(content) <= 64 * 1024 + 20  # 64KB + marker


class TestCountOpenItems:
    def test_counts_open_items(self):
        content = "- [ ] Task 1\n- [x] Task 2\n- [ ] Task 3\n"
        assert _count_open_items(content) == 2

    def test_no_open_items(self):
        content = "- [x] Task 1\n- [x] Task 2\n"
        assert _count_open_items(content) == 0

    def test_empty_content(self):
        assert _count_open_items("") == 0

    def test_mixed_markdown(self):
        content = "# Tasks\n\n- [ ] First\n- [x] Second\nSome text\n- [ ] Third\n"
        assert _count_open_items(content) == 2


class TestBuildPrompt:
    def test_prompt_composition(self):
        prefix = "Process these tasks:"
        content = "- [ ] Task 1\n- [ ] Task 2\n"
        result = _build_prompt(prefix, content)
        assert result.startswith("Process these tasks:")
        assert "- [ ] Task 1" in result
        assert "\n\n" in result


# ---------------------------------------------------------------------------
# Dispatcher integration
# ---------------------------------------------------------------------------


class TestDispatcherBuildsHeartbeat:
    def test_builds_heartbeat(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [ ] test")
        config = HeartbeatTriggerConfig(file=str(f))
        from initrunner.triggers.dispatcher import TriggerDispatcher

        dispatcher = TriggerDispatcher([config], lambda e: None)
        assert dispatcher.count == 1


# ---------------------------------------------------------------------------
# Discriminated union deserialization
# ---------------------------------------------------------------------------


class TestDiscriminatedUnion:
    def test_heartbeat_from_dict(self):
        from pydantic import TypeAdapter

        from initrunner.agent.schema.triggers import TriggerConfig

        ta = TypeAdapter(TriggerConfig)
        config = ta.validate_python(
            {"type": "heartbeat", "file": "tasks.md", "interval_seconds": 300}
        )
        assert isinstance(config, HeartbeatTriggerConfig)
        assert config.interval_seconds == 300
        assert config.file == "tasks.md"


# ---------------------------------------------------------------------------
# Trigger lifecycle
# ---------------------------------------------------------------------------


class TestHeartbeatTriggerLifecycle:
    def test_start_and_stop(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [ ] test task\n")
        config = HeartbeatTriggerConfig(file=str(f), interval_seconds=1)
        events: list[TriggerEvent] = []
        trigger = HeartbeatTrigger(config, events.append)
        trigger.start()
        time.sleep(2.5)
        trigger.stop()
        assert len(events) >= 1
        assert events[0].trigger_type == "heartbeat"
        assert events[0].metadata["file"] == str(f)
        assert events[0].metadata["item_count"] == "1"

    def test_no_fire_when_no_open_items(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [x] done\n- [x] also done\n")
        config = HeartbeatTriggerConfig(file=str(f), interval_seconds=1)
        events: list[TriggerEvent] = []
        trigger = HeartbeatTrigger(config, events.append)
        trigger.start()
        time.sleep(2.5)
        trigger.stop()
        assert len(events) == 0
