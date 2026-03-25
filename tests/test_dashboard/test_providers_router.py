"""Tests for /api/providers route."""

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
