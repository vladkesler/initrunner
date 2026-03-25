"""Tests for config hot-reload in daemon mode."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.role import AgentSpec, DaemonConfig, RoleDefinition
from initrunner.agent.schema.triggers import CronTriggerConfig
from initrunner.runner.daemon import DaemonRunner, _triggers_key
from initrunner.runner.hot_reload import RoleReloader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_role(
    *,
    triggers=None,
    hot_reload: bool = True,
    reload_debounce: float = 0.2,
) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test agent.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            triggers=triggers or [],
            daemon=DaemonConfig(
                hot_reload=hot_reload,
                reload_debounce_seconds=reload_debounce,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# DaemonConfig schema
# ---------------------------------------------------------------------------


class TestDaemonConfig:
    def test_defaults(self):
        config = DaemonConfig()
        assert config.hot_reload is True
        assert config.reload_debounce_seconds == 1.0

    def test_custom_values(self):
        config = DaemonConfig(hot_reload=False, reload_debounce_seconds=5.0)
        assert config.hot_reload is False
        assert config.reload_debounce_seconds == 5.0

    def test_debounce_range(self):
        with pytest.raises(ValidationError):
            DaemonConfig(reload_debounce_seconds=-1.0)
        with pytest.raises(ValidationError):
            DaemonConfig(reload_debounce_seconds=31.0)

    def test_daemon_on_agent_spec(self):
        role = _make_role()
        assert role.spec.daemon.hot_reload is True


# ---------------------------------------------------------------------------
# RoleReloader
# ---------------------------------------------------------------------------


class TestRoleReloader:
    def test_fires_callback_on_change(self, tmp_path):
        watched = tmp_path / "role.yaml"
        watched.write_text("version: 1")

        calls: list[Path] = []

        def on_reload(path):
            calls.append(path)

        reloader = RoleReloader(
            [watched],
            on_reload,
            role_path=watched,
            debounce_ms=100,
        )
        reloader.start()
        time.sleep(0.5)

        # Modify file
        watched.write_text("version: 2")
        time.sleep(2.0)

        reloader.stop()
        assert len(calls) >= 1
        assert calls[0] == watched

    def test_stops_cleanly(self, tmp_path):
        watched = tmp_path / "role.yaml"
        watched.write_text("version: 1")

        reloader = RoleReloader(
            [watched],
            lambda p: None,
            role_path=watched,
            debounce_ms=100,
        )
        reloader.start()
        time.sleep(0.3)
        reloader.stop()
        # No hang, no error

    def test_callback_exception_does_not_crash(self, tmp_path):
        watched = tmp_path / "role.yaml"
        watched.write_text("version: 1")

        def bad_callback(path):
            raise RuntimeError("reload failed!")

        reloader = RoleReloader(
            [watched],
            bad_callback,
            role_path=watched,
            debounce_ms=100,
        )
        reloader.start()
        time.sleep(0.5)
        watched.write_text("version: 2")
        time.sleep(2.0)
        reloader.stop()
        # Should not crash — fail-open

    def test_set_watched_paths(self, tmp_path):
        watched = tmp_path / "role.yaml"
        watched.write_text("version: 1")

        reloader = RoleReloader(
            [watched],
            lambda p: None,
            role_path=watched,
            debounce_ms=100,
        )
        new_path = tmp_path / "skill.md"
        new_path.write_text("# skill")
        reloader.set_watched_paths([watched, new_path])
        assert len(reloader._paths) == 2


# ---------------------------------------------------------------------------
# _triggers_key
# ---------------------------------------------------------------------------


class TestTriggersKey:
    def test_same_triggers_same_key(self):
        t1 = [CronTriggerConfig(schedule="* * * * *", prompt="test")]
        t2 = [CronTriggerConfig(schedule="* * * * *", prompt="test")]
        assert _triggers_key(t1) == _triggers_key(t2)

    def test_different_triggers_different_key(self):
        t1 = [CronTriggerConfig(schedule="* * * * *", prompt="test")]
        t2 = [CronTriggerConfig(schedule="0 * * * *", prompt="test")]
        assert _triggers_key(t1) != _triggers_key(t2)

    def test_empty_triggers(self):
        assert _triggers_key([]) == "[]"


# ---------------------------------------------------------------------------
# DaemonRunner reload logic
# ---------------------------------------------------------------------------


class TestDaemonRunnerReload:
    def test_apply_reload_success_swaps_role_and_agent(self, tmp_path):
        """Successful reload atomically swaps role and agent."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text("placeholder")

        old_role = _make_role(triggers=[CronTriggerConfig(schedule="* * * * *", prompt="old")])
        old_agent = MagicMock()
        new_role = _make_role(triggers=[CronTriggerConfig(schedule="* * * * *", prompt="new")])
        new_agent = MagicMock()

        runner = DaemonRunner(
            old_agent,
            old_role,
            role_path=role_file,
        )
        # Initialise dispatcher to avoid AttributeError
        runner._dispatcher = MagicMock()

        with patch(
            "initrunner.agent.loader.load_and_build",
            return_value=(new_role, new_agent),
        ):
            runner._apply_reload(role_file)

        assert runner._role is new_role
        assert runner._agent is new_agent

    def test_apply_reload_failure_keeps_old_config(self, tmp_path):
        """If load_and_build fails, the old role/agent remain."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text("placeholder")

        old_role = _make_role(triggers=[CronTriggerConfig(schedule="* * * * *", prompt="old")])
        old_agent = MagicMock()

        runner = DaemonRunner(old_agent, old_role, role_path=role_file)
        runner._dispatcher = MagicMock()

        with patch(
            "initrunner.agent.loader.load_and_build",
            side_effect=RuntimeError("bad yaml"),
        ):
            runner._apply_reload(role_file)

        assert runner._role is old_role
        assert runner._agent is old_agent

    def test_triggers_restart_only_when_changed(self, tmp_path):
        """Dispatcher is only restarted when trigger config actually changes."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text("placeholder")

        triggers = [CronTriggerConfig(schedule="* * * * *", prompt="test")]
        old_role = _make_role(triggers=triggers)
        new_role = _make_role(triggers=triggers)  # Same triggers
        old_agent = MagicMock()
        new_agent = MagicMock()

        runner = DaemonRunner(old_agent, old_role, role_path=role_file)
        runner._dispatcher = MagicMock()

        with patch(
            "initrunner.agent.loader.load_and_build",
            return_value=(new_role, new_agent),
        ):
            runner._apply_reload(role_file)

        # Dispatcher should NOT have been restarted
        runner._dispatcher.stop_all.assert_not_called()

    def test_triggers_restart_when_changed(self, tmp_path):
        """Dispatcher is restarted when trigger config changes."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text("placeholder")

        old_triggers = [CronTriggerConfig(schedule="* * * * *", prompt="old")]
        new_triggers = [CronTriggerConfig(schedule="0 * * * *", prompt="new")]
        old_role = _make_role(triggers=old_triggers)
        new_role = _make_role(triggers=new_triggers)

        runner = DaemonRunner(MagicMock(), old_role, role_path=role_file)
        old_dispatcher = MagicMock()
        runner._dispatcher = old_dispatcher

        with (
            patch(
                "initrunner.agent.loader.load_and_build",
                return_value=(new_role, MagicMock()),
            ),
            patch("initrunner.triggers.dispatcher.TriggerDispatcher"),
        ):
            runner._apply_reload(role_file)

        # Old dispatcher should have been stopped
        old_dispatcher.stop_all.assert_called_once()

    def test_autonomous_trigger_types_recomputed(self, tmp_path):
        """Autonomous trigger types are recomputed on reload."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text("placeholder")

        old_role = _make_role(
            triggers=[CronTriggerConfig(schedule="* * * * *", prompt="t", autonomous=False)]
        )
        new_role = _make_role(
            triggers=[CronTriggerConfig(schedule="* * * * *", prompt="t", autonomous=True)]
        )

        runner = DaemonRunner(MagicMock(), old_role, role_path=role_file)
        runner._dispatcher = MagicMock()
        assert "cron" not in runner._autonomous_trigger_types

        with patch(
            "initrunner.agent.loader.load_and_build",
            return_value=(new_role, MagicMock()),
        ):
            runner._apply_reload(role_file)

        assert "cron" in runner._autonomous_trigger_types

    def test_in_flight_uses_old_refs(self, tmp_path):
        """In-flight trigger runs use snapshot of old agent/role."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text("placeholder")

        old_role = _make_role(triggers=[CronTriggerConfig(schedule="* * * * *", prompt="t")])
        old_agent = MagicMock(name="old-agent")
        new_role = _make_role(triggers=[CronTriggerConfig(schedule="* * * * *", prompt="t")])
        new_agent = MagicMock(name="new-agent")

        runner = DaemonRunner(old_agent, old_role, role_path=role_file)
        runner._dispatcher = MagicMock()

        # Capture agent ref when _on_trigger_inner runs
        captured_agents: list = []

        def capture_inner(event):
            with runner._agent_role_lock:
                captured_agents.append(runner._agent)
            # Don't actually run the event (would need mock executor)

        runner._on_trigger_inner = capture_inner  # type: ignore[assignment]

        from initrunner.triggers.base import TriggerEvent

        # Simulate: trigger fires, then reload happens
        event = TriggerEvent(trigger_type="cron", prompt="test")
        runner._on_trigger(event)

        # Now reload
        with patch(
            "initrunner.agent.loader.load_and_build",
            return_value=(new_role, new_agent),
        ):
            runner._apply_reload(role_file)

        # Trigger again — should see new agent
        runner._on_trigger(event)

        assert captured_agents[0] is old_agent
        assert captured_agents[1] is new_agent


# ---------------------------------------------------------------------------
# run_daemon signature
# ---------------------------------------------------------------------------


class TestRunDaemonSignature:
    def test_run_daemon_accepts_new_params(self):
        """run_daemon accepts role_path and extra_skill_dirs without error."""
        from initrunner.runner.daemon import run_daemon

        role = _make_role(triggers=[CronTriggerConfig(schedule="* * * * *", prompt="test")])
        agent = MagicMock()

        # Patch run() to avoid blocking
        with patch.object(DaemonRunner, "run"):
            run_daemon(
                agent,
                role,
                role_path=Path("/tmp/role.yaml"),
                extra_skill_dirs=[Path("/tmp/skills")],
            )
