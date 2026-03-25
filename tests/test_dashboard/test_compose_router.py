"""Tests for /api/compose routes."""

from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.deps import ComposeCache, RoleCache, get_compose_cache, get_role_cache
from initrunner.services.compose import build_compose


def _write_compose(tmp_path: Path, name: str = "test-compose") -> Path:
    """Generate and write a valid compose project, return compose.yaml path."""
    bundle = build_compose(name, pattern="pipeline", service_count=2, provider="openai")

    project_dir = tmp_path / name
    roles_dir = project_dir / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    compose_path = project_dir / "compose.yaml"
    compose_path.write_text(bundle.compose_yaml)
    for filename, role_yaml in bundle.role_yamls.items():
        (roles_dir / filename).write_text(role_yaml)
    return compose_path


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


class _IsolatedComposeCache(ComposeCache):
    """ComposeCache that only scans specific dirs (no cwd/examples)."""

    def __init__(self, dirs: list[Path]):
        settings = DashboardSettings()
        self._settings = settings
        self._dirs = dirs
        self._cache: dict = {}

    def refresh(self):
        from initrunner.dashboard.deps import _compose_id
        from initrunner.services.discovery import discover_composes_sync

        composes = discover_composes_sync(self._dirs)
        self._cache = {_compose_id(c.path): c for c in composes}
        return self._cache


@pytest.fixture
def compose_dir(tmp_path):
    """Temp dir with a valid compose project."""
    _write_compose(tmp_path)
    return tmp_path


@pytest.fixture
def client(compose_dir):
    """Test client with isolated caches pointing at compose_dir only."""
    settings = DashboardSettings()
    app = create_app(settings)

    role_cache = _IsolatedRoleCache([compose_dir])
    role_cache.refresh()
    compose_cache = _IsolatedComposeCache([compose_dir])
    compose_cache.refresh()

    app.dependency_overrides[get_role_cache] = lambda: role_cache
    app.dependency_overrides[get_compose_cache] = lambda: compose_cache

    return TestClient(app)


# -- GET /api/compose ----------------------------------------------------------


def test_list_composes(client):
    resp = client.get("/api/compose")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    first = data[0]
    assert first["name"] == "test-compose"
    assert first["service_count"] == 2
    assert set(first["service_names"]) == {"step-1", "step-2"}


def test_list_composes_empty(tmp_path):
    """Empty dir yields empty list."""
    settings = DashboardSettings()
    app = create_app(settings)

    compose_cache = _IsolatedComposeCache([tmp_path])
    compose_cache.refresh()
    app.dependency_overrides[get_compose_cache] = lambda: compose_cache

    resp = TestClient(app).get("/api/compose")
    assert resp.status_code == 200
    assert resp.json() == []


# -- GET /api/compose/{id} -----------------------------------------------------


def test_get_compose_detail(client):
    composes = client.get("/api/compose").json()
    cid = composes[0]["id"]

    resp = client.get(f"/api/compose/{cid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "test-compose"
    assert len(data["services"]) == 2
    svc_names = {s["name"] for s in data["services"]}
    assert svc_names == {"step-1", "step-2"}


def test_get_compose_not_found(client):
    resp = client.get("/api/compose/nonexistent")
    assert resp.status_code == 404


# -- GET /api/compose/{id}/yaml ------------------------------------------------


def test_get_compose_yaml(client):
    composes = client.get("/api/compose").json()
    cid = composes[0]["id"]

    resp = client.get(f"/api/compose/{cid}/yaml")
    assert resp.status_code == 200
    data = resp.json()
    assert "yaml" in data
    assert "compose.yaml" in data["path"]
    parsed = yaml.safe_load(data["yaml"])
    assert parsed["kind"] == "Compose"


# -- GET /api/compose/{id}/events ----------------------------------------------


def test_get_compose_events_empty(client):
    """No events returns empty list."""
    composes = client.get("/api/compose").json()
    cid = composes[0]["id"]

    resp = client.get(f"/api/compose/{cid}/events")
    assert resp.status_code == 200
    assert resp.json() == []


# -- DELETE /api/compose/{id} --------------------------------------------------


def test_delete_compose(client, compose_dir):
    """DELETE removes the compose YAML and evicts from cache."""
    composes = client.get("/api/compose").json()
    cid = composes[0]["id"]
    compose_path = composes[0]["path"]

    resp = client.delete(f"/api/compose/{cid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == cid
    assert not Path(compose_path).exists()

    # Should be gone from cache
    resp = client.get(f"/api/compose/{cid}")
    assert resp.status_code == 404


def test_delete_compose_not_found(client):
    resp = client.delete("/api/compose/nonexistent")
    assert resp.status_code == 404
