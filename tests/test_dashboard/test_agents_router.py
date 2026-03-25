"""Tests for /api/agents routes."""

from pathlib import Path

from initrunner.dashboard.deps import _role_id


def test_list_agents(client, mock_roles):
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    names = {a["name"] for a in data}
    assert names == {"agent-a", "agent-b"}
    # Every agent has an ID
    assert all(a["id"] for a in data)


def test_get_agent(client, mock_roles):
    agent_id = _role_id(Path("/tmp/roles/agent-a.yaml"))
    resp = client.get(f"/api/agents/{agent_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "agent-a"
    assert data["id"] == agent_id
    assert data["provider"] == "openai"


def test_get_agent_not_found(client):
    resp = client.get("/api/agents/doesnotexist")
    assert resp.status_code == 404


def test_get_agent_yaml(client, mock_roles, tmp_path):
    """YAML endpoint reads the file from disk."""
    yaml_content = "apiVersion: initrunner/v1\nkind: Agent\n"
    yaml_file = tmp_path / "agent-a.yaml"
    yaml_file.write_text(yaml_content)

    # Point the mock role's path to the real temp file
    dr = mock_roles[0]
    dr.path = yaml_file

    # Re-inject the cache with updated path
    from initrunner.dashboard.deps import RoleCache, get_role_cache

    cache = RoleCache.__new__(RoleCache)
    cache._settings = None
    cache._cache = {}
    for r in mock_roles:
        cache._cache[_role_id(r.path)] = r

    client.app.dependency_overrides[get_role_cache] = lambda: cache

    new_id = _role_id(yaml_file)
    resp = client.get(f"/api/agents/{new_id}/yaml")
    assert resp.status_code == 200
    assert resp.json()["yaml"] == yaml_content


def test_get_agent_yaml_not_found(client):
    resp = client.get("/api/agents/doesnotexist/yaml")
    assert resp.status_code == 404


def test_delete_agent(client, mock_roles, tmp_path):
    """DELETE /api/agents/{id} removes the YAML file and evicts from cache."""
    yaml_file = tmp_path / "agent-a.yaml"
    yaml_file.write_text("apiVersion: initrunner/v1\nkind: Agent\n")

    # Point the mock role's path to the real temp file
    mock_roles[0].path = yaml_file

    # Re-inject the cache with updated path
    from initrunner.dashboard.deps import RoleCache, get_role_cache

    cache = RoleCache.__new__(RoleCache)
    cache._settings = None
    cache._cache = {}
    for r in mock_roles:
        cache._cache[_role_id(r.path)] = r

    client.app.dependency_overrides[get_role_cache] = lambda: cache

    agent_id = _role_id(yaml_file)
    resp = client.delete(f"/api/agents/{agent_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == agent_id
    assert not yaml_file.exists()
    assert cache.get(agent_id) is None


def test_delete_agent_not_found(client):
    resp = client.delete("/api/agents/doesnotexist")
    assert resp.status_code == 404
