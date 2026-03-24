"""Tests for /api/builder routes."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.deps import RoleCache, get_role_cache


class _BuilderRoleCache(RoleCache):
    """RoleCache with configurable role dirs for builder tests."""

    def __init__(self, role_dirs: list[Path]):
        settings = DashboardSettings()
        settings.extra_role_dirs = list(role_dirs)
        self._settings = settings
        self._cache: dict = {}
        self._role_dirs = role_dirs

    def refresh(self):
        return self._cache


@pytest.fixture
def role_dir(tmp_path):
    """A temporary directory that acts as a role dir."""
    return tmp_path / "roles"


@pytest.fixture
def builder_client(role_dir):
    """Test client with a builder-friendly RoleCache."""
    role_dir.mkdir(parents=True, exist_ok=True)

    settings = DashboardSettings()
    app = create_app(settings)

    cache = _BuilderRoleCache([role_dir])
    app.dependency_overrides[get_role_cache] = lambda: cache

    return TestClient(app)


# -- GET /api/builder/templates ------------------------------------------------


def test_builder_options(builder_client):
    resp = builder_client.get("/api/builder/templates")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["templates"]) > 0
    assert any(t["name"] == "basic" for t in data["templates"])
    assert any(t["name"] == "rag" for t in data["templates"])

    assert len(data["providers"]) > 0
    assert any(p["provider"] == "openai" for p in data["providers"])
    for p in data["providers"]:
        assert len(p["models"]) > 0

    assert isinstance(data["role_dirs"], list)
    assert len(data["role_dirs"]) > 0

    # Custom presets
    assert len(data["custom_presets"]) >= 2
    preset_names = {p["name"] for p in data["custom_presets"]}
    assert "openrouter" in preset_names
    assert "custom" in preset_names

    # OpenRouter preset has correct fields
    or_preset = next(p for p in data["custom_presets"] if p["name"] == "openrouter")
    assert "openrouter.ai" in or_preset["base_url"]
    assert or_preset["api_key_env"] == "OPENROUTER_API_KEY"

    # Ollama fields
    assert isinstance(data["ollama_models"], list)
    assert isinstance(data["ollama_base_url"], str)
    assert "11434" in data["ollama_base_url"]

    # Template setups -- discord and telegram have setup guidance
    setups = data["template_setups"]
    assert "discord" in setups
    assert "telegram" in setups
    assert len(setups["discord"]["steps"]) > 0
    assert len(setups["telegram"]["steps"]) > 0
    assert any(ev["name"] == "DISCORD_BOT_TOKEN" for ev in setups["discord"]["env_vars"])
    assert any(ev["name"] == "TELEGRAM_BOT_TOKEN" for ev in setups["telegram"]["env_vars"])
    assert "discord" in setups["discord"]["extras"]
    assert "telegram" in setups["telegram"]["extras"]
    assert setups["discord"]["docs_url"].startswith("https://")
    assert setups["telegram"]["docs_url"].startswith("https://")
    # Templates without setup guidance should not appear
    assert "basic" not in setups
    assert "rag" not in setups


def test_template_setups_env_var_status(builder_client, monkeypatch):
    """Env var status reflects whether the token is set in the environment."""
    # Token not set
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    resp = builder_client.get("/api/builder/templates")
    data = resp.json()
    discord_vars = data["template_setups"]["discord"]["env_vars"]
    assert discord_vars[0]["name"] == "DISCORD_BOT_TOKEN"
    assert discord_vars[0]["is_set"] is False

    # Token set
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-123")
    resp = builder_client.get("/api/builder/templates")
    data = resp.json()
    discord_vars = data["template_setups"]["discord"]["env_vars"]
    assert discord_vars[0]["is_set"] is True


# -- POST /api/builder/seed ---------------------------------------------------


def test_seed_template(builder_client):
    resp = builder_client.post(
        "/api/builder/seed",
        json={"mode": "template", "template": "basic", "provider": "openai"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "apiVersion" in data["yaml_text"]
    assert "initrunner/v1" in data["yaml_text"]
    assert isinstance(data["issues"], list)
    assert isinstance(data["ready"], bool)


def test_seed_blank(builder_client):
    resp = builder_client.post(
        "/api/builder/seed",
        json={"mode": "blank", "provider": "anthropic"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "apiVersion: initrunner/v1" in data["yaml_text"]
    assert "provider: anthropic" in data["yaml_text"]
    # Blank seed should be shorter than a full template
    assert len(data["yaml_text"]) < 500


def test_seed_template_missing_name(builder_client):
    resp = builder_client.post(
        "/api/builder/seed",
        json={"mode": "template", "provider": "openai"},
    )
    assert resp.status_code == 400


def test_seed_description_missing_text(builder_client):
    resp = builder_client.post(
        "/api/builder/seed",
        json={"mode": "description", "provider": "openai"},
    )
    assert resp.status_code == 400


def test_seed_template_unknown(builder_client):
    resp = builder_client.post(
        "/api/builder/seed",
        json={"mode": "template", "template": "nonexistent", "provider": "openai"},
    )
    assert resp.status_code == 400


def test_seed_description(builder_client):
    """Description seed calls the LLM -- mock it."""
    mock_turn = MagicMock()
    mock_turn.explanation = "Here is your agent."
    mock_turn.yaml_text = "apiVersion: initrunner/v1\nkind: Agent\n"
    mock_turn.issues = []
    mock_turn.ready = True

    with patch(
        "initrunner.services.agent_builder.BuilderSession.seed_description",
        return_value=mock_turn,
    ):
        resp = builder_client.post(
            "/api/builder/seed",
            json={
                "mode": "description",
                "description": "a code review agent",
                "provider": "openai",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["explanation"] == "Here is your agent."
    assert "apiVersion" in data["yaml_text"]


# -- POST /api/builder/validate ------------------------------------------------


def test_validate_valid_yaml(builder_client):
    yaml_text = """\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: test-agent
spec:
  role: |
    You are a helpful assistant that answers questions clearly.
  model:
    provider: openai
    name: gpt-4o
"""
    resp = builder_client.post(
        "/api/builder/validate",
        json={"yaml_text": yaml_text},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    # May have warnings but no errors
    errors = [i for i in data["issues"] if i["severity"] == "error"]
    assert len(errors) == 0


def test_validate_invalid_yaml(builder_client):
    resp = builder_client.post(
        "/api/builder/validate",
        json={"yaml_text": "{{not valid yaml"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is False
    assert len(data["issues"]) > 0
    assert data["issues"][0]["severity"] == "error"


def test_validate_missing_fields(builder_client):
    resp = builder_client.post(
        "/api/builder/validate",
        json={"yaml_text": "apiVersion: initrunner/v1\nkind: Agent\n"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is False


# -- POST /api/builder/save ----------------------------------------------------


def test_save_agent(builder_client, role_dir):
    yaml_text = """\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: saved-agent
spec:
  role: |
    You are a helpful assistant that answers questions clearly.
  model:
    provider: openai
    name: gpt-4o
"""
    resp = builder_client.post(
        "/api/builder/save",
        json={
            "yaml_text": yaml_text,
            "directory": str(role_dir),
            "filename": "saved-agent.yaml",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert "saved-agent.yaml" in data["path"]
    assert data["agent_id"]
    assert len(data["next_steps"]) > 0

    # File actually written
    saved = role_dir / "saved-agent.yaml"
    assert saved.exists()
    assert "saved-agent" in saved.read_text()


def test_save_conflict(builder_client, role_dir):
    """Saving to an existing file without force returns 409."""
    existing = role_dir / "existing.yaml"
    existing.write_text("old content")

    resp = builder_client.post(
        "/api/builder/save",
        json={
            "yaml_text": "apiVersion: initrunner/v1\nkind: Agent\n",
            "directory": str(role_dir),
            "filename": "existing.yaml",
        },
    )
    assert resp.status_code == 409


def test_save_force_overwrite(builder_client, role_dir):
    """Saving with force=True overwrites existing file."""
    existing = role_dir / "existing.yaml"
    existing.write_text("old content")

    yaml_text = """\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: overwritten
spec:
  role: |
    You are a helpful assistant that answers questions clearly.
  model:
    provider: openai
    name: gpt-4o
"""
    resp = builder_client.post(
        "/api/builder/save",
        json={
            "yaml_text": yaml_text,
            "directory": str(role_dir),
            "filename": "existing.yaml",
            "force": True,
        },
    )
    assert resp.status_code == 200
    assert "overwritten" in existing.read_text()


# -- Custom endpoint seeding ---------------------------------------------------


def test_seed_openrouter(builder_client):
    """OpenRouter seed produces YAML with provider: openai + base_url + api_key_env."""
    resp = builder_client.post(
        "/api/builder/seed",
        json={
            "mode": "blank",
            "provider": "openrouter",
            "model": "anthropic/claude-sonnet-4",
        },
    )
    assert resp.status_code == 200
    yaml_text = resp.json()["yaml_text"]
    assert "provider: openai" in yaml_text
    assert "name: anthropic/claude-sonnet-4" in yaml_text
    assert "base_url: https://openrouter.ai/api/v1" in yaml_text
    assert "api_key_env: OPENROUTER_API_KEY" in yaml_text


def test_seed_custom_endpoint(builder_client):
    """Custom endpoint seed with explicit base_url."""
    resp = builder_client.post(
        "/api/builder/seed",
        json={
            "mode": "blank",
            "provider": "custom",
            "model": "my-model",
            "base_url": "https://my-vllm.example.com/v1",
            "api_key_env": "MY_API_KEY",
        },
    )
    assert resp.status_code == 200
    yaml_text = resp.json()["yaml_text"]
    assert "provider: openai" in yaml_text
    assert "name: my-model" in yaml_text
    assert "base_url: https://my-vllm.example.com/v1" in yaml_text
    assert "api_key_env: MY_API_KEY" in yaml_text


def test_seed_custom_missing_base_url(builder_client):
    """Custom endpoint without base_url returns 400."""
    resp = builder_client.post(
        "/api/builder/seed",
        json={
            "mode": "blank",
            "provider": "custom",
            "model": "my-model",
        },
    )
    assert resp.status_code == 400
    assert "base_url" in resp.json()["detail"]


def test_seed_openrouter_missing_model(builder_client):
    """OpenRouter without model name returns 400."""
    resp = builder_client.post(
        "/api/builder/seed",
        json={
            "mode": "blank",
            "provider": "openrouter",
        },
    )
    assert resp.status_code == 400
    assert "model" in resp.json()["detail"]


def test_seed_ollama_default_url(builder_client):
    """Ollama with default URL does not inject base_url into YAML."""
    resp = builder_client.post(
        "/api/builder/seed",
        json={
            "mode": "blank",
            "provider": "ollama",
        },
    )
    assert resp.status_code == 200
    yaml_text = resp.json()["yaml_text"]
    assert "provider: ollama" in yaml_text
    assert "base_url" not in yaml_text


def test_seed_ollama_custom_url(builder_client):
    """Ollama with non-default URL injects base_url into YAML."""
    resp = builder_client.post(
        "/api/builder/seed",
        json={
            "mode": "blank",
            "provider": "ollama",
            "base_url": "http://gpu-server:11434/v1",
        },
    )
    assert resp.status_code == 200
    yaml_text = resp.json()["yaml_text"]
    assert "provider: ollama" in yaml_text
    assert "base_url: http://gpu-server:11434/v1" in yaml_text


def test_seed_openrouter_template(builder_client):
    """OpenRouter with template mode also injects endpoint fields."""
    resp = builder_client.post(
        "/api/builder/seed",
        json={
            "mode": "template",
            "template": "basic",
            "provider": "openrouter",
            "model": "openai/gpt-4o",
        },
    )
    assert resp.status_code == 200
    yaml_text = resp.json()["yaml_text"]
    assert "provider: openai" in yaml_text
    assert "base_url: https://openrouter.ai/api/v1" in yaml_text
    assert "api_key_env: OPENROUTER_API_KEY" in yaml_text


# -- POST /api/builder/save-key -------------------------------------------------


def test_save_key_preset(builder_client, tmp_path, monkeypatch):
    """Saving a key for a known preset writes to .env and returns env var name."""
    env_file = tmp_path / ".env"
    monkeypatch.setattr("initrunner.config.get_global_env_path", lambda: env_file)
    # Also patch in the router module

    resp = builder_client.post(
        "/api/builder/save-key",
        json={"preset": "openrouter", "api_key": "sk-or-test-123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["env_var"] == "OPENROUTER_API_KEY"

    # Key was written to .env
    contents = env_file.read_text()
    assert "OPENROUTER_API_KEY=sk-or-test-123" in contents


def test_save_key_custom(builder_client, tmp_path, monkeypatch):
    """Custom endpoint derives env var name from URL."""
    env_file = tmp_path / ".env"
    monkeypatch.setattr("initrunner.config.get_global_env_path", lambda: env_file)

    resp = builder_client.post(
        "/api/builder/save-key",
        json={
            "base_url": "https://my-vllm.example.com/v1",
            "api_key": "sk-custom-456",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "INITRUNNER_" in data["env_var"]
    assert "KEY" in data["env_var"]

    contents = env_file.read_text()
    assert "sk-custom-456" in contents


def test_save_key_updates_existing(builder_client, tmp_path, monkeypatch):
    """Saving a key that already exists updates it."""
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=old-key\n")
    monkeypatch.setattr("initrunner.config.get_global_env_path", lambda: env_file)

    resp = builder_client.post(
        "/api/builder/save-key",
        json={"preset": "openrouter", "api_key": "new-key"},
    )
    assert resp.status_code == 200

    contents = env_file.read_text()
    assert "OPENROUTER_API_KEY=new-key" in contents
    assert "old-key" not in contents


def test_save_key_missing_preset_and_url(builder_client):
    """Save key without preset or base_url returns 400."""
    resp = builder_client.post(
        "/api/builder/save-key",
        json={"api_key": "sk-test"},
    )
    assert resp.status_code == 400


def test_builder_options_key_configured(builder_client, monkeypatch):
    """Preset shows key_configured=true when env var is set."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    resp = builder_client.get("/api/builder/templates")
    data = resp.json()

    or_preset = next(p for p in data["custom_presets"] if p["name"] == "openrouter")
    assert or_preset["key_configured"] is True

    custom_preset = next(p for p in data["custom_presets"] if p["name"] == "custom")
    assert custom_preset["key_configured"] is False


# -- POST /api/builder/save ----------------------------------------------------


def test_save_outside_role_dirs(builder_client, tmp_path):
    """Saving outside configured role dirs returns 400."""
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    resp = builder_client.post(
        "/api/builder/save",
        json={
            "yaml_text": "apiVersion: initrunner/v1\nkind: Agent\n",
            "directory": str(outside_dir),
            "filename": "sneaky.yaml",
        },
    )
    assert resp.status_code == 400
    assert "not within" in resp.json()["detail"]


# -- _rewrite_model_block unit tests -------------------------------------------

_SAMPLE_YAML = """\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: test-agent
spec:
  role: |
    You are a helpful assistant.
  model:
    provider: openai
    name: gpt-4o
"""


def test_rewrite_model_block_replace():
    """Replacing provider and name in the model block."""
    from initrunner.dashboard.routers.builder import _rewrite_model_block

    result = _rewrite_model_block(
        _SAMPLE_YAML, provider="anthropic", name="claude-sonnet-4-20250514"
    )
    assert "provider: anthropic" in result
    assert "name: claude-sonnet-4-20250514" in result
    assert "provider: openai" not in result
    assert "name: gpt-4o" not in result


def test_rewrite_model_block_inject():
    """Injecting base_url and api_key_env after the name line."""
    from initrunner.dashboard.routers.builder import _rewrite_model_block

    result = _rewrite_model_block(
        _SAMPLE_YAML,
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
    )
    assert "base_url: https://openrouter.ai/api/v1" in result
    assert "api_key_env: OPENROUTER_API_KEY" in result
    # Original provider/name unchanged
    assert "provider: openai" in result
    assert "name: gpt-4o" in result


def test_rewrite_model_block_replace_and_inject():
    """Replace provider/name and inject base_url in one call."""
    from initrunner.dashboard.routers.builder import _rewrite_model_block

    result = _rewrite_model_block(
        _SAMPLE_YAML,
        provider="openai",
        name="anthropic/claude-sonnet-4",
        base_url="https://openrouter.ai/api/v1",
    )
    assert "provider: openai" in result
    assert "name: anthropic/claude-sonnet-4" in result
    assert "base_url: https://openrouter.ai/api/v1" in result


def test_rewrite_model_block_scoped():
    """Does not touch provider/name fields outside the model block."""
    from initrunner.dashboard.routers.builder import _rewrite_model_block

    yaml_with_other_provider = """\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: test-agent
  provider: metadata-provider
spec:
  role: |
    You are a helpful assistant.
  model:
    provider: openai
    name: gpt-4o
  ingest:
    provider: local
"""
    result = _rewrite_model_block(
        yaml_with_other_provider, provider="anthropic", name="claude-sonnet-4-20250514"
    )
    assert "provider: metadata-provider" in result  # metadata untouched
    assert "provider: local" in result  # ingest untouched
    lines = result.split("\n")
    model_section = False
    for line in lines:
        stripped = line.lstrip()
        if stripped == "model:":
            model_section = True
        elif model_section and stripped.startswith("provider:"):
            assert "anthropic" in stripped
            model_section = False


# -- GET /api/builder/hub-search -----------------------------------------------


def test_hub_search_success(builder_client):
    from initrunner.hub import HubSearchResult

    mock_results = [
        HubSearchResult(
            owner="alice",
            name="code-reviewer",
            description="Reviews pull requests",
            tags=["code", "review"],
            downloads=42,
            latest_version="1.0.0",
        ),
    ]
    with patch("initrunner.hub.hub_search", return_value=mock_results):
        resp = builder_client.get("/api/builder/hub-search?q=code+review")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["owner"] == "alice"
    assert item["name"] == "code-reviewer"
    assert item["downloads"] == 42
    assert item["latest_version"] == "1.0.0"


def test_hub_search_empty(builder_client):
    with patch("initrunner.hub.hub_search", return_value=[]):
        resp = builder_client.get("/api/builder/hub-search?q=nonexistent")

    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_hub_search_short_query(builder_client):
    """Query shorter than 2 chars returns empty without hitting the API."""
    resp = builder_client.get("/api/builder/hub-search?q=a")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_hub_search_hub_error(builder_client):
    from initrunner.hub import HubError

    with patch("initrunner.hub.hub_search", side_effect=HubError("connection failed")):
        resp = builder_client.get("/api/builder/hub-search?q=test+query")

    assert resp.status_code == 502
    assert "connection failed" in resp.json()["detail"]


# -- GET /api/builder/hub-featured ---------------------------------------------


def test_hub_featured_success(builder_client):
    import initrunner.dashboard.routers.builder as _bmod
    from initrunner.hub import HubSearchResult

    # Reset cache so this test starts fresh
    _bmod._featured_cache = (0.0, [])

    mock_results = [
        HubSearchResult(
            owner="alice",
            name="code-reviewer",
            description="Reviews pull requests",
            tags=["code"],
            downloads=100,
            latest_version="2.0.0",
        ),
        HubSearchResult(
            owner="bob",
            name="summarizer",
            description="Summarizes documents",
            tags=["text"],
            downloads=80,
            latest_version="1.5.0",
        ),
    ]
    with patch("initrunner.hub.hub_browse", return_value=mock_results):
        resp = builder_client.get("/api/builder/hub-featured")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["items"][0]["owner"] == "alice"
    assert data["items"][0]["downloads"] == 100


def test_hub_featured_hub_error_returns_empty(builder_client):
    import initrunner.dashboard.routers.builder as _bmod
    from initrunner.hub import HubError

    _bmod._featured_cache = (0.0, [])

    with patch("initrunner.hub.hub_browse", side_effect=HubError("timeout")):
        resp = builder_client.get("/api/builder/hub-featured")

    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_hub_featured_caching(builder_client):
    """Second call within TTL uses cached results."""
    import initrunner.dashboard.routers.builder as _bmod
    from initrunner.hub import HubSearchResult

    _bmod._featured_cache = (0.0, [])

    mock_results = [
        HubSearchResult(
            owner="alice",
            name="agent",
            description="d",
            tags=[],
            downloads=50,
            latest_version="1.0.0",
        ),
    ]
    with patch("initrunner.hub.hub_browse", return_value=mock_results) as mock_browse:
        builder_client.get("/api/builder/hub-featured")
        builder_client.get("/api/builder/hub-featured")

    assert mock_browse.call_count == 1


# -- POST /api/builder/hub-seed ------------------------------------------------


def _make_hub_bundle(tmp_path, yaml_content, sidecars=None):
    """Create a .tar.gz bundle for testing hub-seed."""
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        # Primary YAML
        yaml_bytes = yaml_content.encode()
        info = tarfile.TarInfo(name="role.yaml")
        info.size = len(yaml_bytes)
        tar.addfile(info, io.BytesIO(yaml_bytes))
        # Sidecar files
        for name, content in (sidecars or {}).items():
            data = content.encode()
            si = tarfile.TarInfo(name=name)
            si.size = len(data)
            tar.addfile(si, io.BytesIO(data))
    return buf.getvalue()


_HUB_YAML = """\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: hub-agent
  description: An agent from the hub
spec:
  role: |
    You are a helpful assistant that answers questions clearly.
  model:
    provider: openai
    name: gpt-4o
"""


def test_hub_seed_success(builder_client, tmp_path):
    bundle = _make_hub_bundle(tmp_path, _HUB_YAML)

    with patch("initrunner.hub.hub_download", return_value=bundle):
        resp = builder_client.post(
            "/api/builder/hub-seed",
            json={
                "ref": "alice/code-reviewer@1.0.0",
                "provider": "anthropic",
                "model": "claude-sonnet-4-20250514",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "provider: anthropic" in data["yaml_text"]
    assert "name: claude-sonnet-4-20250514" in data["yaml_text"]
    assert "provider: openai" not in data["yaml_text"]
    assert "alice/code-reviewer" in data["explanation"]


def test_hub_seed_with_sidecars(builder_client, tmp_path):
    bundle = _make_hub_bundle(tmp_path, _HUB_YAML, sidecars={"kb/docs.txt": "some knowledge"})

    with patch("initrunner.hub.hub_download", return_value=bundle):
        resp = builder_client.post(
            "/api/builder/hub-seed",
            json={"ref": "alice/kb-agent@1.0.0", "provider": "openai"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "additional files" in data["explanation"]
    assert "initrunner install" in data["explanation"]


def test_hub_seed_invalid_ref(builder_client):
    resp = builder_client.post(
        "/api/builder/hub-seed",
        json={"ref": "not-a-valid-ref!!!", "provider": "openai"},
    )
    assert resp.status_code == 400


def test_hub_seed_hub_error(builder_client):
    from initrunner.hub import HubError

    with patch("initrunner.hub.hub_download", side_effect=HubError("not found")):
        resp = builder_client.post(
            "/api/builder/hub-seed",
            json={"ref": "alice/missing@1.0.0", "provider": "openai"},
        )

    assert resp.status_code == 502
    assert "not found" in resp.json()["detail"]


def test_hub_seed_custom_provider(builder_client, tmp_path):
    """Hub seed with openrouter rewrites to provider: openai + injects base_url."""
    bundle = _make_hub_bundle(tmp_path, _HUB_YAML)

    with patch("initrunner.hub.hub_download", return_value=bundle):
        resp = builder_client.post(
            "/api/builder/hub-seed",
            json={
                "ref": "alice/agent@1.0.0",
                "provider": "openrouter",
                "model": "anthropic/claude-sonnet-4",
            },
        )

    assert resp.status_code == 200
    yaml_text = resp.json()["yaml_text"]
    assert "provider: openai" in yaml_text
    assert "name: anthropic/claude-sonnet-4" in yaml_text
    assert "base_url: https://openrouter.ai/api/v1" in yaml_text
    assert "api_key_env: OPENROUTER_API_KEY" in yaml_text
