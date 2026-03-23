"""Tests for RoleCache and _role_id."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.dashboard.deps import RoleCache, _role_id


def test_role_id_deterministic():
    """Same path always produces the same ID."""
    p = Path("/some/path/role.yaml")
    assert _role_id(p) == _role_id(p)


def test_role_id_different_paths():
    """Different paths produce different IDs."""
    a = _role_id(Path("/dir1/role.yaml"))
    b = _role_id(Path("/dir2/role.yaml"))
    assert a != b


def test_role_id_length():
    """ID is 12 hex chars."""
    rid = _role_id(Path("/any/path.yaml"))
    assert len(rid) == 12
    assert all(c in "0123456789abcdef" for c in rid)


def test_role_cache_refresh():
    """refresh() populates the cache from discovered roles."""
    from initrunner.dashboard.config import DashboardSettings

    mock_role_a = MagicMock()
    mock_role_a.path = Path("/tmp/a/role.yaml")
    mock_role_a.role = MagicMock()
    mock_role_a.error = None

    mock_role_b = MagicMock()
    mock_role_b.path = Path("/tmp/b/role.yaml")
    mock_role_b.role = MagicMock()
    mock_role_b.error = None

    settings = DashboardSettings(extra_role_dirs=[Path("/tmp")])

    with (
        patch(
            "initrunner.services.discovery.discover_roles_sync",
            return_value=[mock_role_a, mock_role_b],
        ),
        patch.object(settings, "get_role_dirs", return_value=[Path("/tmp")]),
    ):
        cache = RoleCache(settings)
        result = cache.refresh()

    assert len(result) == 2
    id_a = _role_id(Path("/tmp/a/role.yaml"))
    id_b = _role_id(Path("/tmp/b/role.yaml"))
    assert cache.get(id_a) is mock_role_a
    assert cache.get(id_b) is mock_role_b


def test_role_cache_get_unknown():
    """get() returns None for unknown IDs."""
    from initrunner.dashboard.config import DashboardSettings

    settings = DashboardSettings()
    cache = RoleCache(settings)
    assert cache.get("nonexistent") is None


def test_same_name_different_dirs():
    """Two roles with the same metadata.name but different paths get different IDs."""
    p1 = Path("/dir1/agent.yaml")
    p2 = Path("/dir2/agent.yaml")
    assert _role_id(p1) != _role_id(p2)
