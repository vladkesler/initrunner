"""`initrunner run` against a group of agents."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()

_ROLE = "name: {name}\ndescription: {description}\nprompt: {prompt}\nmodel: openai:gpt-5-mini\n"


def _flat(output: str) -> str:
    """Collapse Rich's line wrapping so a phrase can be matched as written.

    Console width depends on the environment, so a message that fits on one
    line locally wraps mid-sentence in CI.
    """
    return " ".join(output.split())


def _make_group(tmp_path: Path, *, shared_memory: bool = False) -> Path:
    roles = tmp_path / "roles"
    roles.mkdir()
    (roles / "intake.yaml").write_text(
        _ROLE.format(
            name="intake-agent",
            description="Triages incoming support tickets",
            prompt="triage the ticket",
        )
    )
    (roles / "writer.yaml").write_text(
        _ROLE.format(
            name="writer-agent",
            description="Writes replies to customers",
            prompt="write the reply",
        )
    )
    path = tmp_path / "desk.yaml"
    body = "name: desk\n"
    if shared_memory:
        body += "shared_memory:\n  enabled: true\n"
    body += (
        "agents:\n  intake:\n    use: roles/intake.yaml\n  writer:\n    use: roles/writer.yaml\n"
    )
    path.write_text(body)
    return path


def test_no_member_lists_agents_and_exits(tmp_path: Path) -> None:
    """A group has no single run, so it never fans out or picks for you."""
    group = _make_group(tmp_path)

    result = runner.invoke(app, ["run", str(group), "-p", "hello", "--no-audit"])

    assert result.exit_code == 1
    assert "intake" in result.output
    assert "writer" in result.output
    assert "--agent" in result.output


def test_agent_flag_runs_that_member(tmp_path: Path) -> None:
    group = _make_group(tmp_path)

    result = runner.invoke(
        app,
        ["run", str(group), "--agent", "writer", "-p", "hi", "--dry-run", "--no-audit"],
    )

    assert result.exit_code == 0, result.output


def test_unknown_member_lists_valid_agents(tmp_path: Path) -> None:
    group = _make_group(tmp_path)

    result = runner.invoke(app, ["run", str(group), "--agent", "nope", "-p", "hi", "--no-audit"])

    assert result.exit_code == 1
    assert "no agent 'nope'" in _flat(result.output)
    assert "intake" in result.output


def test_agent_flag_rejected_for_solo_role(tmp_path: Path) -> None:
    role = tmp_path / "solo.yaml"
    role.write_text(_ROLE.format(name="solo", description="d", prompt="p"))

    result = runner.invoke(app, ["run", str(role), "--agent", "intake", "-p", "hi", "--no-audit"])

    assert result.exit_code == 1
    assert "is not a group" in _flat(result.output)


def test_sense_picks_a_member(tmp_path: Path) -> None:
    group = _make_group(tmp_path)

    result = runner.invoke(
        app,
        ["run", str(group), "--sense", "-p", "write the customer reply", "--dry-run", "--no-audit"],
    )

    assert result.exit_code == 0, result.output
    assert "writer-agent" in result.output


def test_single_agent_flags_rejected_without_member(tmp_path: Path) -> None:
    group = _make_group(tmp_path)

    result = runner.invoke(app, ["run", str(group), "-i", "--no-audit"])

    assert result.exit_code == 1
    assert "--interactive" in _flat(result.output)
    assert "--agent" in _flat(result.output)


@patch("initrunner.agent.loader.build_agent")
def test_member_run_applies_shared_memory(mock_build, tmp_path: Path) -> None:
    """A member picked from a group still gets the group's shared store."""
    group = _make_group(tmp_path, shared_memory=True)
    mock_build.return_value = MagicMock()

    runner.invoke(
        app,
        ["run", str(group), "--agent", "intake", "-p", "hi", "--dry-run", "--no-audit"],
    )

    built_role = mock_build.call_args.args[0]
    assert built_role.spec.memory is not None
    assert built_role.spec.memory.store_path.endswith("desk-shared.db")
    # ...and it is built against its own directory, not the group file's.
    assert mock_build.call_args.kwargs["role_dir"] == tmp_path / "roles"


def test_validate_renders_group(tmp_path: Path) -> None:
    group = _make_group(tmp_path)

    result = runner.invoke(app, ["validate", str(group)])

    assert result.exit_code == 0, result.output
    assert "Group: desk" in _flat(result.output)
    assert "Valid" in result.output


def test_validate_reports_missing_member(tmp_path: Path) -> None:
    group = _make_group(tmp_path)
    (tmp_path / "roles/writer.yaml").unlink()

    result = runner.invoke(app, ["validate", str(group)])

    assert result.exit_code == 1
    assert "agents.writer.use" in result.output


def test_plan_points_at_members(tmp_path: Path) -> None:
    group = _make_group(tmp_path)

    result = runner.invoke(app, ["plan", str(group), "-p", "hi"])

    assert result.exit_code == 1
    assert "intake.yaml" in result.output
