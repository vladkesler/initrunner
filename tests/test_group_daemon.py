"""Running a group's trigger-driven agents in one process."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import ClassVar
from unittest.mock import MagicMock, patch

from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.agent.schema.triggers import CronTriggerConfig
from initrunner.group.daemon import run_group_daemon
from initrunner.group.prepare import PreparedMember
from initrunner.group.schema import GroupDefinition, Roster, RosterMember


def _role(name: str, *, triggers: bool) -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name=name),
        spec=AgentSpec(
            role="You are a test.",
            model=ModelConfig(provider="openai", name="gpt-5-mini"),
            triggers=([CronTriggerConfig(schedule="0 * * * *", prompt="tick")] if triggers else []),
        ),
    )


def _roster(tmp_path: Path, members: dict[str, bool]) -> tuple[Roster, dict]:
    from initrunner.agent.schema.security import SecurityPolicy
    from initrunner.flow.schema import SharedMemoryConfig
    from initrunner.team.schema import TeamDocumentsConfig

    group = GroupDefinition(
        name="desk",
        members={},
        shared_memory=SharedMemoryConfig(),
        shared_documents=TeamDocumentsConfig(),
        security=SecurityPolicy(),
        source_path=tmp_path / "desk.yaml",
    )
    roster = Roster(group=group)
    prepared = {}
    for key, has_triggers in members.items():
        role = _role(key, triggers=has_triggers)
        path = tmp_path / f"{key}.yaml"
        roster.members[key] = RosterMember(key=key, path=path, role_dir=tmp_path, role=role)
        prepared[key] = PreparedMember(
            key=key, path=path, role_dir=tmp_path, role=role, agent=MagicMock()
        )
    return roster, prepared


class _FakeRunner:
    """Stands in for DaemonRunner: records construction and blocks on the stop event."""

    instances: ClassVar[list[_FakeRunner]] = []

    def __init__(self, agent, role, **kwargs):
        self.role = role
        self.kwargs = kwargs
        self.ran = False
        _FakeRunner.instances.append(self)

    def run(self) -> None:
        self.ran = True
        self.kwargs["stop_event"].wait(timeout=5)

    def _on_first_signal(self) -> None:
        pass


def _run_group(roster, prepared, stop_after: float = 0.2):
    _FakeRunner.instances = []
    with (
        patch("initrunner.runner.daemon.DaemonRunner", _FakeRunner),
        patch("initrunner.group.daemon.install_shutdown_handler", create=True),
        patch("initrunner._signal.install_shutdown_handler") as mock_signal,
    ):
        stopper = threading.Timer(
            stop_after,
            lambda: mock_signal.call_args.args[0].set() if mock_signal.call_args else None,
        )
        stopper.start()
        run_group_daemon(roster, prepared)
        stopper.cancel()
    return _FakeRunner.instances


def test_only_triggered_members_get_runners(tmp_path: Path, capsys) -> None:
    roster, prepared = _roster(tmp_path, {"intake": True, "writer": False})

    runners = _run_group(roster, prepared)

    assert [r.role.metadata.name for r in runners] == ["intake"]
    assert "writer" in capsys.readouterr().out


def test_runners_share_one_stop_event_and_install_no_handlers(tmp_path: Path) -> None:
    """Signal handlers install on the main thread only, so the parent owns them."""
    roster, prepared = _roster(tmp_path, {"intake": True, "writer": True})

    runners = _run_group(roster, prepared)

    assert len(runners) == 2
    stop_events = {id(r.kwargs["stop_event"]) for r in runners}
    assert len(stop_events) == 1
    assert all(r.kwargs["install_signal_handler"] is False for r in runners)
    assert all(r.kwargs["label"] for r in runners)


def test_no_triggers_anywhere_is_an_error(tmp_path: Path, capsys) -> None:
    roster, prepared = _roster(tmp_path, {"intake": False, "writer": False})

    runners = _run_group(roster, prepared)

    assert runners == []
    out = " ".join(capsys.readouterr().out.split())
    assert "no agent in group 'desk' has triggers" in out


def test_reload_keeps_group_settings(tmp_path: Path) -> None:
    """A hot reload rebuilds through the group, so shared stores survive."""
    roster, prepared = _roster(tmp_path, {"intake": True})

    runners = _run_group(roster, prepared)

    rebuild = runners[0].kwargs["rebuild"]
    with patch("initrunner.agent.loader.load_and_build") as mock_build:
        mock_build.return_value = (MagicMock(), MagicMock())
        rebuild(tmp_path / "intake.yaml")

    assert mock_build.call_args.kwargs["role_mutator"] is not None
