"""Path-traversal hardening for dashboard builder save endpoints.

Covers the ``_paths`` helper directly and the four save endpoints that write
request-controlled paths (agent/flow/team/skill builders), asserting that
escapes are rejected (HTTP 400) and nothing is written outside an allowed root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="dashboard extras not installed")

from starlette.testclient import TestClient

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.deps import (
    FlowCache,
    RoleCache,
    SkillCache,
    TeamCache,
    get_flow_cache,
    get_role_cache,
    get_skill_cache,
    get_team_cache,
)
from initrunner.dashboard.routers._paths import (
    PathValidationError,
    role_save_roots,
    safe_basename,
    validated_child_dir,
    validated_file_target,
)

# ---------------------------------------------------------------------------
# Unit tests: _paths helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "..", "/abs", "a/../b"])
def test_safe_basename_rejects(bad):
    with pytest.raises(PathValidationError):
        safe_basename(bad)


def test_safe_basename_accepts_plain_name():
    assert safe_basename("role.yaml") == "role.yaml"


def test_validated_file_target_accepts_absolute_in_root(tmp_path):
    root = tmp_path / "roles"
    root.mkdir()
    # Absolute directory must be allowed as long as it resolves within a root.
    dest = validated_file_target(str(root), "agent.yaml", [root])
    assert dest == (root / "agent.yaml").resolve()


def test_validated_file_target_rejects_prefix_sibling(tmp_path):
    root = tmp_path / "roles"
    root.mkdir()
    sibling = tmp_path / "roles_evil"
    sibling.mkdir()
    # String-prefix bypass: /roles_evil must NOT pass a /roles allowlist.
    with pytest.raises(PathValidationError):
        validated_file_target(str(sibling), "agent.yaml", [root])


def test_validated_file_target_rejects_traversal_filename(tmp_path):
    root = tmp_path / "roles"
    root.mkdir()
    with pytest.raises(PathValidationError):
        validated_file_target(str(root), "../outside.yaml", [root])


def test_validated_child_dir_rejects_absolute_child(tmp_path):
    root = tmp_path / "roles"
    root.mkdir()
    with pytest.raises(PathValidationError):
        validated_child_dir(str(root), "/etc", [root])


# ---------------------------------------------------------------------------
# Endpoint fixtures
# ---------------------------------------------------------------------------


def _settings_allowing(dirs: list[Path]) -> DashboardSettings:
    return DashboardSettings(extra_role_dirs=list(dirs))


class _Cache:
    """Mixin giving a cache configurable allowed roots and a no-op refresh."""

    def _init(self, settings: DashboardSettings) -> None:
        self._settings = settings
        self._cache: dict = {}

    def refresh(self):
        return self._cache

    def refresh_one(self, *args, **kwargs):
        return None


class _RoleCache(_Cache, RoleCache):
    def __init__(self, settings):
        self._init(settings)


class _FlowCache(_Cache, FlowCache):
    def __init__(self, settings):
        self._init(settings)


class _TeamCache(_Cache, TeamCache):
    def __init__(self, settings):
        self._init(settings)


class _SkillCache(_Cache, SkillCache):
    def __init__(self, settings):
        self._init(settings)


@pytest.fixture
def allowed_root(tmp_path):
    d = tmp_path / "roles"
    d.mkdir()
    return d


@pytest.fixture
def client(allowed_root):
    settings = _settings_allowing([allowed_root])
    app = create_app(settings)
    app.dependency_overrides[get_role_cache] = lambda: _RoleCache(settings)
    app.dependency_overrides[get_flow_cache] = lambda: _FlowCache(settings)
    app.dependency_overrides[get_team_cache] = lambda: _TeamCache(settings)
    app.dependency_overrides[get_skill_cache] = lambda: _SkillCache(settings)
    return TestClient(app)


_AGENT_YAML = (
    "apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: a\n"
    "spec:\n  role: |\n    You help.\n  model:\n    provider: openai\n    name: gpt-4o\n"
)


# ---------------------------------------------------------------------------
# Endpoint regression tests -- one per vuln
# ---------------------------------------------------------------------------


def test_agent_save_rejects_traversal_filename(client, tmp_path, allowed_root):
    resp = client.post(
        "/api/builder/save",
        json={
            "yaml_text": _AGENT_YAML,
            "directory": str(allowed_root),
            "filename": "../outside.yaml",
        },
    )
    assert resp.status_code == 400
    assert not (tmp_path / "outside.yaml").exists()


def test_agent_save_rejects_outside_directory(client, tmp_path, allowed_root):
    resp = client.post(
        "/api/builder/save",
        json={
            "yaml_text": _AGENT_YAML,
            "directory": str(tmp_path / "elsewhere"),
            "filename": "a.yaml",
        },
    )
    assert resp.status_code == 400


def test_flow_save_rejects_outside_directory(client, tmp_path, allowed_root):
    resp = client.post(
        "/api/flow-builder/save",
        json={
            "flow_yaml": "apiVersion: initrunner/v1\nkind: Flow\n",
            "role_yamls": {},
            "directory": str(tmp_path),
            "project_name": "proj",
        },
    )
    assert resp.status_code == 400
    assert not (tmp_path / "proj").exists()


def test_flow_save_rejects_absolute_project_name(client, allowed_root):
    resp = client.post(
        "/api/flow-builder/save",
        json={
            "flow_yaml": "apiVersion: initrunner/v1\nkind: Flow\n",
            "role_yamls": {},
            "directory": str(allowed_root),
            "project_name": "/etc/evil",
        },
    )
    assert resp.status_code == 400


def test_flow_save_rejects_traversal_role_key(client, tmp_path, allowed_root):
    # project_name is valid, but a role_yamls key tries to escape roles/.
    resp = client.post(
        "/api/flow-builder/save",
        json={
            "flow_yaml": "apiVersion: initrunner/v1\nkind: Flow\n",
            "role_yamls": {"../../evil.yaml": "apiVersion: initrunner/v1\nkind: Agent\n"},
            "directory": str(allowed_root),
            "project_name": "proj",
        },
    )
    assert resp.status_code == 400
    assert not (tmp_path / "evil.yaml").exists()


def test_team_save_rejects_prefix_sibling(client, tmp_path):
    sibling = tmp_path / "roles_evil"
    sibling.mkdir()
    from initrunner.services.team_builder import build_blank_team_yaml

    yaml_text = build_blank_team_yaml("t", provider="openai")
    resp = client.post(
        "/api/team-builder/save",
        json={
            "yaml_text": yaml_text,
            "directory": str(sibling),
            "filename": "t.yaml",
            "force": False,
        },
    )
    assert resp.status_code == 400
    assert not (sibling / "t.yaml").exists()


def test_team_save_rejects_traversal_filename(client, tmp_path, allowed_root):
    from initrunner.services.team_builder import build_blank_team_yaml

    yaml_text = build_blank_team_yaml("t", provider="openai")
    resp = client.post(
        "/api/team-builder/save",
        json={
            "yaml_text": yaml_text,
            "directory": str(allowed_root),
            "filename": "../evil.yaml",
            "force": False,
        },
    )
    assert resp.status_code == 400
    assert not (tmp_path / "evil.yaml").exists()


def test_skill_create_rejects_outside_directory(client, tmp_path):
    resp = client.post(
        "/api/skills",
        json={"name": "my-skill", "directory": str(tmp_path / "nope"), "provider": "openai"},
    )
    assert resp.status_code == 400


def test_skill_create_rejects_traversal_name(client, allowed_root):
    skill_dir = allowed_root / "skills"
    skill_dir.mkdir()
    resp = client.post(
        "/api/skills",
        json={"name": "../evil", "directory": str(skill_dir), "provider": "openai"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Positive: first-run save to the global roles dir even if discovery missed it
# ---------------------------------------------------------------------------


def test_role_save_roots_includes_global_roles_dir(tmp_path, monkeypatch):
    import initrunner.config as cfg

    global_roles = tmp_path / "dot-initrunner" / "roles"
    monkeypatch.setattr(cfg, "get_roles_dir", lambda: global_roles)

    settings = DashboardSettings()  # no extra dirs, discovery may not include global
    roots = role_save_roots(settings)
    assert global_roles in roots
