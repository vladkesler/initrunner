"""A directory of agent files is a group.

Several agents sitting next to each other, with no ``agent.yaml`` saying which
one the directory is about, is what a group file describes. ``initrunner run``
reads such a directory as a group instead of refusing to choose. Only
top-level files count: nested directories hold the parts other documents are
built from, and a team's personas are not standalone agents.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from initrunner.cli._helpers import resolve_role_path, resolve_run_target
from initrunner.cli.main import app
from initrunner.group.loader import GroupLoadError, load_directory_group, load_roster

runner = CliRunner()

_ROLE = "name: {name}\ndescription: {description}\nprompt: {prompt}\nmodel: openai:gpt-5-mini\n"

_TEAM = (
    "name: review-team\n"
    "model: openai:gpt-5-mini\n"
    "agents:\n"
    "  architect: review the design\n"
    "  security: find vulnerabilities\n"
    "run: sequential\n"
)

_GROUP = "name: desk\nagents:\n  one:\n    use: agents/one.yaml\n"


def _flat(output: str) -> str:
    """Collapse Rich's line wrapping so a phrase can be matched as written."""
    return " ".join(output.split())


def _agent(directory: Path, filename: str, name: str, description: str = "d") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(_ROLE.format(name=name, description=description, prompt=f"be {name}"))
    return path


@pytest.fixture
def desk(tmp_path: Path) -> Path:
    """A directory with three agents and one nested agent that must be ignored."""
    _agent(tmp_path, "intake.yaml", "intake", "Triages incoming tickets")
    _agent(tmp_path, "triage.yaml", "triage", "Sorts tickets by severity")
    _agent(tmp_path, "reply.yaml", "reply", "Writes replies to customers")
    _agent(tmp_path / "personas", "helper.yaml", "helper")
    return tmp_path


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class TestLoadDirectoryGroup:
    def test_members_are_keyed_by_role_name(self, desk: Path) -> None:
        roster = load_directory_group(desk)
        assert sorted(roster.members) == ["intake", "reply", "triage"]

    def test_group_is_named_after_the_directory(self, desk: Path) -> None:
        assert load_directory_group(desk).name == desk.resolve().name

    def test_nested_agents_are_not_members(self, desk: Path) -> None:
        roster = load_directory_group(desk)
        assert "helper" not in roster.members

    def test_relative_directory_gets_a_real_name(self, desk: Path, monkeypatch) -> None:
        """`initrunner run .` must not produce a group called '.'."""
        monkeypatch.chdir(desk)
        assert load_directory_group(Path(".")).name == desk.resolve().name

    def test_members_keep_their_own_directory(self, desk: Path) -> None:
        member = load_directory_group(desk).members["intake"]
        assert member.role_dir == desk
        assert member.path == desk / "intake.yaml"

    def test_every_broken_member_is_reported(self, desk: Path) -> None:
        (desk / "intake.yaml").write_text("name: intake\nmodel: {{{\n")
        (desk / "triage.yaml").write_text("name: triage\nprompt: p\nmodel: 42\n")

        with pytest.raises(GroupLoadError) as exc:
            load_directory_group(desk)

        assert "intake.yaml" in str(exc.value)
        assert "triage.yaml" in str(exc.value)

    def test_unparseable_yaml_is_not_called_an_agent(self, desk: Path) -> None:
        """A file that does not parse cannot be classified, so it is not a member.

        It still fails the group -- an agent hiding in it would otherwise be
        served short one member -- but the error says what it actually is.
        """
        (desk / "values.yaml").write_text("replicas: {{ .Values.count }}\n")

        with pytest.raises(GroupLoadError) as exc:
            load_directory_group(desk)

        message = str(exc.value)
        assert "could not be loaded as a group" in message
        assert "values.yaml: does not parse as YAML" in message
        assert "agents that failed to load" not in message

    def test_duplicate_role_names_name_the_files(self, desk: Path) -> None:
        _agent(desk, "copy.yaml", "intake")

        with pytest.raises(GroupLoadError) as exc:
            load_directory_group(desk)

        message = str(exc.value)
        assert "share a name" in message
        assert "intake.yaml" in message
        assert "copy.yaml" in message

    def test_empty_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(GroupLoadError, match="no agent YAML"):
            load_directory_group(tmp_path)

    def test_load_roster_dispatches_on_directory(self, desk: Path) -> None:
        assert sorted(load_roster(desk).members) == ["intake", "reply", "triage"]

    def test_load_roster_still_reads_a_group_file(self, tmp_path: Path) -> None:
        _agent(tmp_path / "agents", "one.yaml", "one")
        group_file = tmp_path / "desk.yaml"
        group_file.write_text(_GROUP)

        roster = load_roster(group_file)

        assert roster.name == "desk"
        assert sorted(roster.members) == ["one"]

    def test_overlay_is_the_identity(self, desk: Path) -> None:
        """A directory carries no shared stores, so a member runs as it does alone."""
        from initrunner.group.prepare import make_group_overlay

        roster = load_directory_group(desk)
        role = roster.members["intake"].role

        assert make_group_overlay(roster.group)(role) is role
        assert role.spec.memory is None
        assert role.spec.observability is None


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


class TestResolveRunTarget:
    def test_several_agents_make_a_group(self, desk: Path) -> None:
        assert resolve_run_target(desk) == (desk, "Group")

    def test_one_agent_still_resolves_to_that_file(self, tmp_path: Path) -> None:
        path = _agent(tmp_path, "solo.yaml", "solo")
        assert resolve_run_target(tmp_path) == (path, "Agent")

    @pytest.mark.parametrize("marker", ["agent.yaml", "role.yaml"])
    def test_marker_file_wins(self, tmp_path: Path, marker: str) -> None:
        _agent(tmp_path, "other.yaml", "other")
        path = _agent(tmp_path, marker, "the-one")
        assert resolve_run_target(tmp_path) == (path, "Agent")

    def test_a_team_beside_an_agent_is_not_a_group(self, tmp_path: Path) -> None:
        """A team's personas are not standalone agents; refuse to guess."""
        _agent(tmp_path, "solo.yaml", "solo")
        (tmp_path / "team.yaml").write_text(_TEAM)

        with pytest.raises(typer.Exit):
            resolve_run_target(tmp_path)

    def test_a_lone_group_file_is_unchanged(self, tmp_path: Path) -> None:
        _agent(tmp_path / "agents", "one.yaml", "one")
        group_file = tmp_path / "desk.yaml"
        group_file.write_text(_GROUP)

        assert resolve_run_target(tmp_path) == (group_file, "Group")

    def test_only_nested_agents_is_still_an_error(self, tmp_path: Path) -> None:
        _agent(tmp_path / "agents", "one.yaml", "one")
        _agent(tmp_path / "agents", "two.yaml", "two")

        with pytest.raises(typer.Exit):
            resolve_run_target(tmp_path)

    def test_an_explicit_file_is_unchanged(self, desk: Path) -> None:
        assert resolve_run_target(desk / "intake.yaml") == (desk / "intake.yaml", "Agent")

    def test_other_commands_still_refuse_the_directory(self, desk: Path) -> None:
        """Only `run` reads a directory as a group."""
        with pytest.raises(typer.Exit):
            resolve_role_path(desk)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestADirectoryGroupReportsAMissingExtra:
    def test_the_install_hint_keeps_the_extra_name(self, desk: Path, monkeypatch) -> None:
        """Rich reads `initrunner[vector]` as markup; the bare name is useless."""
        import sys

        monkeypatch.setitem(sys.modules, "lancedb", None)
        (desk / "notes.yaml").write_text(
            "name: notes\ndescription: d\nprompt: p\nmodel: openai:gpt-5-mini\n"
            "memory:\n  enabled: true\n"
        )

        result = runner.invoke(app, ["run", str(desk), "--serve", "--no-audit"])

        assert result.exit_code == 1
        assert "initrunner[vector]" in _flat(result.output)


class TestRunADirectory:
    def test_lists_members_and_exits(self, desk: Path) -> None:
        result = runner.invoke(app, ["run", str(desk), "-p", "hello", "--no-audit"])

        assert result.exit_code == 1
        for name in ("intake", "triage", "reply"):
            assert name in result.output
        assert "--agent" in result.output
        assert "helper" not in result.output

    def test_agent_flag_runs_one_member(self, desk: Path) -> None:
        result = runner.invoke(
            app,
            ["run", str(desk), "--agent", "triage", "-p", "hi", "--dry-run", "--no-audit"],
        )
        assert result.exit_code == 0, result.output

    def test_unknown_member_lists_the_names(self, desk: Path) -> None:
        result = runner.invoke(app, ["run", str(desk), "--agent", "nope", "-p", "hi", "--no-audit"])

        assert result.exit_code == 1
        assert "no agent 'nope'" in _flat(result.output)
        assert "intake" in result.output

    def test_sense_picks_a_member(self, desk: Path) -> None:
        result = runner.invoke(
            app,
            ["run", str(desk), "--sense", "-p", "sort this by severity", "--dry-run", "--no-audit"],
        )

        assert result.exit_code == 0, result.output
        assert "triage" in result.output

    def test_single_agent_flags_are_rejected(self, desk: Path) -> None:
        result = runner.invoke(app, ["run", str(desk), "-i", "--no-audit"])

        assert result.exit_code == 1
        assert "--interactive" in _flat(result.output)

    def test_save_is_rejected(self, desk: Path, tmp_path: Path) -> None:
        result = runner.invoke(app, ["run", str(desk), "--save", str(tmp_path / "out.yaml")])

        assert result.exit_code == 1
        assert "directory of agents" in _flat(result.output)

    def test_a_broken_member_stops_the_whole_group(self, desk: Path) -> None:
        (desk / "reply.yaml").write_text("name: reply\nmodel: 42\n")

        result = runner.invoke(app, ["run", str(desk), "--serve", "--no-audit"])

        assert result.exit_code == 1
        assert "reply.yaml" in _flat(result.output)

    @patch("initrunner.server.app.run_multi_server")
    def test_serve_uses_role_names_as_model_ids(self, mock_serve, desk: Path) -> None:
        result = runner.invoke(app, ["run", str(desk), "--serve", "--no-audit"])

        assert result.exit_code == 0, result.output
        members = mock_serve.call_args.args[0]
        assert sorted(members) == ["intake", "reply", "triage"]
        assert all(key == member.role.metadata.name for key, member in members.items())

    @patch("initrunner.group.daemon.run_group_daemon")
    def test_daemon_runs_every_member(self, mock_daemon, desk: Path) -> None:
        mock_daemon.return_value = MagicMock()

        result = runner.invoke(app, ["run", str(desk), "--daemon", "--no-audit"])

        assert result.exit_code == 0, result.output
        roster = mock_daemon.call_args.args[0]
        assert sorted(roster.members) == ["intake", "reply", "triage"]
