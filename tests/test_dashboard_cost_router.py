"""Tests for dashboard cost and audit cost_usd endpoints."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("fastapi", reason="dashboard extras not installed")

from fastapi.testclient import TestClient  # type: ignore[import-not-found]

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings
from initrunner.services.cost import ModelCostEntry


@pytest.fixture()
def client():
    app = create_app(DashboardSettings())
    return TestClient(app)


class TestCostByModel:
    def test_returns_list(self, client: TestClient):
        entries = [
            ModelCostEntry(
                model="gpt-4o",
                provider="openai",
                run_count=5,
                tokens_in=1000,
                tokens_out=500,
                total_cost_usd=0.05,
            ),
            ModelCostEntry(
                model="claude-sonnet-4-20250514",
                provider="anthropic",
                run_count=3,
                tokens_in=800,
                tokens_out=400,
                total_cost_usd=None,
            ),
        ]
        with patch(
            "initrunner.services.cost.cost_by_model_sync", return_value=entries
        ):
            resp = client.get("/api/cost/by-model")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["model"] == "gpt-4o"
        assert data[0]["total_cost_usd"] == 0.05
        assert data[1]["total_cost_usd"] is None

    def test_passes_since_until(self, client: TestClient):
        with patch(
            "initrunner.services.cost.cost_by_model_sync", return_value=[]
        ) as mock_fn:
            resp = client.get(
                "/api/cost/by-model",
                params={"since": "2026-01-01T00:00:00", "until": "2026-04-01T00:00:00"},
            )
        assert resp.status_code == 200
        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs["since"] == "2026-01-01T00:00:00"
        assert call_kwargs["until"] == "2026-04-01T00:00:00"

    def test_empty_result(self, client: TestClient):
        with patch(
            "initrunner.services.cost.cost_by_model_sync", return_value=[]
        ):
            resp = client.get("/api/cost/by-model")
        assert resp.status_code == 200
        assert resp.json() == []


class TestAuditCostUsd:
    def test_cost_usd_present_in_records(self, client: TestClient):
        """Audit records should include computed cost_usd."""
        from dataclasses import dataclass

        @dataclass
        class FakeRecord:
            run_id: str = "r1"
            agent_name: str = "test"
            timestamp: str = "2026-04-01T00:00:00"
            user_prompt: str = "hello"
            model: str = "gpt-4o"
            provider: str = "openai"
            output: str = "hi"
            tokens_in: int = 100
            tokens_out: int = 50
            total_tokens: int = 150
            tool_calls: int = 0
            duration_ms: int = 500
            success: bool = True
            error: str | None = None
            trigger_type: str | None = None

        with (
            patch(
                "initrunner.services.operations.query_audit_sync",
                return_value=[FakeRecord()],
            ),
            patch(
                "initrunner.pricing.estimate_cost",
                return_value={
                    "total_cost_usd": 0.001,
                    "input_cost_usd": 0.0005,
                    "output_cost_usd": 0.0005,
                },
            ),
        ):
            resp = client.get("/api/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["cost_usd"] == 0.001

    def test_cost_usd_null_when_unpriceable(self, client: TestClient):
        from dataclasses import dataclass

        @dataclass
        class FakeRecord:
            run_id: str = "r1"
            agent_name: str = "test"
            timestamp: str = "2026-04-01T00:00:00"
            user_prompt: str = "hello"
            model: str = "unknown-model"
            provider: str = "ollama"
            output: str = "hi"
            tokens_in: int = 100
            tokens_out: int = 50
            total_tokens: int = 150
            tool_calls: int = 0
            duration_ms: int = 500
            success: bool = True
            error: str | None = None
            trigger_type: str | None = None

        with (
            patch(
                "initrunner.services.operations.query_audit_sync",
                return_value=[FakeRecord()],
            ),
            patch("initrunner.pricing.estimate_cost", return_value=None),
        ):
            resp = client.get("/api/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["cost_usd"] is None
