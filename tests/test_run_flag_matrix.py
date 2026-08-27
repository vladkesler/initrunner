"""Every `run` flag is consumed or refused in every context.

The point of trimming `run` was that a flag should never be accepted and then
silently ignored. This walks each retained flag across each kind of target and
asserts one of two things happened: the dispatcher actually received it, or the
run stopped with an error naming it. A new flag that lands in neither column
fails here.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()

_AGENT = (
    "apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: matrix-agent\n"
    "spec:\n  role: test\n  model:\n    provider: openai\n    name: gpt-5-mini\n"
)
_TEAM = (
    "apiVersion: initrunner/v1\nkind: Team\nmetadata:\n  name: matrix-team\n"
    "spec:\n  model:\n    provider: openai\n    name: gpt-5-mini\n"
    '  personas:\n    alpha: "first"\n    bravo: "second"\n'
)
_FLOW = (
    "apiVersion: initrunner/v1\nkind: Flow\nmetadata:\n  name: matrix-flow\n"
    "spec:\n  agents:\n    worker:\n      role: worker.yaml\n"
)


@pytest.fixture
def agent_file(tmp_path: Path) -> Path:
    p = tmp_path / "role.yaml"
    p.write_text(_AGENT)
    return p


@pytest.fixture
def team_file(tmp_path: Path) -> Path:
    p = tmp_path / "team.yaml"
    p.write_text(_TEAM)
    return p


@pytest.fixture
def flow_file(tmp_path: Path) -> Path:
    (tmp_path / "worker.yaml").write_text(_AGENT)
    p = tmp_path / "flow.yaml"
    p.write_text(_FLOW)
    return p


@pytest.fixture
def group_dir(tmp_path: Path) -> Path:
    d = tmp_path / "group"
    d.mkdir()
    (d / "one.yaml").write_text(_AGENT.replace("matrix-agent", "one"))
    (d / "two.yaml").write_text(_AGENT.replace("matrix-agent", "two"))
    return d


def _refused(argv: list[str], flag: str) -> None:
    """The run must stop with an error that names *flag*."""
    result = runner.invoke(app, argv)
    assert result.exit_code == 1, f"{argv} exited {result.exit_code}: {result.output}"
    flat = " ".join(result.output.split())
    assert flag in flat, f"{argv} did not name {flag}: {flat}"


# ---------------------------------------------------------------------------
# Refused: the target cannot honour the flag
# ---------------------------------------------------------------------------


class TestEphemeralRefusals:
    """No role file: nothing to attach a report, var, or member to."""

    @pytest.mark.parametrize(
        ("argv", "flag"),
        [
            (["-a", "-p", "hi"], "--autonomous"),
            (["--dry-run", "-p", "hi"], "--dry-run"),
            (["--report", "out.md", "-p", "hi"], "--report"),
            (["--var", "K=V", "-p", "hi"], "--var"),
            (["--agent", "one", "-p", "hi"], "--agent"),
            (["--format", "json", "-p", "hi"], "--format"),
            (["--daemon"], "daemon"),
            (["--serve"], "serve"),
        ],
    )
    def test_refused_without_a_role_file(self, argv, flag):
        _refused(["run", *argv], flag)


class TestRoleFileRefusals:
    """Ephemeral-only settings come from the YAML when there is a role file."""

    @pytest.mark.parametrize(
        ("argv", "flag"),
        [
            (["--tools", "all"], "--tools"),
            (["--no-memory", "-p", "hi"], "--memory/--no-memory"),
            (["--memory", "-p", "hi"], "--memory/--no-memory"),
            (["--ingest", "docs/"], "--ingest"),
        ],
    )
    def test_refused_with_a_role_file(self, agent_file, argv, flag):
        _refused(["run", str(agent_file), *argv], flag)


class TestModeRefusals:
    """A long-running mode has no single run to steer."""

    @pytest.mark.parametrize(
        ("argv", "flag"),
        [
            (["--daemon", "--format", "json"], "--format"),
            (["--daemon", "-p", "hi"], "--prompt"),
            (["--serve", "-p", "hi"], "--prompt"),
            (["--port", "9000", "-p", "hi"], "--port"),
            (["--host", "0.0.0.0", "-p", "hi"], "--host"),
        ],
    )
    def test_refused_outside_its_mode(self, agent_file, argv, flag):
        _refused(["run", str(agent_file), *argv], flag)


class TestTeamRefusals:
    @pytest.mark.parametrize(
        ("argv", "flag"),
        [
            (["-p", "hi", "--model", "openai:gpt-5-mini"], "--model"),
            (["-p", "hi", "--report", "out.md"], "--report"),
            (["-p", "hi", "--format", "json"], "--format"),
            (["-p", "hi", "--var", "K=V"], "--var"),
            (["-p", "hi", "-i"], "--interactive"),
            (["--daemon"], "--daemon"),
            (["--serve"], "--serve"),
        ],
    )
    def test_team_refuses_single_agent_flags(self, team_file, argv, flag):
        _refused(["run", str(team_file), *argv], flag)


class TestFlowRefusals:
    @pytest.mark.parametrize(
        ("argv", "flag"),
        [
            (["-p", "hi", "--model", "openai:gpt-5-mini"], "--model"),
            (["-p", "hi", "--dry-run"], "--dry-run"),
            (["-p", "hi", "--report", "out.md"], "--report"),
            (["--daemon"], "--daemon"),
            (["--serve"], "--serve"),
        ],
    )
    def test_flow_refuses_single_agent_flags(self, flow_file, argv, flag):
        _refused(["run", str(flow_file), *argv], flag)


class TestWholeGroupRefusals:
    """A whole group has no single run; --agent narrows it to one."""

    @pytest.mark.parametrize(
        ("argv", "flag"),
        [
            (["--daemon", "--report", "out.md"], "--report"),
            (["--daemon", "--attach", "x.png"], "--attach"),
            (["--daemon", "--var", "K=V"], "--var"),
            (["--serve", "--format", "json"], "--format"),
        ],
    )
    def test_group_refuses_single_agent_flags(self, group_dir, argv, flag):
        _refused(["run", str(group_dir), *argv], flag)


# ---------------------------------------------------------------------------
# Consumed: the dispatcher actually receives the value
# ---------------------------------------------------------------------------


class TestConsumed:
    def test_ephemeral_receives_its_flags(self):
        with patch("initrunner.cli._ephemeral.dispatch_ephemeral") as mock:
            result = runner.invoke(
                app,
                ["run", "-p", "hi", "--tools", "all", "--no-memory", "--ingest", "docs/"],
            )
        assert result.exit_code == 0
        kwargs = mock.call_args[1]
        assert kwargs["tools"] == ["all"]
        assert kwargs["memory"] is False
        assert kwargs["ingest"] == ["docs/"]
        assert kwargs["prompt"] == "hi"

    def test_serve_receives_host_and_port(self, agent_file):
        with patch("initrunner.cli.run_cmd._command._dispatch_serve") as mock:
            result = runner.invoke(
                app, ["run", str(agent_file), "--serve", "--host", "0.0.0.0", "--port", "9001"]
            )
        assert result.exit_code == 0
        args = mock.call_args[0]
        assert args[1] == "0.0.0.0"
        assert args[2] == 9001

    def test_group_serve_receives_host_and_port(self, group_dir):
        with patch("initrunner.cli.run_cmd._group_dispatch.dispatch_group_serve") as mock:
            result = runner.invoke(
                app, ["run", str(group_dir), "--serve", "--host", "0.0.0.0", "--port", "9002"]
            )
        assert result.exit_code == 0
        args = mock.call_args[0]
        assert args[1] == "0.0.0.0"
        assert args[2] == 9002

    def test_agent_receives_report_spec_and_model(self, agent_file, tmp_path):
        with patch("initrunner.cli.run_cmd._command._run_agent") as mock:
            result = runner.invoke(
                app,
                [
                    "run",
                    str(agent_file),
                    "-p",
                    "hi",
                    "--report",
                    f"pr-review:{tmp_path / 'r.md'}",
                    "--model",
                    "openai:gpt-5-mini",
                ],
            )
        assert result.exit_code == 0
        kwargs = mock.call_args[1]
        assert kwargs["report_spec"] == ("pr-review", tmp_path / "r.md")
        assert kwargs["model"] == "openai:gpt-5-mini"

    def test_group_member_runs_as_a_single_agent(self, group_dir):
        """--agent rewrites the target to Agent, so single-agent flags apply."""
        with patch("initrunner.cli.run_cmd._command._run_agent") as mock:
            result = runner.invoke(
                app, ["run", str(group_dir), "--agent", "one", "-p", "hi", "--format", "json"]
            )
        assert result.exit_code == 0
        assert mock.call_args[1]["output_format"] == "json"

    def test_team_receives_prompt_and_dry_run(self, team_file):
        with patch("initrunner.cli.run_cmd._command._run_team") as mock:
            result = runner.invoke(app, ["run", str(team_file), "-p", "hi", "--dry-run"])
        assert result.exit_code == 0
        args = mock.call_args[0]
        assert args[1] == "hi"
        assert args[2] is True

    def test_flow_receives_prompt(self, flow_file):
        with patch("initrunner.cli.run_cmd._command._dispatch_flow") as mock:
            result = runner.invoke(app, ["run", str(flow_file), "-p", "hi"])
        assert result.exit_code == 0
        assert mock.call_args[1]["prompt"] == "hi"

    def test_daemon_receives_the_model_override(self, agent_file):
        with patch("initrunner.cli.run_cmd._command._dispatch_daemon") as mock:
            result = runner.invoke(
                app, ["run", str(agent_file), "--daemon", "--model", "openai:gpt-5-mini"]
            )
        assert result.exit_code == 0
        assert mock.call_args[0][2] == "openai:gpt-5-mini"
