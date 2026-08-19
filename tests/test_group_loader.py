"""Loading a group and its member roles."""

from __future__ import annotations

from pathlib import Path

import pytest

from initrunner.group.loader import GroupLoadError, load_group, load_group_definition

_ROLE = "name: {name}\nprompt: do the thing\nmodel: openai:gpt-5-mini\n"


def _group_dir(tmp_path: Path, members: dict[str, str], **group_fields: str) -> Path:
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    lines = ["name: desk"]
    lines.extend(f"{k}: {v}" for k, v in group_fields.items())
    lines.append("agents:")
    for key, role_name in members.items():
        (roles / f"{key}.yaml").write_text(_ROLE.format(name=role_name))
        lines.append(f"  {key}:")
        lines.append(f"    use: roles/{key}.yaml")
    path = tmp_path / "desk.yaml"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_load_group_reads_every_member(tmp_path: Path) -> None:
    path = _group_dir(tmp_path, {"intake": "intake-agent", "writer": "writer-agent"})

    roster = load_group(path)

    assert roster.name == "desk"
    assert roster.keys() == ["intake", "writer"]
    assert roster.members["intake"].role.metadata.name == "intake-agent"
    # Members resolve their own paths, not the group file's.
    assert roster.members["intake"].role_dir == (tmp_path / "roles").resolve()


def test_group_of_one_is_a_group(tmp_path: Path) -> None:
    path = _group_dir(tmp_path, {"solo": "solo-agent"})

    roster = load_group(path)

    assert roster.keys() == ["solo"]


def test_definition_does_not_read_members(tmp_path: Path) -> None:
    """Validation needs the member list even when a member file is missing."""
    path = tmp_path / "desk.yaml"
    path.write_text("name: desk\nagents:\n  gone:\n    use: roles/gone.yaml\n")

    group = load_group_definition(path)

    assert list(group.members) == ["gone"]
    assert group.members["gone"].path == (tmp_path / "roles/gone.yaml").resolve()


def test_all_member_failures_reported_together(tmp_path: Path) -> None:
    path = _group_dir(tmp_path, {"ok": "ok-agent", "broken": "broken-agent"})
    (tmp_path / "roles/broken.yaml").write_text("name: broken-agent\nprompt: hi\nnope: 1\n")
    (tmp_path / "roles/missing.yaml").unlink(missing_ok=True)
    path.write_text(path.read_text() + "  gone:\n    use: roles/missing.yaml\n")

    with pytest.raises(GroupLoadError) as excinfo:
        load_group(path)

    message = str(excinfo.value)
    assert "broken" in message
    assert "gone" in message


def test_duplicate_member_role_names_rejected(tmp_path: Path) -> None:
    """Runs, budgets and stores are keyed on the role name, so it must be unique."""
    path = _group_dir(tmp_path, {"a": "same-agent", "b": "same-agent"})

    with pytest.raises(GroupLoadError, match="share a name"):
        load_group(path)


def test_team_file_is_not_a_group(tmp_path: Path) -> None:
    path = tmp_path / "team.yaml"
    path.write_text("name: t\nrun: sequential\nagents:\n  a: one\n  b: two\n")

    with pytest.raises(GroupLoadError, match="not a group"):
        load_group(path)
