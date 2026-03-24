"""Tests for /api/compose-builder routes."""

from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.deps import (
    ComposeCache,
    RoleCache,
    _compose_id,
    _role_id,
    get_compose_cache,
    get_role_cache,
)
from initrunner.templates import build_role_yaml


def _write_agent(directory: Path, name: str) -> Path:
    """Write a minimal agent role file and return its path."""
    role_yaml = build_role_yaml(name=name, description=f"Test agent {name}", provider="openai")
    p = directory / f"{name}.yaml"
    p.write_text(role_yaml)
    return p


class _IsolatedRoleCache(RoleCache):
    def __init__(self, dirs: list[Path]):
        settings = DashboardSettings()
        self._settings = settings
        self._dirs = dirs
        self._cache: dict = {}

    def refresh(self):
        from initrunner.services.discovery import discover_roles_sync

        roles = discover_roles_sync(self._dirs)
        self._cache = {_role_id(r.path): r for r in roles}
        return self._cache


class _IsolatedComposeCache(ComposeCache):
    def __init__(self, dirs: list[Path]):
        settings = DashboardSettings()
        self._settings = settings
        self._dirs = dirs
        self._cache: dict = {}

    def refresh(self):
        from initrunner.services.discovery import discover_composes_sync

        composes = discover_composes_sync(self._dirs)
        self._cache = {_compose_id(c.path): c for c in composes}
        return self._cache


@pytest.fixture
def role_dir(tmp_path):
    """Temp dir with two agent files."""
    d = tmp_path / "roles"
    d.mkdir()
    _write_agent(d, "fetcher")
    _write_agent(d, "summarizer")
    return d


@pytest.fixture
def client(role_dir):
    settings = DashboardSettings()
    app = create_app(settings)

    role_cache = _IsolatedRoleCache([role_dir])
    role_cache.refresh()
    compose_cache = _IsolatedComposeCache([role_dir])
    compose_cache.refresh()

    app.dependency_overrides[get_role_cache] = lambda: role_cache
    app.dependency_overrides[get_compose_cache] = lambda: compose_cache

    return TestClient(app), role_cache


# -- GET /api/compose-builder/options ------------------------------------------


def test_builder_options(client):
    tc, _ = client
    resp = tc.get("/api/compose-builder/options")
    assert resp.status_code == 200
    data = resp.json()

    # Patterns
    assert len(data["patterns"]) == 3
    names = {p["name"] for p in data["patterns"]}
    assert names == {"pipeline", "fan-out", "route"}

    # Route is fixed topology
    route = next(p for p in data["patterns"] if p["name"] == "route")
    assert route["fixed_topology"] is True
    assert len(route["slot_names"]) == 4

    # Agents
    assert len(data["agents"]) == 2
    agent_names = {a["name"] for a in data["agents"]}
    assert agent_names == {"fetcher", "summarizer"}

    # Provider surface
    assert len(data["providers"]) > 0
    assert len(data["save_dirs"]) > 0
    assert isinstance(data["ollama_models"], list)


# -- POST /api/compose-builder/seed -------------------------------------------


def test_seed_pipeline_placeholders(client):
    tc, _ = client
    resp = tc.post(
        "/api/compose-builder/seed",
        json={
            "pattern": "pipeline",
            "name": "test-pipe",
            "services": [
                {"slot": "step-1", "agent_id": None},
                {"slot": "step-2", "agent_id": None},
            ],
            "service_count": 2,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "compose_yaml" in data
    assert len(data["role_yamls"]) == 2
    assert data["ready"] is True

    parsed = yaml.safe_load(data["compose_yaml"])
    assert parsed["kind"] == "Compose"
    assert len(parsed["spec"]["services"]) == 2


def test_seed_pipeline_with_existing_agent(client):
    tc, role_cache = client
    agents = [
        {"id": rid, "path": dr.path}
        for rid, dr in role_cache.all().items()
        if dr.role and dr.role.metadata.name == "fetcher"
    ]
    assert len(agents) > 0
    agent_id = agents[0]["id"]

    resp = tc.post(
        "/api/compose-builder/seed",
        json={
            "pattern": "pipeline",
            "name": "test-mixed",
            "services": [
                {"slot": "step-1", "agent_id": agent_id},
                {"slot": "step-2", "agent_id": None},
            ],
            "service_count": 2,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    # Only 1 placeholder role (step-2), step-1 uses existing agent
    assert len(data["role_yamls"]) == 1
    assert "step-2.yaml" in data["role_yamls"]
    assert "step-1.yaml" not in data["role_yamls"]


def test_seed_route_fixed(client):
    tc, _ = client
    resp = tc.post(
        "/api/compose-builder/seed",
        json={
            "pattern": "route",
            "name": "test-route",
            "services": [
                {"slot": "intake", "agent_id": None},
                {"slot": "researcher", "agent_id": None},
                {"slot": "responder", "agent_id": None},
                {"slot": "escalator", "agent_id": None},
            ],
            "service_count": 4,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    parsed = yaml.safe_load(data["compose_yaml"])
    expected = {"intake", "researcher", "responder", "escalator"}
    assert set(parsed["spec"]["services"].keys()) == expected


def test_seed_invalid_pattern(client):
    tc, _ = client
    resp = tc.post(
        "/api/compose-builder/seed",
        json={
            "pattern": "bogus",
            "name": "test",
            "services": [],
            "service_count": 2,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    assert resp.status_code == 400


def test_seed_shared_memory(client):
    tc, _ = client
    resp = tc.post(
        "/api/compose-builder/seed",
        json={
            "pattern": "pipeline",
            "name": "test-sm",
            "services": [
                {"slot": "step-1", "agent_id": None},
                {"slot": "step-2", "agent_id": None},
            ],
            "service_count": 2,
            "shared_memory": True,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    parsed = yaml.safe_load(resp.json()["compose_yaml"])
    assert parsed["spec"]["shared_memory"]["enabled"] is True


# -- POST /api/compose-builder/validate ----------------------------------------


def test_validate_valid_yaml(client):
    tc, _ = client
    seed_resp = tc.post(
        "/api/compose-builder/seed",
        json={
            "pattern": "pipeline",
            "name": "v",
            "services": [{"slot": "step-1"}, {"slot": "step-2"}],
            "service_count": 2,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    yaml_text = seed_resp.json()["compose_yaml"]

    resp = tc.post("/api/compose-builder/validate", json={"yaml_text": yaml_text})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert len(data["issues"]) == 0


def test_validate_invalid_yaml(client):
    tc, _ = client
    resp = tc.post("/api/compose-builder/validate", json={"yaml_text": "not: valid: yaml: ["})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is False
    assert len(data["issues"]) > 0


def test_validate_missing_spec(client):
    tc, _ = client
    resp = tc.post(
        "/api/compose-builder/validate",
        json={"yaml_text": "apiVersion: initrunner/v1\nkind: Compose\nmetadata:\n  name: x\n"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is False


# -- POST /api/compose-builder/save -------------------------------------------


def test_save_compose(client, tmp_path):
    tc, _ = client
    seed_resp = tc.post(
        "/api/compose-builder/seed",
        json={
            "pattern": "pipeline",
            "name": "saved",
            "services": [{"slot": "step-1"}, {"slot": "step-2"}],
            "service_count": 2,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    seed_data = seed_resp.json()

    resp = tc.post(
        "/api/compose-builder/save",
        json={
            "compose_yaml": seed_data["compose_yaml"],
            "role_yamls": seed_data["role_yamls"],
            "directory": str(tmp_path),
            "project_name": "saved",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert "compose_id" in data
    assert len(data["next_steps"]) > 0
    assert (tmp_path / "saved" / "compose.yaml").exists()


def test_save_conflict(client, tmp_path):
    tc, _ = client
    seed_resp = tc.post(
        "/api/compose-builder/seed",
        json={
            "pattern": "pipeline",
            "name": "dup",
            "services": [{"slot": "step-1"}, {"slot": "step-2"}],
            "service_count": 2,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    seed_data = seed_resp.json()

    tc.post(
        "/api/compose-builder/save",
        json={
            "compose_yaml": seed_data["compose_yaml"],
            "role_yamls": seed_data["role_yamls"],
            "directory": str(tmp_path),
            "project_name": "dup",
        },
    )

    resp = tc.post(
        "/api/compose-builder/save",
        json={
            "compose_yaml": seed_data["compose_yaml"],
            "role_yamls": seed_data["role_yamls"],
            "directory": str(tmp_path),
            "project_name": "dup",
        },
    )
    assert resp.status_code == 409
