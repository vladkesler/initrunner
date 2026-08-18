"""Validate all example YAML files parse against their schemas."""

from pathlib import Path

import pytest
import yaml

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

_ALL_YAMLS = sorted(EXAMPLES_DIR.rglob("*.yaml"))

_ROLE_YAMLS = []
_FLOW_YAMLS = []
_TEAM_YAMLS = []
_SUITE_YAMLS = []

for _p in _ALL_YAMLS:
    with open(_p) as _f:
        try:
            _data = yaml.safe_load(_f)
        except yaml.YAMLError:
            continue
    if not isinstance(_data, dict):
        continue
    if _data.get("apiVersion", "").startswith("initguard/"):
        continue
    if _data.get("kind") == "Flow":
        _FLOW_YAMLS.append(_p)
    elif _data.get("kind") == "Team":
        _TEAM_YAMLS.append(_p)
    elif _data.get("kind") == "TestSuite":
        _SUITE_YAMLS.append(_p)
    elif _data.get("kind") == "Service":
        continue
    else:
        # Envelope Agent or flat v3 (solo / composed).
        from initrunner.agent.schema.adapt import run_kind_from_mapping
        from initrunner.agent.schema.document import DocumentClass, classify_mapping

        cls = classify_mapping(_data)
        if cls.document_class is DocumentClass.FLAT_AGENT:
            kind = run_kind_from_mapping(_data)
            if kind == "Flow":
                _FLOW_YAMLS.append(_p)
            elif kind == "Team":
                _TEAM_YAMLS.append(_p)
            else:
                _ROLE_YAMLS.append(_p)
        else:
            _ROLE_YAMLS.append(_p)


def _rel(path: Path) -> str:
    return str(path.relative_to(EXAMPLES_DIR))


@pytest.mark.parametrize("path", _ROLE_YAMLS, ids=[_rel(p) for p in _ROLE_YAMLS])
def test_role_yaml_validates(path: Path) -> None:
    from initrunner.agent.loader import load_role

    role = load_role(path)
    assert role.metadata.name
    assert role.spec.role


@pytest.mark.parametrize("path", _ROLE_YAMLS, ids=[_rel(p) for p in _ROLE_YAMLS])
def test_role_skills_resolve(path: Path) -> None:
    """Example roles with skills must resolve without --skill-dir."""
    from initrunner.agent.loader import load_role

    role = load_role(path)
    if not role.spec.skills:
        pytest.skip("No skills")

    from initrunner.agent.skills import resolve_skills

    resolved = resolve_skills(role.spec.skills, role_dir=path.parent, extra_dirs=None)
    assert len(resolved) == len(role.spec.skills)


@pytest.mark.parametrize("path", _FLOW_YAMLS, ids=[_rel(p) for p in _FLOW_YAMLS])
def test_flow_yaml_validates(path: Path) -> None:
    from initrunner.flow.loader import load_flow

    flow = load_flow(path)
    assert flow.metadata.name
    assert len(flow.spec.agents) >= 1


@pytest.mark.parametrize("path", _TEAM_YAMLS, ids=[_rel(p) for p in _TEAM_YAMLS])
def test_team_yaml_validates(path: Path) -> None:
    from initrunner.team.loader import load_team

    team = load_team(path)
    assert team.metadata.name
    assert len(team.spec.personas) >= 2


@pytest.mark.parametrize("path", _SUITE_YAMLS, ids=[_rel(p) for p in _SUITE_YAMLS])
def test_suite_yaml_validates(path: Path) -> None:
    from initrunner.eval.schema import TestSuiteDefinition

    with open(path) as f:
        data = yaml.safe_load(f)
    suite = TestSuiteDefinition.model_validate(data)
    assert suite.metadata.name
    assert len(suite.cases) >= 1


_ALLOWED_ENVELOPE_KINDS = {"Service", "TestSuite"}


@pytest.mark.parametrize("path", _ALL_YAMLS, ids=[_rel(p) for p in _ALL_YAMLS])
def test_examples_have_no_agent_team_flow_envelope(path: Path) -> None:
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return
    api = data.get("apiVersion", "")
    if isinstance(api, str) and api.startswith("initguard/"):
        return
    kind = data.get("kind")
    if data.get("apiVersion") == "initrunner/v1" and kind in {"Agent", "Team", "Flow"}:
        raise AssertionError(f"{path} still uses a public Agent/Team/Flow envelope")
    if kind in _ALLOWED_ENVELOPE_KINDS:
        return


# ---------------------------------------------------------------------------
# Policy YAML validation (initguard format)
# ---------------------------------------------------------------------------

_POLICY_DIRS: list[Path] = []
for _candidate in EXAMPLES_DIR.iterdir():
    if not _candidate.is_dir():
        continue
    _has_policy = any(
        yaml.safe_load(f.read_text()).get("apiVersion", "").startswith("initguard/")
        for f in _candidate.rglob("*.yaml")
        if f.is_file() and isinstance(yaml.safe_load(f.read_text()), dict)
    )
    if _has_policy:
        # Find the deepest directory containing policy files
        for _sub in [_candidate, *sorted(_candidate.rglob("*"))]:
            if _sub.is_dir() and any(_sub.glob("*.yaml")):
                _yaml_files = list(_sub.glob("*.yaml"))
                if _yaml_files and any(
                    isinstance(d := yaml.safe_load(f.read_text()), dict)
                    and d.get("apiVersion", "").startswith("initguard/")
                    for f in _yaml_files
                ):
                    _POLICY_DIRS.append(_sub)


@pytest.mark.parametrize("policy_dir", _POLICY_DIRS, ids=[_rel(p) for p in _POLICY_DIRS])
def test_policy_yaml_validates(policy_dir: Path) -> None:
    """Policy directories load without errors via initguard."""
    from initguard import load_policies  # type: ignore[import-not-found]

    policy_set = load_policies(str(policy_dir))
    assert policy_set is not None
