"""Shared fixtures for dashboard tests."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.deps import RoleCache, _role_id, get_role_cache


def _make_discovered_role(path: str, name: str = "test-agent", error: str | None = None):
    """Create a mock DiscoveredRole."""
    dr = MagicMock()
    dr.path = Path(path)
    dr.error = error
    if error:
        dr.role = None
    else:
        dr.role = MagicMock()
        dr.role.metadata.name = name
        dr.role.metadata.description = f"Description of {name}"
        dr.role.metadata.tags = ["test"]
        dr.role.spec.model.provider = "openai"
        dr.role.spec.model.name = "gpt-4o"
        dr.role.spec.features = ["memory", "tools"]
    return dr


class MockRoleCache(RoleCache):
    """RoleCache that skips real discovery in refresh()."""

    def __init__(self, roles):
        self._settings = DashboardSettings()
        self._cache = {_role_id(r.path): r for r in roles}
        self._mock_roles = roles

    def refresh(self):
        # Return existing cache without scanning the filesystem
        return self._cache


@pytest.fixture
def mock_roles():
    """Two mock discovered roles."""
    return [
        _make_discovered_role("/tmp/roles/agent-a.yaml", "agent-a"),
        _make_discovered_role("/tmp/roles/agent-b.yaml", "agent-b"),
    ]


@pytest.fixture
def app(mock_roles):
    """Create a test FastAPI app with mock roles."""
    settings = DashboardSettings()
    application = create_app(settings)

    cache = MockRoleCache(mock_roles)
    application.dependency_overrides[get_role_cache] = lambda: cache

    return application


@pytest.fixture
def client(app):
    """Synchronous test client."""
    from starlette.testclient import TestClient

    return TestClient(app)
