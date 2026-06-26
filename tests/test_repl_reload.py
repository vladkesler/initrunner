"""Tests for the REPL AgentHandle hot-reload/hot-attach primitive."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.runner import single
from initrunner.runner.interactive import _attach_tool
from initrunner.runner.reload import _CARRYOVER_ATTRS, AgentHandle, ReloadResult
from tests.conftest import make_role


def _agent_with_attrs(**attrs) -> MagicMock:
    agent = MagicMock()
    for name, value in attrs.items():
        setattr(agent, name, value)
    return agent


class TestRebuildFromRole:
    def test_swaps_agent_and_role(self):
        old_agent = MagicMock(name="old")
        new_agent = MagicMock(name="new")
        old_role = make_role(name="before")
        new_role = make_role(name="after")
        handle = AgentHandle(old_agent, old_role, role_dir=None)

        with patch("initrunner.agent.loader.build_agent", return_value=new_agent) as bld:
            result = handle.rebuild_from_role(new_role)

        bld.assert_called_once()
        assert result.ok is True
        assert result.agent is new_agent
        agent, role = handle.current()
        assert agent is new_agent
        assert role is new_role

    def test_fail_open_keeps_current_agent(self):
        old_agent = MagicMock(name="old")
        old_role = make_role(name="before")
        new_role = make_role(name="after")
        handle = AgentHandle(old_agent, old_role, role_dir=None)

        with patch(
            "initrunner.agent.loader.build_agent",
            side_effect=RuntimeError("boom"),
        ):
            result = handle.rebuild_from_role(new_role)

        assert result.ok is False
        assert "boom" in (result.error or "")
        agent, role = handle.current()
        assert agent is old_agent  # unchanged
        assert role is old_role

    def test_carries_runtime_attrs_onto_new_agent(self):
        store = object()
        old_agent = _agent_with_attrs(
            _template_values={"k": "v"},
            _memory_store=store,
            _resume_context="prior context",
        )
        # A fresh mock would auto-create any attribute, so use a real object
        # for the new agent to prove the values are actually copied across.
        new_agent = type("A", (), {})()
        handle = AgentHandle(old_agent, make_role(), role_dir=None)

        with patch("initrunner.agent.loader.build_agent", return_value=new_agent):
            handle.rebuild_from_role(make_role(name="after"))

        for attr in _CARRYOVER_ATTRS:
            assert hasattr(new_agent, attr)
        assert new_agent._template_values == {"k": "v"}
        assert new_agent._memory_store is store
        assert new_agent._resume_context == "prior context"


class TestReloadFromDisk:
    def test_no_role_path_is_not_supported(self):
        handle = AgentHandle(MagicMock(), make_role(), role_dir=None, role_path=None)
        result = handle.reload_from_disk()
        assert isinstance(result, ReloadResult)
        assert result.ok is False
        assert result.error is None
        assert "ephemeral" in result.summary.lower()

    def test_reload_swaps_from_disk(self):
        new_agent = MagicMock(name="new")
        new_role = make_role(name="reloaded")
        handle = AgentHandle(
            MagicMock(), make_role(), role_dir=Path("/x"), role_path=Path("/x/role.yaml")
        )

        with patch(
            "initrunner.agent.loader.load_and_build",
            return_value=(new_role, new_agent),
        ) as lab:
            result = handle.reload_from_disk()

        lab.assert_called_once()
        assert result.ok is True
        agent, role = handle.current()
        assert agent is new_agent
        assert role is new_role

    def test_reload_fail_open(self):
        old_agent = MagicMock(name="old")
        old_role = make_role(name="before")
        handle = AgentHandle(
            old_agent, old_role, role_dir=Path("/x"), role_path=Path("/x/role.yaml")
        )

        with patch(
            "initrunner.agent.loader.load_and_build",
            side_effect=ValueError("bad yaml"),
        ):
            result = handle.reload_from_disk()

        assert result.ok is False
        assert "bad yaml" in (result.error or "")
        agent, role = handle.current()
        assert agent is old_agent
        assert role is old_role


class TestAttachTool:
    def test_appends_custom_config_and_rebuilds(self, tmp_path):
        handle = AgentHandle(MagicMock(), make_role(), role_dir=tmp_path)
        with patch("initrunner.agent.loader.build_agent", return_value=MagicMock()):
            result = _attach_tool(handle, "mymod")

        assert result.ok is True
        _agent, role = handle.current()
        customs = [t for t in role.spec.tools if getattr(t, "type", None) == "custom"]
        assert [t.module for t in customs] == ["mymod"]

    def test_reattach_replaces_not_duplicates(self, tmp_path):
        handle = AgentHandle(MagicMock(), make_role(), role_dir=tmp_path)
        with patch("initrunner.agent.loader.build_agent", return_value=MagicMock()):
            _attach_tool(handle, "mymod")
            _attach_tool(handle, "mymod")

        _agent, role = handle.current()
        mymods = [t for t in role.spec.tools if getattr(t, "module", None) == "mymod"]
        assert len(mymods) == 1


class TestDevQuietMode:
    def test_run_single_skips_spinner_when_show_thinking_false(self):
        result = MagicMock(status="ok", success=True)
        with (
            patch.object(single.console, "status") as status,
            patch("initrunner.runner.single.execute_run", return_value=(result, [])),
            patch("initrunner.runner.single._display_result"),
        ):
            single.run_single(MagicMock(), make_role(), "hi", show_thinking=False)
        status.assert_not_called()

    def test_run_single_shows_spinner_by_default(self):
        result = MagicMock(status="ok", success=True)
        with (
            patch.object(single.console, "status") as status,
            patch("initrunner.runner.single.execute_run", return_value=(result, [])),
            patch("initrunner.runner.single._display_result"),
        ):
            single.run_single(MagicMock(), make_role(), "hi")
        status.assert_called_once()
