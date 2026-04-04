"""Tests for /api/flows routes."""

from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.deps import FlowCache, RoleCache, get_flow_cache, get_role_cache
from initrunner.services.flow import build_flow


def _write_flow(tmp_path: Path, name: str = "test-flow") -> Path:
    """Generate and write a valid flow project, return flow.yaml path."""
    bundle = build_flow(name, pattern="chain", agent_count=2, provider="openai")

    project_dir = tmp_path / name
    roles_dir = project_dir / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    flow_path = project_dir / "flow.yaml"
    flow_path.write_text(bundle.flow_yaml)
    for filename, role_yaml in bundle.role_yamls.items():
        (roles_dir / filename).write_text(role_yaml)
    return flow_path


class _IsolatedRoleCache(RoleCache):
    """RoleCache that only scans specific dirs (no cwd/examples)."""

    def __init__(self, dirs: list[Path]):
        settings = DashboardSettings()
        self._settings = settings
        self._dirs = dirs
        self._cache: dict = {}

    def refresh(self):
        from initrunner.services.discovery import discover_roles_sync

        roles = discover_roles_sync(self._dirs)
        from initrunner.dashboard.deps import _role_id

        self._cache = {_role_id(r.path): r for r in roles}
        return self._cache


class _IsolatedFlowCache(FlowCache):
    """FlowCache that only scans specific dirs (no cwd/examples)."""

    def __init__(self, dirs: list[Path]):
        settings = DashboardSettings()
        self._settings = settings
        self._dirs = dirs
        self._cache: dict = {}

    def refresh(self):
        from initrunner.dashboard.deps import _flow_id
        from initrunner.services.discovery import discover_flows_sync

        flows = discover_flows_sync(self._dirs)
        self._cache = {_flow_id(c.path): c for c in flows}
        return self._cache


@pytest.fixture
def flow_dir(tmp_path):
    """Temp dir with a valid flow project."""
    _write_flow(tmp_path)
    return tmp_path


@pytest.fixture
def client(flow_dir):
    """Test client with isolated caches pointing at flow_dir only."""
    settings = DashboardSettings()
    app = create_app(settings)

    role_cache = _IsolatedRoleCache([flow_dir])
    role_cache.refresh()
    flow_cache = _IsolatedFlowCache([flow_dir])
    flow_cache.refresh()

    app.dependency_overrides[get_role_cache] = lambda: role_cache
    app.dependency_overrides[get_flow_cache] = lambda: flow_cache

    return TestClient(app)


# -- GET /api/flows ----------------------------------------------------------


def test_list_flows(client):
    resp = client.get("/api/flows")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    first = data[0]
    assert first["name"] == "test-flow"
    assert first["agent_count"] == 2
    assert set(first["agent_names"]) == {"step-1", "step-2"}


def test_list_flows_empty(tmp_path):
    """Empty dir yields empty list."""
    settings = DashboardSettings()
    app = create_app(settings)

    flow_cache = _IsolatedFlowCache([tmp_path])
    flow_cache.refresh()
    app.dependency_overrides[get_flow_cache] = lambda: flow_cache

    resp = TestClient(app).get("/api/flows")
    assert resp.status_code == 200
    assert resp.json() == []


# -- GET /api/flows/{id} -----------------------------------------------------


def test_get_flow_detail(client):
    flows = client.get("/api/flows").json()
    fid = flows[0]["id"]

    resp = client.get(f"/api/flows/{fid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "test-flow"
    assert len(data["agents"]) == 2
    agent_names = {s["name"] for s in data["agents"]}
    assert agent_names == {"step-1", "step-2"}


def test_get_flow_not_found(client):
    resp = client.get("/api/flows/nonexistent")
    assert resp.status_code == 404


# -- GET /api/flows/{id}/yaml ------------------------------------------------


def test_get_flow_yaml(client):
    flows = client.get("/api/flows").json()
    fid = flows[0]["id"]

    resp = client.get(f"/api/flows/{fid}/yaml")
    assert resp.status_code == 200
    data = resp.json()
    assert "yaml" in data
    assert "flow.yaml" in data["path"]
    parsed = yaml.safe_load(data["yaml"])
    assert parsed["kind"] == "Flow"


# -- GET /api/flows/{id}/events ----------------------------------------------


def test_get_flow_events_empty(client):
    """No events returns empty list."""
    flows = client.get("/api/flows").json()
    fid = flows[0]["id"]

    resp = client.get(f"/api/flows/{fid}/events")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_flow_events_field_names(client):
    """Non-empty events use source_agent/target_agent field names."""
    from unittest.mock import patch

    from initrunner.dashboard.schemas import DelegateEventResponse

    mock_events = [
        DelegateEventResponse(
            timestamp="2026-04-04T12:00:00Z",
            source_agent="inbox-watcher",
            target_agent="triager",
            status="delivered",
            source_run_id="run-1",
            flow_name="test-flow",
            reason=None,
            trace=None,
            payload_preview="hello",
        )
    ]

    flows = client.get("/api/flows").json()
    fid = flows[0]["id"]

    with patch("initrunner.dashboard.routers.flow._query_events", return_value=mock_events):
        resp = client.get(f"/api/flows/{fid}/events")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    event = data[0]
    assert "source_agent" in event
    assert "target_agent" in event
    assert event["source_agent"] == "inbox-watcher"
    assert event["target_agent"] == "triager"
    assert "source_service" not in event
    assert "target_service" not in event


# -- DELETE /api/flows/{id} --------------------------------------------------


def test_delete_flow(client, flow_dir):
    """DELETE removes the flow YAML and evicts from cache."""
    flows = client.get("/api/flows").json()
    fid = flows[0]["id"]
    flow_path = flows[0]["path"]

    resp = client.delete(f"/api/flows/{fid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == fid
    assert not Path(flow_path).exists()

    # Should be gone from cache
    resp = client.get(f"/api/flows/{fid}")
    assert resp.status_code == 404


def test_delete_flow_not_found(client):
    resp = client.delete("/api/flows/nonexistent")
    assert resp.status_code == 404
