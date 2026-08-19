"""Preparing group members for a run."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from initrunner.group.loader import load_group
from initrunner.group.prepare import GroupPrepareError, make_group_overlay, prepare_group

_ROLE = "name: {name}\nprompt: do the thing\nmodel: openai:gpt-5-mini\n"


def _make_group(tmp_path: Path, body_extra: str = "") -> Path:
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    for key, name in (("intake", "intake-agent"), ("writer", "writer-agent")):
        (roles / f"{key}.yaml").write_text(_ROLE.format(name=name))
    path = tmp_path / "desk.yaml"
    path.write_text(
        "name: desk\n"
        + body_extra
        + "agents:\n  intake:\n    use: roles/intake.yaml\n  writer:\n    use: roles/writer.yaml\n"
    )
    return path


def test_overlay_is_identity_without_shared_config(tmp_path: Path) -> None:
    """With nothing shared, a member runs exactly as it does standalone."""
    roster = load_group(_make_group(tmp_path))
    overlay = make_group_overlay(roster.group)

    role = roster.members["intake"].role
    assert overlay(role).spec.memory is None


def test_overlay_points_members_at_the_shared_store(tmp_path: Path) -> None:
    roster = load_group(_make_group(tmp_path, "shared_memory:\n  enabled: true\n"))
    overlay = make_group_overlay(roster.group)

    paths = {}
    for key, member in roster.members.items():
        memory = overlay(member.role).spec.memory
        assert memory is not None
        paths[key] = memory.store_path

    assert paths["intake"] == paths["writer"]
    assert str(paths["intake"]).endswith("desk-shared.db")


def test_overlay_honours_an_explicit_store_path(tmp_path: Path) -> None:
    store = tmp_path / "team.db"
    roster = load_group(
        _make_group(tmp_path, f"shared_memory:\n  enabled: true\n  store_path: {store}\n")
    )

    role = make_group_overlay(roster.group)(roster.members["intake"].role)

    assert role.spec.memory is not None
    assert role.spec.memory.store_path == str(store)


@patch("initrunner.agent.loader.build_agent")
def test_prepare_builds_every_member_in_its_own_directory(mock_build, tmp_path: Path) -> None:
    mock_build.return_value = MagicMock()
    roster = load_group(_make_group(tmp_path))

    prepared = prepare_group(roster)

    assert list(prepared) == ["intake", "writer"]
    assert prepared["intake"].role.metadata.name == "intake-agent"
    role_dirs = {call.kwargs["role_dir"] for call in mock_build.call_args_list}
    assert role_dirs == {tmp_path / "roles"}


@patch("initrunner.agent.loader.build_agent")
def test_prepare_selected_members_only(mock_build, tmp_path: Path) -> None:
    mock_build.return_value = MagicMock()
    roster = load_group(_make_group(tmp_path))

    prepared = prepare_group(roster, keys=["writer"])

    assert list(prepared) == ["writer"]


@patch("initrunner.agent.loader.build_agent")
def test_prepare_is_atomic(mock_build, tmp_path: Path) -> None:
    """A service must not come up quietly missing one of its agents."""
    mock_build.side_effect = [MagicMock(), RuntimeError("boom")]
    roster = load_group(_make_group(tmp_path))

    with pytest.raises(GroupPrepareError, match="failed to build"):
        prepare_group(roster)


def test_prepare_unknown_member(tmp_path: Path) -> None:
    roster = load_group(_make_group(tmp_path))

    with pytest.raises(GroupPrepareError, match="no agent 'nope'"):
        prepare_group(roster, keys=["nope"])
