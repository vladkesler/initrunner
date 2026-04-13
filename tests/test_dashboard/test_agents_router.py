"""Tests for /api/agents routes."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.agent.schema.base import ModelConfig
from initrunner.agent.schema.guardrails import Guardrails
from initrunner.agent.schema.output import OutputConfig
from initrunner.dashboard.deps import _role_id, get_role_cache
from tests.test_dashboard.conftest import MockRoleCache


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


def _make_detail_role(path: str, name: str, provider: str = "openai", model: str = "gpt-4o"):
    """Create a mock DiscoveredRole with real Pydantic models for _detail_from."""
    dr = MagicMock()
    dr.path = Path(path)
    dr.error = None
    dr.role.metadata.name = name
    dr.role.metadata.description = f"Description of {name}"
    dr.role.metadata.tags = ["test"]
    dr.role.metadata.author = ""
    dr.role.metadata.team = ""
    dr.role.metadata.version = ""
    dr.role.spec.model = ModelConfig(provider=provider, name=model)
    dr.role.spec.output = OutputConfig()
    dr.role.spec.guardrails = Guardrails()
    dr.role.spec.memory = None
    dr.role.spec.ingest = None
    dr.role.spec.reasoning = None
    dr.role.spec.autonomy = None
    dr.role.spec.tools = []
    dr.role.spec.triggers = []
    dr.role.spec.sinks = []
    dr.role.spec.capabilities = []
    dr.role.spec.skills = []
    dr.role.spec.features = []
    dr.role.spec.tool_search = MagicMock(enabled=False)
    dr.role.spec.security.effective_label = "default"
    return dr


def test_agent_detail_provider_warning_sdk_missing(client):
    """provider_warning is populated when the provider SDK is not installed."""
    role = _make_detail_role("/tmp/roles/agent-c.yaml", "agent-c", provider="anthropic")
    cache = MockRoleCache([role])
    client.app.dependency_overrides[get_role_cache] = lambda: cache
    agent_id = _role_id(Path("/tmp/roles/agent-c.yaml"))

    with (
        patch("initrunner.agent.loader._load_dotenv"),
        patch(
            "initrunner._compat.require_provider",
            side_effect=RuntimeError(
                "Provider 'anthropic' requires: uv pip install initrunner[anthropic]"
            ),
        ),
    ):
        resp = client.get(f"/api/agents/{agent_id}/detail")

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider_warning"] is not None
    assert "anthropic" in data["provider_warning"]
    assert "uv pip install" in data["provider_warning"]


def test_agent_detail_provider_warning_none_when_ready(client, monkeypatch):
    """provider_warning is null when provider SDK and API key are available."""
    role = _make_detail_role("/tmp/roles/agent-d.yaml", "agent-d", provider="openai")
    cache = MockRoleCache([role])
    client.app.dependency_overrides[get_role_cache] = lambda: cache
    agent_id = _role_id(Path("/tmp/roles/agent-d.yaml"))

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch("initrunner.agent.loader._load_dotenv"):
        resp = client.get(f"/api/agents/{agent_id}/detail")

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider_warning"] is None


def test_agent_detail_tool_search_exposed(client, monkeypatch):
    """tool_search is included in detail when enabled."""
    role = _make_detail_role("/tmp/roles/agent-ts.yaml", "agent-ts", provider="openai")
    # Enable tool_search on the mock
    role.role.spec.tool_search = MagicMock(
        enabled=True,
        model_dump=lambda: {
            "enabled": True,
            "always_available": ["current_time"],
            "max_results": 5,
            "threshold": 0.0,
        },
    )
    role.role.spec.features = ["tools", "tool_search"]
    cache = MockRoleCache([role])
    client.app.dependency_overrides[get_role_cache] = lambda: cache
    agent_id = _role_id(Path("/tmp/roles/agent-ts.yaml"))

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch("initrunner.agent.loader._load_dotenv"):
        resp = client.get(f"/api/agents/{agent_id}/detail")

    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_search"] is not None
    assert data["tool_search"]["enabled"] is True
    assert data["tool_search"]["always_available"] == ["current_time"]
    assert "tool_search" in data["features"]


def test_agent_detail_tool_search_null_when_disabled(client, monkeypatch):
    """tool_search is null in detail when disabled."""
    role = _make_detail_role("/tmp/roles/agent-nts.yaml", "agent-nts", provider="openai")
    cache = MockRoleCache([role])
    client.app.dependency_overrides[get_role_cache] = lambda: cache
    agent_id = _role_id(Path("/tmp/roles/agent-nts.yaml"))

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch("initrunner.agent.loader._load_dotenv"):
        resp = client.get(f"/api/agents/{agent_id}/detail")

    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_search"] is None
