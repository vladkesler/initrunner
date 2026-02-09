"""Smoke tests for HTMX page rendering."""

from __future__ import annotations

import tempfile
from pathlib import Path

from starlette.testclient import TestClient

from initrunner.api.app import create_dashboard_app


def _client() -> TestClient:
    return TestClient(create_dashboard_app(api_key=None))


class TestPageRendering:
    """Verify HTML pages render without errors."""

    def test_root_redirects_to_roles(self):
        c = _client()
        resp = c.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/roles"

    def test_roles_page_renders(self):
        c = _client()
        resp = c.get("/roles")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "InitRunner" in resp.text

    def test_roles_page_contains_table(self):
        c = _client()
        resp = c.get("/roles")
        assert resp.status_code == 200
        assert "<table" in resp.text

    def test_roles_table_fragment(self):
        c = _client()
        resp = c.get("/roles/table")
        assert resp.status_code == 200

    def test_roles_filter(self):
        c = _client()
        resp = c.get("/roles/table?q=nonexistent")
        assert resp.status_code == 200

    def test_audit_page_renders(self):
        c = _client()
        resp = c.get("/audit")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Audit" in resp.text

    def test_audit_table_fragment(self):
        c = _client()
        resp = c.get("/audit/table")
        assert resp.status_code == 200

    def test_login_page_renders(self):
        c = _client()
        resp = c.get("/login")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "API Key" in resp.text

    def test_nonexistent_role_returns_404(self):
        c = _client()
        resp = c.get("/roles/nonexistent-id")
        assert resp.status_code == 404

    def test_health_endpoint(self):
        c = _client()
        resp = c.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_static_assets_served(self):
        c = _client()
        resp = c.get("/static/style.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]

    def test_htmx_served(self):
        c = _client()
        resp = c.get("/static/htmx.min.js")
        assert resp.status_code == 200

    def test_daisyui_served(self):
        c = _client()
        resp = c.get("/static/daisyui.css")
        assert resp.status_code == 200

    def test_api_routes_still_work(self):
        """JSON API routes remain functional."""
        c = _client()
        resp = c.get("/api/roles")
        assert resp.status_code == 200
        data = resp.json()
        assert "roles" in data

    def test_api_audit_still_works(self):
        c = _client()
        resp = c.get("/api/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert "records" in data


class TestAuditDashboardIntegration:
    """End-to-end: audit logger wired through dashboard returns records."""

    def test_audit_records_visible_via_api(self):
        """Records logged via AuditLogger appear in /api/audit."""
        from initrunner.audit.logger import AuditLogger, AuditRecord

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "audit.db"
            logger = AuditLogger(db)
            logger.log(
                AuditRecord(
                    run_id="run-1",
                    agent_name="test-agent",
                    timestamp="2026-02-15T10:00:00+00:00",
                    user_prompt="hello",
                    model="gpt-4",
                    provider="openai",
                    output="hi",
                    tokens_in=10,
                    tokens_out=5,
                    total_tokens=15,
                    tool_calls=0,
                    duration_ms=100,
                    success=True,
                )
            )

            app = create_dashboard_app(api_key=None, audit_logger=logger)
            c = TestClient(app)

            resp = c.get("/api/audit")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["records"]) == 1
            assert data["records"][0]["run_id"] == "run-1"
            assert data["records"][0]["agent_name"] == "test-agent"

            logger.close()

    def test_audit_records_visible_via_html(self):
        """Records logged via AuditLogger appear in /audit HTML page."""
        from initrunner.audit.logger import AuditLogger, AuditRecord

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "audit.db"
            logger = AuditLogger(db)
            logger.log(
                AuditRecord(
                    run_id="run-2",
                    agent_name="html-agent",
                    timestamp="2026-02-15T11:00:00+00:00",
                    user_prompt="test prompt",
                    model="gpt-4",
                    provider="openai",
                    output="test output",
                    tokens_in=10,
                    tokens_out=5,
                    total_tokens=15,
                    tool_calls=0,
                    duration_ms=200,
                    success=True,
                )
            )

            app = create_dashboard_app(api_key=None, audit_logger=logger)
            c = TestClient(app)

            resp = c.get("/audit")
            assert resp.status_code == 200
            assert "No audit records found" not in resp.text
            assert "html-agent" in resp.text

            logger.close()

    def test_executor_writes_audit_via_dashboard_logger(self):
        """execute_run_stream writes to the same logger the dashboard queries."""
        from unittest.mock import MagicMock

        from initrunner.agent.executor import execute_run_stream
        from initrunner.agent.schema import (
            AgentSpec,
            ApiVersion,
            Guardrails,
            Kind,
            Metadata,
            ModelConfig,
            RoleDefinition,
        )
        from initrunner.audit.logger import AuditLogger

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "audit.db"
            logger = AuditLogger(db)

            agent = MagicMock()
            stream_mock = MagicMock()
            stream_mock.stream_text.return_value = iter(["Hello ", "world"])
            stream_mock.all_messages.return_value = []
            usage = MagicMock()
            usage.input_tokens = 5
            usage.output_tokens = 3
            usage.total_tokens = 8
            stream_mock.usage.return_value = usage
            agent.run_stream_sync.return_value = stream_mock

            role = RoleDefinition(
                apiVersion=ApiVersion.V1,
                kind=Kind.AGENT,
                metadata=Metadata(name="stream-agent"),
                spec=AgentSpec(
                    role="test",
                    model=ModelConfig(provider="openai", name="gpt-4"),
                    system_prompt="test",
                    guardrails=Guardrails(),
                ),
            )

            execute_run_stream(
                agent,
                role,
                "chat prompt",
                audit_logger=logger,
                skip_input_validation=True,
            )

            # Now query via the dashboard API
            app = create_dashboard_app(api_key=None, audit_logger=logger)
            c = TestClient(app)

            resp = c.get("/api/audit")
            data = resp.json()
            assert len(data["records"]) == 1
            assert data["records"][0]["agent_name"] == "stream-agent"
            assert data["records"][0]["prompt"] == "chat prompt"

            resp2 = c.get("/audit")
            assert "No audit records found" not in resp2.text
            assert "stream-agent" in resp2.text

            logger.close()
