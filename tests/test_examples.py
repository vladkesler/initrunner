"""Validate all example YAML files parse against their schemas."""

from pathlib import Path

import pytest
import yaml

from initrunner.agent.schema.role import RoleDefinition
from initrunner.compose.schema import ComposeDefinition
from initrunner.team.schema import TeamDefinition

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

_ALL_YAMLS = sorted(EXAMPLES_DIR.rglob("*.yaml"))

_ROLE_YAMLS = []
_COMPOSE_YAMLS = []
_TEAM_YAMLS = []

for _p in _ALL_YAMLS:
    with open(_p) as _f:
        _data = yaml.safe_load(_f)
    if isinstance(_data, dict) and _data.get("kind") == "Compose":
        _COMPOSE_YAMLS.append(_p)
    elif isinstance(_data, dict) and _data.get("kind") == "Team":
        _TEAM_YAMLS.append(_p)
    else:
        _ROLE_YAMLS.append(_p)


def _rel(path: Path) -> str:
    return str(path.relative_to(EXAMPLES_DIR))


@pytest.mark.parametrize("path", _ROLE_YAMLS, ids=[_rel(p) for p in _ROLE_YAMLS])
def test_role_yaml_validates(path: Path) -> None:
    with open(path) as f:
        data = yaml.safe_load(f)
    role = RoleDefinition.model_validate(data)
    assert role.metadata.name
    assert role.spec.role


@pytest.mark.parametrize("path", _ROLE_YAMLS, ids=[_rel(p) for p in _ROLE_YAMLS])
def test_role_skills_resolve(path: Path) -> None:
    """Example roles with skills must resolve without --skill-dir."""
    with open(path) as f:
        data = yaml.safe_load(f)
    role = RoleDefinition.model_validate(data)
    if not role.spec.skills:
        pytest.skip("No skills")

    from initrunner.agent.skills import resolve_skills

    resolved = resolve_skills(role.spec.skills, role_dir=path.parent, extra_dirs=None)
    assert len(resolved) == len(role.spec.skills)


@pytest.mark.parametrize("path", _COMPOSE_YAMLS, ids=[_rel(p) for p in _COMPOSE_YAMLS])
def test_compose_yaml_validates(path: Path) -> None:
    with open(path) as f:
        data = yaml.safe_load(f)
    compose = ComposeDefinition.model_validate(data)
    assert compose.metadata.name
    assert len(compose.spec.services) >= 1


@pytest.mark.parametrize("path", _TEAM_YAMLS, ids=[_rel(p) for p in _TEAM_YAMLS])
def test_team_yaml_validates(path: Path) -> None:
    with open(path) as f:
        data = yaml.safe_load(f)
    team = TeamDefinition.model_validate(data)
    assert team.metadata.name
    assert len(team.spec.personas) >= 2
