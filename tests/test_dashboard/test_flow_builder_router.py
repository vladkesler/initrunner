"""Tests for /api/flow-builder routes."""

from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.deps import (
    FlowCache,
    RoleCache,
    _flow_id,
    _role_id,
    get_flow_cache,
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


class _IsolatedFlowCache(FlowCache):
    def __init__(self, dirs: list[Path]):
        settings = DashboardSettings()
        self._settings = settings
        self._dirs = dirs
        self._cache: dict = {}

    def refresh(self):
        from initrunner.services.discovery import discover_flows_sync

        flows = discover_flows_sync(self._dirs)
        self._cache = {_flow_id(c.path): c for c in flows}
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
    flow_cache = _IsolatedFlowCache([role_dir])
    flow_cache.refresh()

    app.dependency_overrides[get_role_cache] = lambda: role_cache
    app.dependency_overrides[get_flow_cache] = lambda: flow_cache

    return TestClient(app), role_cache


# -- GET /api/flow-builder/options ------------------------------------------


def test_builder_options(client):
    tc, _ = client
    resp = tc.get("/api/flow-builder/options")
    assert resp.status_code == 200
    data = resp.json()

    # Patterns
    assert len(data["patterns"]) == 3
    names = {p["name"] for p in data["patterns"]}
    assert names == {"chain", "fan-out", "route"}

    # Route is flexible topology (variable specialist count)
    route = next(p for p in data["patterns"] if p["name"] == "route")
    assert route["fixed_topology"] is False
    assert route["min_agents"] == 3
    assert route["max_agents"] == 10

    # Agents -- sorted by name, with enriched fields
    assert len(data["agents"]) == 2
    agent_names = [a["name"] for a in data["agents"]]
    assert agent_names == ["fetcher", "summarizer"]  # sorted

    # Each agent carries model, tags, features
    for agent in data["agents"]:
        assert "model" in agent
        assert isinstance(agent["tags"], list)
        assert isinstance(agent["features"], list)
        assert isinstance(agent["path"], str)
        if agent["model"] is not None:
            assert "provider" in agent["model"]
            assert "name" in agent["model"]

    # Provider surface
    assert len(data["providers"]) > 0
    assert len(data["save_dirs"]) > 0
    assert isinstance(data["ollama_models"], list)


# -- POST /api/flow-builder/seed -------------------------------------------


def test_seed_pipeline_placeholders(client):
    tc, _ = client
    resp = tc.post(
        "/api/flow-builder/seed",
        json={
            "pattern": "chain",
            "name": "test-pipe",
            "agents": [
                {"slot": "step-1", "agent_id": None},
                {"slot": "step-2", "agent_id": None},
            ],
            "agent_count": 2,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "flow_yaml" in data
    assert len(data["role_yamls"]) == 2
    assert data["ready"] is True

    parsed = yaml.safe_load(data["flow_yaml"])
    assert parsed["kind"] == "Flow"
    assert len(parsed["spec"]["agents"]) == 2


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
        "/api/flow-builder/seed",
        json={
            "pattern": "chain",
            "name": "test-mixed",
            "agents": [
                {"slot": "step-1", "agent_id": agent_id},
                {"slot": "step-2", "agent_id": None},
            ],
            "agent_count": 2,
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
        "/api/flow-builder/seed",
        json={
            "pattern": "route",
            "name": "test-route",
            "agents": [
                {"slot": "intake", "agent_id": None},
                {"slot": "researcher", "agent_id": None},
                {"slot": "responder", "agent_id": None},
                {"slot": "escalator", "agent_id": None},
            ],
            "agent_count": 4,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    parsed = yaml.safe_load(data["flow_yaml"])
    expected = {"intake", "researcher", "responder", "escalator"}
    assert set(parsed["spec"]["agents"].keys()) == expected


def test_seed_invalid_pattern(client):
    tc, _ = client
    resp = tc.post(
        "/api/flow-builder/seed",
        json={
            "pattern": "bogus",
            "name": "test",
            "agents": [],
            "agent_count": 2,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    assert resp.status_code == 400


def test_seed_shared_memory(client):
    tc, _ = client
    resp = tc.post(
        "/api/flow-builder/seed",
        json={
            "pattern": "chain",
            "name": "test-sm",
            "agents": [
                {"slot": "step-1", "agent_id": None},
                {"slot": "step-2", "agent_id": None},
            ],
            "agent_count": 2,
            "shared_memory": True,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    parsed = yaml.safe_load(resp.json()["flow_yaml"])
    assert parsed["spec"]["shared_memory"]["enabled"] is True


def test_seed_route_with_routing_strategy(client):
    """Route pattern respects the routing_strategy parameter."""
    tc, _ = client
    for strategy in ("all", "keyword", "sense"):
        resp = tc.post(
            "/api/flow-builder/seed",
            json={
                "pattern": "route",
                "name": f"test-{strategy}",
                "agents": [
                    {"slot": "intake", "agent_id": None},
                    {"slot": "researcher", "agent_id": None},
                    {"slot": "responder", "agent_id": None},
                ],
                "agent_count": 3,
                "shared_memory": False,
                "provider": "openai",
                "routing_strategy": strategy,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        parsed = yaml.safe_load(data["flow_yaml"])
        sink = parsed["spec"]["agents"]["intake"]["sink"]
        assert sink["strategy"] == strategy


def test_seed_route_variable_agent_count(client):
    """Route pattern supports variable specialist count (3-10)."""
    tc, _ = client
    resp = tc.post(
        "/api/flow-builder/seed",
        json={
            "pattern": "route",
            "name": "test-five",
            "agents": [
                {"slot": "intake", "agent_id": None},
                {"slot": "researcher", "agent_id": None},
                {"slot": "responder", "agent_id": None},
                {"slot": "escalator", "agent_id": None},
                {"slot": "analyst", "agent_id": None},
            ],
            "agent_count": 5,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    parsed = yaml.safe_load(data["flow_yaml"])
    agents = parsed["spec"]["agents"]
    assert len(agents) == 5
    assert "intake" in agents
    sink = agents["intake"]["sink"]
    assert len(sink["target"]) == 4


def test_seed_route_defaults_to_sense(client):
    """Route pattern defaults to 'sense' strategy when routing_strategy is omitted."""
    tc, _ = client
    resp = tc.post(
        "/api/flow-builder/seed",
        json={
            "pattern": "route",
            "name": "test-default",
            "agents": [
                {"slot": "intake", "agent_id": None},
                {"slot": "researcher", "agent_id": None},
                {"slot": "responder", "agent_id": None},
            ],
            "agent_count": 3,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    parsed = yaml.safe_load(resp.json()["flow_yaml"])
    assert parsed["spec"]["agents"]["intake"]["sink"]["strategy"] == "sense"


# -- POST /api/flow-builder/validate ----------------------------------------


def test_validate_valid_yaml(client):
    tc, _ = client
    seed_resp = tc.post(
        "/api/flow-builder/seed",
        json={
            "pattern": "chain",
            "name": "v",
            "agents": [{"slot": "step-1"}, {"slot": "step-2"}],
            "agent_count": 2,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    yaml_text = seed_resp.json()["flow_yaml"]

    resp = tc.post("/api/flow-builder/validate", json={"yaml_text": yaml_text})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert len(data["issues"]) == 0


def test_validate_invalid_yaml(client):
    tc, _ = client
    resp = tc.post("/api/flow-builder/validate", json={"yaml_text": "not: valid: yaml: ["})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is False
    assert len(data["issues"]) > 0


def test_validate_missing_spec(client):
    tc, _ = client
    resp = tc.post(
        "/api/flow-builder/validate",
        json={"yaml_text": "apiVersion: initrunner/v1\nkind: Flow\nmetadata:\n  name: x\n"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is False


# -- POST /api/flow-builder/save -------------------------------------------


def test_save_flow(client, tmp_path):
    tc, _ = client
    seed_resp = tc.post(
        "/api/flow-builder/seed",
        json={
            "pattern": "chain",
            "name": "saved",
            "agents": [{"slot": "step-1"}, {"slot": "step-2"}],
            "agent_count": 2,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    seed_data = seed_resp.json()

    resp = tc.post(
        "/api/flow-builder/save",
        json={
            "flow_yaml": seed_data["flow_yaml"],
            "role_yamls": seed_data["role_yamls"],
            "directory": str(tmp_path),
            "project_name": "saved",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert "flow_id" in data
    assert len(data["next_steps"]) > 0
    assert (tmp_path / "saved" / "flow.yaml").exists()


def test_save_conflict(client, tmp_path):
    tc, _ = client
    seed_resp = tc.post(
        "/api/flow-builder/seed",
        json={
            "pattern": "chain",
            "name": "dup",
            "agents": [{"slot": "step-1"}, {"slot": "step-2"}],
            "agent_count": 2,
            "shared_memory": False,
            "provider": "openai",
        },
    )
    seed_data = seed_resp.json()

    tc.post(
        "/api/flow-builder/save",
        json={
            "flow_yaml": seed_data["flow_yaml"],
            "role_yamls": seed_data["role_yamls"],
            "directory": str(tmp_path),
            "project_name": "dup",
        },
    )

    resp = tc.post(
        "/api/flow-builder/save",
        json={
            "flow_yaml": seed_data["flow_yaml"],
            "role_yamls": seed_data["role_yamls"],
            "directory": str(tmp_path),
            "project_name": "dup",
        },
    )
    assert resp.status_code == 409
