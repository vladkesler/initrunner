"""Tests for /api/team-builder routes."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.deps import TeamCache, _file_id, get_team_cache


class _IsolatedTeamCache(TeamCache):
    """TeamCache that only scans specific dirs."""

    def __init__(self, dirs: list[Path]):
        settings = DashboardSettings()
        self._settings = settings
        self._discover_fn = None
        self._path_attr = "path"
        self._dirs = dirs
        self._cache: dict = {}

    def refresh(self):
        from initrunner.services.discovery import discover_teams_sync

        teams = discover_teams_sync(self._dirs)
        self._cache = {_file_id(t.path): t for t in teams}
        return self._cache


@pytest.fixture
def save_dir(tmp_path):
    """Temp dir that acts as an allowed save directory."""
    d = tmp_path / "teams"
    d.mkdir()
    return d


@pytest.fixture
def client(save_dir, monkeypatch):
    """Test client with isolated team cache."""
    settings = DashboardSettings()

    # Monkey-patch get_role_dirs so our tmp dir is allowed
    monkeypatch.setattr(settings, "get_role_dirs", lambda: [save_dir])

    app = create_app(settings)
    cache = _IsolatedTeamCache([save_dir])
    cache.refresh()
    app.dependency_overrides[get_team_cache] = lambda: cache
    return TestClient(app)


def test_seed_blank(client):
    resp = client.post(
        "/api/team-builder/seed",
        json={
            "mode": "blank",
            "name": "my-team",
            "strategy": "sequential",
            "persona_count": 3,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "yaml_text" in data
    assert data["ready"] is True
    assert "my-team" in data["yaml_text"]
    assert "sequential" in data["yaml_text"]


def test_seed_parallel(client):
    resp = client.post(
        "/api/team-builder/seed",
        json={
            "mode": "blank",
            "name": "par-team",
            "strategy": "parallel",
            "persona_count": 4,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "parallel" in data["yaml_text"]


def test_validate_valid_yaml(client):
    from initrunner.services.team_builder import build_blank_team_yaml

    yaml_text = build_blank_team_yaml("valid-team", provider="openai")
    resp = client.post(
        "/api/team-builder/validate",
        json={"yaml_text": yaml_text},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    # May have info-level issues but no errors
    errors = [i for i in data["issues"] if i["severity"] == "error"]
    assert len(errors) == 0


def test_validate_invalid_yaml(client):
    resp = client.post(
        "/api/team-builder/validate",
        json={"yaml_text": "not valid yaml: ["},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is False
    assert len(data["issues"]) > 0


def test_validate_missing_personas(client):
    yaml_text = """
apiVersion: initrunner/v1
kind: Team
metadata:
  name: bad-team
spec:
  model:
    provider: openai
    name: gpt-5-mini
  personas:
    solo: "only one persona"
"""
    resp = client.post(
        "/api/team-builder/validate",
        json={"yaml_text": yaml_text},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is False
    errors = [i for i in data["issues"] if i["severity"] == "error"]
    assert len(errors) > 0


def test_save_team(save_dir, monkeypatch):
    from initrunner.services.team_builder import build_blank_team_yaml

    yaml_text = build_blank_team_yaml("saved-team", provider="openai")

    # Patch DashboardSettings at import source so the lazy import inside
    # the router endpoint picks up our mock.
    _OrigSettings = DashboardSettings
    mock_settings = _OrigSettings()
    monkeypatch.setattr(mock_settings, "get_role_dirs", lambda: [save_dir])
    monkeypatch.setattr(
        "initrunner.dashboard.config.DashboardSettings",
        lambda: mock_settings,
    )

    app = create_app(mock_settings)
    cache = _IsolatedTeamCache([save_dir])
    cache.refresh()
    app.dependency_overrides[get_team_cache] = lambda: cache
    c = TestClient(app)

    resp = c.post(
        "/api/team-builder/save",
        json={
            "yaml_text": yaml_text,
            "directory": str(save_dir),
            "filename": "saved-team.yaml",
            "force": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["team_id"] != ""
    assert "saved-team.yaml" in data["path"]
    assert len(data["next_steps"]) > 0

    # File was written
    assert (save_dir / "saved-team.yaml").exists()


def test_save_conflict(save_dir, monkeypatch):
    from initrunner.services.team_builder import build_blank_team_yaml

    yaml_text = build_blank_team_yaml("conflict-team", provider="openai")

    mock_settings = DashboardSettings()
    monkeypatch.setattr(mock_settings, "get_role_dirs", lambda: [save_dir])
    monkeypatch.setattr(
        "initrunner.dashboard.config.DashboardSettings",
        lambda: mock_settings,
    )

    app = create_app(mock_settings)
    cache = _IsolatedTeamCache([save_dir])
    cache.refresh()
    app.dependency_overrides[get_team_cache] = lambda: cache
    c = TestClient(app)

    # Write the file first
    (save_dir / "conflict-team.yaml").write_text("existing content")

    resp = c.post(
        "/api/team-builder/save",
        json={
            "yaml_text": yaml_text,
            "directory": str(save_dir),
            "filename": "conflict-team.yaml",
            "force": False,
        },
    )
    assert resp.status_code == 409


def test_options_endpoint(client):
    resp = client.get("/api/team-builder/options")
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    assert "save_dirs" in data


# -- Structured persona tests -------------------------------------------------


def test_seed_with_personas(client):
    """Structured personas produce YAML with custom names and roles."""
    resp = client.post(
        "/api/team-builder/seed",
        json={
            "mode": "blank",
            "name": "custom-team",
            "strategy": "sequential",
            "persona_count": 2,
            "personas": [
                {"name": "code-reviewer", "role": "Review code for bugs"},
                {"name": "security-auditor", "role": "Check for vulnerabilities"},
            ],
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    yaml_text = data["yaml_text"]
    assert "code-reviewer" in yaml_text
    assert "security-auditor" in yaml_text
    assert "Review code for bugs" in yaml_text
    assert "Check for vulnerabilities" in yaml_text


def test_seed_with_model_override(client):
    """Persona with model override generates long-form YAML with model block."""
    resp = client.post(
        "/api/team-builder/seed",
        json={
            "mode": "blank",
            "name": "override-team",
            "strategy": "parallel",
            "persona_count": 2,
            "personas": [
                {
                    "name": "fast-thinker",
                    "role": "Quick analysis",
                    "model": {
                        "provider": "anthropic",
                        "name": "claude-haiku-4-5-20251001",
                    },
                },
                {"name": "deep-thinker", "role": "Deep analysis"},
            ],
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    yaml_text = data["yaml_text"]
    assert "fast-thinker:" in yaml_text
    assert "claude-haiku-4-5-20251001" in yaml_text
    assert "anthropic" in yaml_text
    # deep-thinker should NOT have a model block
    assert "deep-thinker:" in yaml_text
    assert "Deep analysis" in yaml_text


def test_seed_custom_preset_resolution(client):
    """Persona with openrouter preset resolves to provider: openai + base_url."""
    resp = client.post(
        "/api/team-builder/seed",
        json={
            "mode": "blank",
            "name": "preset-team",
            "strategy": "sequential",
            "persona_count": 2,
            "personas": [
                {
                    "name": "router-persona",
                    "role": "Uses OpenRouter",
                    "model": {
                        "provider": "openrouter",
                        "name": "anthropic/claude-sonnet-4",
                    },
                },
                {"name": "default-persona", "role": "Uses team model"},
            ],
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    yaml_text = resp.json()["yaml_text"]
    # openrouter should resolve to openai with base_url
    assert "openrouter.ai" in yaml_text
    assert "OPENROUTER_API_KEY" in yaml_text
    # The provider in the persona's model block should be "openai", not "openrouter"
    import yaml

    parsed = yaml.safe_load(yaml_text)
    persona_cfg = parsed["spec"]["personas"]["router-persona"]
    assert persona_cfg["model"]["provider"] == "openai"


def test_seed_backwards_compat(client):
    """Request without personas field works identically to before."""
    resp = client.post(
        "/api/team-builder/seed",
        json={
            "mode": "blank",
            "name": "compat-team",
            "strategy": "sequential",
            "persona_count": 3,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    yaml_text = data["yaml_text"]
    # Should use default persona names
    assert "analyst" in yaml_text
    assert "reviewer" in yaml_text
    assert "advisor" in yaml_text


def test_seed_personas_take_precedence(client):
    """When both personas and persona_count are provided, personas wins."""
    resp = client.post(
        "/api/team-builder/seed",
        json={
            "mode": "blank",
            "name": "precedence-team",
            "strategy": "sequential",
            "persona_count": 5,
            "personas": [
                {"name": "alpha", "role": "First"},
                {"name": "beta", "role": "Second"},
            ],
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    yaml_text = resp.json()["yaml_text"]
    import yaml

    parsed = yaml.safe_load(yaml_text)
    assert list(parsed["spec"]["personas"].keys()) == ["alpha", "beta"]


# -- Service unit tests -------------------------------------------------------


def test_build_blank_with_structured_personas():
    """Service function with personas produces correct YAML."""
    from initrunner.services.team_builder import build_blank_team_yaml

    yaml_text = build_blank_team_yaml(
        name="svc-team",
        strategy="sequential",
        provider="openai",
        personas=[
            {"name": "writer", "role": "Write content"},
            {"name": "editor", "role": "Edit content"},
        ],
    )
    import yaml

    parsed = yaml.safe_load(yaml_text)
    personas = parsed["spec"]["personas"]
    assert list(personas.keys()) == ["writer", "editor"]
    assert personas["writer"] == "Write content"
    assert personas["editor"] == "Edit content"


def test_build_blank_with_model_override_persona():
    """Service function with model override produces nested persona config."""
    from initrunner.services.team_builder import build_blank_team_yaml

    yaml_text = build_blank_team_yaml(
        name="override-svc",
        strategy="parallel",
        provider="openai",
        personas=[
            {
                "name": "smart-one",
                "role": "Deep thinking",
                "model": {
                    "provider": "anthropic",
                    "name": "claude-opus-4-6",
                },
            },
            {"name": "fast-one", "role": "Quick thinking"},
        ],
    )
    import yaml

    parsed = yaml.safe_load(yaml_text)
    personas = parsed["spec"]["personas"]
    assert personas["smart-one"]["role"] == "Deep thinking"
    assert personas["smart-one"]["model"]["provider"] == "anthropic"
    assert personas["smart-one"]["model"]["name"] == "claude-opus-4-6"
    assert personas["fast-one"] == "Quick thinking"


def test_build_blank_preserves_order():
    """Persona order in output matches input list order."""
    from initrunner.services.team_builder import build_blank_team_yaml

    yaml_text = build_blank_team_yaml(
        name="order-team",
        strategy="sequential",
        provider="openai",
        personas=[
            {"name": "zulu", "role": "Last alphabetically"},
            {"name": "alpha", "role": "First alphabetically"},
            {"name": "mike", "role": "Middle"},
        ],
    )
    import yaml

    parsed = yaml.safe_load(yaml_text)
    assert list(parsed["spec"]["personas"].keys()) == ["zulu", "alpha", "mike"]


def test_build_blank_fallback_to_count():
    """When personas=None, falls back to persona_count behavior."""
    from initrunner.services.team_builder import build_blank_team_yaml

    yaml_text = build_blank_team_yaml(
        name="count-team",
        persona_count=4,
        provider="openai",
    )
    import yaml

    parsed = yaml.safe_load(yaml_text)
    personas = parsed["spec"]["personas"]
    assert len(personas) == 4
    assert list(personas.keys()) == ["analyst", "reviewer", "advisor", "checker"]


# -- Shared helper test -------------------------------------------------------


def test_resolve_custom_provider():
    """Custom presets resolve to openai with injected base_url/api_key_env."""
    from initrunner.dashboard.routers._provider_options import resolve_custom_provider

    # OpenRouter preset
    prov, burl, akenv = resolve_custom_provider("openrouter", None, None)
    assert prov == "openai"
    assert "openrouter.ai" in burl
    assert akenv == "OPENROUTER_API_KEY"

    # Standard provider passes through
    prov, burl, akenv = resolve_custom_provider("anthropic", None, None)
    assert prov == "anthropic"
    assert burl is None
    assert akenv is None

    # Explicit base_url not overridden
    prov, burl, akenv = resolve_custom_provider("openrouter", "https://my.proxy/v1", None)
    assert prov == "openai"
    assert burl == "https://my.proxy/v1"
