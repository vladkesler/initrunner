"""Smoke tests for API routes and SPA fallback security."""

import textwrap

import pytest
from fastapi.testclient import TestClient

from initrunner.api.app import create_dashboard_app


@pytest.fixture
def client():
    """Create a test client with no static dir."""
    app = create_dashboard_app()
    return TestClient(app)


@pytest.fixture
def role_dir(tmp_path):
    """Create a temp directory with a valid role file."""
    role_file = tmp_path / "test-agent.yaml"
    role_file.write_text(
        textwrap.dedent("""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: test-agent
          description: A test agent
        spec:
          role: You are a test agent.
          model:
            provider: openai
            name: gpt-5-mini
    """)
    )
    return tmp_path


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestRolesEndpoint:
    def test_list_roles_empty_dir(self, client, tmp_path):
        resp = client.get(f"/api/roles?dirs={tmp_path}")
        assert resp.status_code == 200
        data = resp.json()
        assert "roles" in data
        assert isinstance(data["roles"], list)

    def test_list_roles_with_valid_role(self, client, role_dir):
        resp = client.get(f"/api/roles?dirs={role_dir}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["roles"]) == 1
        assert data["roles"][0]["name"] == "test-agent"
        assert data["roles"][0]["valid"] is True

    def test_get_role_not_found(self, client):
        resp = client.get("/api/roles/nonexistent-id")
        assert resp.status_code == 404

    def test_validate_role_valid(self, role_dir):
        # Create a client with role_dirs including the tmp dir
        app = create_dashboard_app(role_dirs=[role_dir])
        client = TestClient(app)
        role_path = role_dir / "test-agent.yaml"
        resp = client.post("/api/roles/validate", json={"path": str(role_path)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True

    def test_validate_role_missing_file(self, tmp_path):
        # Create a client with role_dirs including the tmp dir
        app = create_dashboard_app(role_dirs=[tmp_path])
        client = TestClient(app)
        resp = client.post("/api/roles/validate", json={"path": str(tmp_path / "missing.yaml")})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert "not found" in data["error"].lower()

    def test_validate_role_rejects_path_outside_role_dirs(self, client, tmp_path):
        resp = client.post("/api/roles/validate", json={"path": "/etc/passwd"})
        assert resp.status_code == 403
        assert "outside" in resp.json()["detail"].lower()

    def test_list_roles_path_traversal_rejected(self, client):
        resp = client.get("/api/roles?dirs=../../etc")
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()

    def test_list_roles_dotdot_in_path_rejected(self, client):
        resp = client.get("/api/roles?dirs=roles/../../../etc")
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()


class TestApiKeyAuth:
    def test_no_key_required(self, client):
        """Without api_key set, all routes should be accessible."""
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_key_required_blocks_unauthorized(self):
        """With api_key set, /api/ routes require auth."""
        app = create_dashboard_app(api_key="test-secret")
        client = TestClient(app)

        resp = client.get("/api/roles")
        assert resp.status_code == 401

    def test_key_via_bearer_header(self):
        """Bearer token auth should work."""
        app = create_dashboard_app(api_key="test-secret")
        client = TestClient(app)

        resp = client.get("/api/roles", headers={"Authorization": "Bearer test-secret"})
        assert resp.status_code == 200

    def test_key_via_query_param(self):
        """Query param auth should work."""
        app = create_dashboard_app(api_key="test-secret")
        client = TestClient(app)

        resp = client.get("/api/roles?api_key=test-secret")
        assert resp.status_code == 200

    def test_health_bypasses_auth(self):
        """Health endpoint should bypass auth."""
        app = create_dashboard_app(api_key="test-secret")
        client = TestClient(app)

        resp = client.get("/api/health")
        assert resp.status_code == 200
