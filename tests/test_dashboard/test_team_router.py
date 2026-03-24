"""Tests for /api/teams routes."""

from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.deps import (
    TeamCache,
    _file_id,
    get_team_cache,
)


def _write_team(
    tmp_path: Path,
    name: str = "test-team",
    strategy: str = "sequential",
) -> Path:
    """Write a valid team YAML file and return its path."""
    team_yaml = {
        "apiVersion": "initrunner/v1",
        "kind": "Team",
        "metadata": {"name": name, "description": f"Test team: {name}"},
        "spec": {
            "model": {"provider": "openai", "name": "gpt-5-mini"},
            "strategy": strategy,
            "personas": {
                "analyst": "Analyze the data",
                "reviewer": "Review the analysis",
            },
            "tools": [],
            "guardrails": {
                "max_tokens_per_run": 50000,
                "timeout_seconds": 300,
            },
        },
    }
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.dump(team_yaml, sort_keys=False))
    return path


class _IsolatedTeamCache(TeamCache):
    """TeamCache that only scans specific dirs (no cwd/examples)."""

    def __init__(self, dirs: list[Path]):
        settings = DashboardSettings()
        self._settings = settings
        self._discover_fn = None  # overridden by refresh
        self._path_attr = "path"
        self._dirs = dirs
        self._cache: dict = {}

    def refresh(self):
        from initrunner.services.discovery import discover_teams_sync

        teams = discover_teams_sync(self._dirs)
        self._cache = {_file_id(t.path): t for t in teams}
        return self._cache


@pytest.fixture
def team_dir(tmp_path):
    """Temp dir with a valid team YAML file."""
    _write_team(tmp_path)
    return tmp_path


@pytest.fixture
def client(team_dir):
    """Test client with isolated team cache pointing at team_dir."""
    settings = DashboardSettings()
    app = create_app(settings)

    team_cache = _IsolatedTeamCache([team_dir])
    team_cache.refresh()
    app.dependency_overrides[get_team_cache] = lambda: team_cache

    return TestClient(app)


def test_list_teams(client):
    resp = client.get("/api/teams")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    team = data[0]
    assert team["name"] == "test-team"
    assert team["strategy"] == "sequential"
    assert team["persona_count"] == 2
    assert set(team["persona_names"]) == {"analyst", "reviewer"}
    assert team["provider"] == "openai"
    assert team["model"] == "gpt-5-mini"
    assert team["has_model_overrides"] is False
    assert team["error"] is None


def test_list_teams_empty(tmp_path):
    settings = DashboardSettings()
    app = create_app(settings)
    cache = _IsolatedTeamCache([tmp_path])
    cache.refresh()
    app.dependency_overrides[get_team_cache] = lambda: cache
    c = TestClient(app)
    resp = c.get("/api/teams")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_team_detail(client, team_dir):
    # Get the team ID
    teams = client.get("/api/teams").json()
    tid = teams[0]["id"]

    resp = client.get(f"/api/teams/{tid}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["name"] == "test-team"
    assert detail["strategy"] == "sequential"
    assert len(detail["personas"]) == 2
    assert detail["guardrails"]["max_tokens_per_run"] == 50000
    assert detail["handoff_max_chars"] == 4000  # default


def test_get_team_not_found(client):
    resp = client.get("/api/teams/nonexistent")
    assert resp.status_code == 404


def test_get_team_yaml(client):
    teams = client.get("/api/teams").json()
    tid = teams[0]["id"]

    resp = client.get(f"/api/teams/{tid}/yaml")
    assert resp.status_code == 200
    data = resp.json()
    assert "yaml" in data
    assert "path" in data
    assert "kind: Team" in data["yaml"]


def test_put_team_yaml(client, team_dir):
    teams = client.get("/api/teams").json()
    tid = teams[0]["id"]

    # Get current YAML and modify description
    current = client.get(f"/api/teams/{tid}/yaml").json()
    modified = current["yaml"].replace("Test team: test-team", "Updated description")

    resp = client.put(
        f"/api/teams/{tid}/yaml",
        json={"yaml_text": modified},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True

    # Verify the change persisted
    after = client.get(f"/api/teams/{tid}/yaml").json()
    assert "Updated description" in after["yaml"]


def test_put_team_yaml_invalid(client, team_dir):
    teams = client.get("/api/teams").json()
    tid = teams[0]["id"]

    resp = client.put(
        f"/api/teams/{tid}/yaml",
        json={"yaml_text": "invalid: yaml: content: ["},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert len(data["issues"]) > 0


def test_team_with_model_overrides(tmp_path):
    """Teams with per-persona model overrides set has_model_overrides=True."""
    team_yaml = {
        "apiVersion": "initrunner/v1",
        "kind": "Team",
        "metadata": {"name": "mixed-team"},
        "spec": {
            "model": {"provider": "openai", "name": "gpt-5-mini"},
            "personas": {
                "analyst": {
                    "role": "Analyze data",
                    "model": {"provider": "anthropic", "name": "claude-sonnet-4-6"},
                },
                "reviewer": "Review the analysis",
            },
        },
    }
    path = tmp_path / "mixed-team.yaml"
    path.write_text(yaml.dump(team_yaml, sort_keys=False))

    settings = DashboardSettings()
    app = create_app(settings)
    cache = _IsolatedTeamCache([tmp_path])
    cache.refresh()
    app.dependency_overrides[get_team_cache] = lambda: cache
    c = TestClient(app)

    teams = c.get("/api/teams").json()
    assert len(teams) == 1
    assert teams[0]["has_model_overrides"] is True


def test_parallel_team(tmp_path):
    """Parallel teams are discovered and listed correctly."""
    _write_team(tmp_path, name="par-team", strategy="parallel")
    settings = DashboardSettings()
    app = create_app(settings)
    cache = _IsolatedTeamCache([tmp_path])
    cache.refresh()
    app.dependency_overrides[get_team_cache] = lambda: cache
    c = TestClient(app)

    teams = c.get("/api/teams").json()
    assert teams[0]["strategy"] == "parallel"


def test_discover_teams_sync(tmp_path):
    """discover_teams_sync finds Team YAML files and skips non-team YAML."""
    from initrunner.services.discovery import discover_teams_sync

    # Write a team file
    _write_team(tmp_path, name="found-team")

    # Write a non-team file (Agent)
    agent_yaml = {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": "not-a-team"},
        "spec": {"model": {"provider": "openai", "name": "gpt-5-mini"}, "role": "test"},
    }
    (tmp_path / "agent.yaml").write_text(yaml.dump(agent_yaml))

    # Write a non-initrunner YAML
    (tmp_path / "random.yaml").write_text("foo: bar")

    results = discover_teams_sync([tmp_path])
    assert len(results) == 1
    assert results[0].team is not None
    assert results[0].team.metadata.name == "found-team"


def test_team_cache_refresh(tmp_path):
    """TeamCache.refresh() populates the cache."""
    _write_team(tmp_path, name="cached-team")

    cache = _IsolatedTeamCache([tmp_path])
    result = cache.refresh()
    assert len(result) == 1

    # get() works
    tid = next(iter(result.keys()))
    found = cache.get(tid)
    assert found is not None
    assert found.team.metadata.name == "cached-team"

    # Unknown ID returns None
    assert cache.get("nonexistent") is None
