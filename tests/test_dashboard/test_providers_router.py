"""Tests for /api/providers route."""

from unittest.mock import MagicMock, patch


def test_list_providers(client):
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


def test_list_providers_empty(client):
    with patch(
        "initrunner.services.providers.list_available_providers",
        return_value=[],
    ):
        resp = client.get("/api/providers")

    assert resp.status_code == 200
    assert resp.json() == []
