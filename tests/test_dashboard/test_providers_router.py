"""Tests for /api/providers routes."""

from unittest.mock import MagicMock, patch


def test_list_providers(client, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    mock_providers = [
        MagicMock(provider="openai", model="gpt-4o"),
        MagicMock(provider="anthropic", model="claude-sonnet-4-20250514"),
    ]

    with patch(
        "initrunner.services.providers.list_available_providers",
        return_value=mock_providers,
    ):
        resp = client.get("/api/providers")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["provider"] == "openai"
    assert data[1]["provider"] == "anthropic"


def test_list_providers_empty(client, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with patch(
        "initrunner.services.providers.list_available_providers",
        return_value=[],
    ):
        resp = client.get("/api/providers")

    assert resp.status_code == 200
    assert resp.json() == []


def test_list_providers_includes_openrouter(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    mock_providers = [
        MagicMock(provider="openai", model="gpt-4o"),
    ]

    with patch(
        "initrunner.services.providers.list_available_providers",
        return_value=mock_providers,
    ):
        resp = client.get("/api/providers")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["provider"] == "openai"
    assert data[1]["provider"] == "openrouter"
    assert data[1]["model"] == "anthropic/claude-sonnet-4"


# -- GET /api/providers/status -------------------------------------------------


def test_provider_status(client, monkeypatch):
    """Status endpoint returns all providers with config flags."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    detected = MagicMock(provider="openai", model="gpt-4o")
    with (
        patch(
            "initrunner.services.providers.detect_provider_and_model",
            return_value=detected,
        ),
        patch(
            "initrunner.services.providers.is_ollama_running",
            return_value=False,
        ),
    ):
        resp = client.get("/api/providers/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["detected_provider"] == "openai"
    assert data["detected_model"] == "gpt-4o"

    providers = data["providers"]
    assert len(providers) > 0

    openai_entry = next(p for p in providers if p["provider"] == "openai")
    assert openai_entry["is_configured"] is True
    assert openai_entry["env_var"] == "OPENAI_API_KEY"

    anthropic_entry = next(p for p in providers if p["provider"] == "anthropic")
    assert anthropic_entry["is_configured"] is False


def test_provider_status_with_ollama(client, monkeypatch):
    """Ollama shows as configured when running."""
    # Clear all API keys
    for env in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"]:
        monkeypatch.delenv(env, raising=False)

    with (
        patch(
            "initrunner.services.providers.detect_provider_and_model",
            return_value=None,
        ),
        patch(
            "initrunner.services.providers.is_ollama_running",
            return_value=True,
        ),
    ):
        resp = client.get("/api/providers/status")

    assert resp.status_code == 200
    data = resp.json()
    ollama_entry = next(p for p in data["providers"] if p["provider"] == "ollama")
    assert ollama_entry["is_configured"] is True


# -- POST /api/providers/save-key ----------------------------------------------


def test_save_key_standard_provider(client, tmp_path, monkeypatch):
    """Saving a key for a standard provider writes to .env."""
    monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
    monkeypatch.setattr("initrunner.config.get_global_env_path", lambda: tmp_path / ".env")

    resp = client.post(
        "/api/providers/save-key",
        json={"provider": "openai", "api_key": "sk-test-123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["env_var"] == "OPENAI_API_KEY"
    assert data["validation_supported"] is True
    assert data["validated"] is False  # validate=False by default


def test_save_key_standard_provider_with_validation(client, tmp_path, monkeypatch):
    """Saving a key with validate=True calls validate_api_key."""
    monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
    monkeypatch.setattr("initrunner.config.get_global_env_path", lambda: tmp_path / ".env")

    with patch(
        "initrunner.services.setup.validate_api_key",
        return_value=True,
    ) as mock_validate:
        resp = client.post(
            "/api/providers/save-key",
            json={"provider": "anthropic", "api_key": "sk-ant-test", "verify": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["env_var"] == "ANTHROPIC_API_KEY"
    assert data["validated"] is True
    assert data["validation_supported"] is True
    mock_validate.assert_called_once_with("anthropic", "sk-ant-test")


def test_save_key_non_validatable_provider(client, tmp_path, monkeypatch):
    """Providers without validation support report validation_supported=False."""
    monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
    monkeypatch.setattr("initrunner.config.get_global_env_path", lambda: tmp_path / ".env")

    resp = client.post(
        "/api/providers/save-key",
        json={"provider": "groq", "api_key": "gsk-test", "verify": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["env_var"] == "GROQ_API_KEY"
    assert data["validation_supported"] is False
    assert data["validated"] is False


def test_save_key_provider_fallthrough_to_preset(client, tmp_path, monkeypatch):
    """Sending provider='openrouter' falls through to preset lookup."""
    monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
    monkeypatch.setattr("initrunner.config.get_global_env_path", lambda: tmp_path / ".env")

    resp = client.post(
        "/api/providers/save-key",
        json={"provider": "openrouter", "api_key": "sk-or-via-provider"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["env_var"] == "OPENROUTER_API_KEY"


def test_save_key_preset(client, tmp_path, monkeypatch):
    """Saving a key for a known preset writes to .env and returns env var name."""
    monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
    monkeypatch.setattr("initrunner.config.get_global_env_path", lambda: tmp_path / ".env")

    resp = client.post(
        "/api/providers/save-key",
        json={"preset": "openrouter", "api_key": "sk-or-test-123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["env_var"] == "OPENROUTER_API_KEY"


def test_save_key_custom(client, tmp_path, monkeypatch):
    """Custom endpoint derives env var name from URL."""
    monkeypatch.setattr("initrunner.config.get_home_dir", lambda: tmp_path)
    monkeypatch.setattr("initrunner.config.get_global_env_path", lambda: tmp_path / ".env")

    resp = client.post(
        "/api/providers/save-key",
        json={
            "base_url": "https://my-vllm.example.com/v1",
            "api_key": "sk-custom-456",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "INITRUNNER_" in data["env_var"]
    assert "KEY" in data["env_var"]


def test_save_key_unknown_provider(client):
    """Unknown provider returns 400."""
    resp = client.post(
        "/api/providers/save-key",
        json={"provider": "nonexistent", "api_key": "sk-test"},
    )
    assert resp.status_code == 400


def test_save_key_missing_all_fields(client):
    """Save key without provider, preset, or base_url returns 400."""
    resp = client.post(
        "/api/providers/save-key",
        json={"api_key": "sk-test"},
    )
    assert resp.status_code == 400
