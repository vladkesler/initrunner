"""Tests for role creation/update API routes."""

from __future__ import annotations

import textwrap

import pytest
from fastapi.testclient import TestClient

from initrunner.api.app import create_dashboard_app


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


@pytest.fixture
def client(role_dir):
    """Create a test client with the temp role dir."""
    app = create_dashboard_app(role_dirs=[role_dir])
    return TestClient(app)


_VALID_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: new-agent
      description: A new agent
    spec:
      role: You are a new agent.
      model:
        provider: openai
        name: gpt-5-mini
""")


class TestCreateRole:
    def test_create_valid_role(self, client, role_dir):
        resp = client.post("/api/roles", json={"yaml_content": _VALID_YAML})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "new-agent"
        # File should exist on disk
        assert (role_dir / "new-agent.yaml").exists()

    def test_create_role_invalid_yaml(self, client):
        resp = client.post("/api/roles", json={"yaml_content": "not: valid: yaml: ["})
        assert resp.status_code == 400

    def test_create_role_invalid_schema(self, client):
        bad_yaml = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: bad
        """)
        resp = client.post("/api/roles", json={"yaml_content": bad_yaml})
        assert resp.status_code == 400

    def test_create_role_invalid_name(self, client):
        bad_yaml = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: UPPERCASE
            spec:
              role: Test
              model:
                provider: openai
                name: gpt-5-mini
        """)
        resp = client.post("/api/roles", json={"yaml_content": bad_yaml})
        assert resp.status_code == 400

    def test_create_role_conflict(self, client):
        """Second create with same name should return 409."""
        client.post("/api/roles", json={"yaml_content": _VALID_YAML})
        resp = client.post("/api/roles", json={"yaml_content": _VALID_YAML})
        assert resp.status_code == 409

    def test_create_role_not_mapping(self, client):
        resp = client.post("/api/roles", json={"yaml_content": "- item1\n- item2"})
        assert resp.status_code == 400


class TestUpdateRole:
    def test_update_role(self, client, role_dir, monkeypatch):
        # First get the role ID
        monkeypatch.chdir(role_dir)
        resp = client.get("/api/roles?dirs=.")
        role_id = resp.json()["roles"][0]["id"]

        updated_yaml = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-agent
              description: Updated description
            spec:
              role: You are an updated agent.
              model:
                provider: openai
                name: gpt-5-mini
        """)
        resp = client.put(f"/api/roles/{role_id}", json={"yaml_content": updated_yaml})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test-agent"
        assert data["valid"] is True

        # Verify .bak was created
        assert (role_dir / "test-agent.yaml.bak").exists()

    def test_update_role_invalid_yaml(self, client, role_dir, monkeypatch):
        monkeypatch.chdir(role_dir)
        resp = client.get("/api/roles?dirs=.")
        role_id = resp.json()["roles"][0]["id"]

        resp = client.put(f"/api/roles/{role_id}", json={"yaml_content": "bad: [["})
        assert resp.status_code == 400

    def test_update_role_not_found(self, client):
        resp = client.put("/api/roles/nonexistent", json={"yaml_content": _VALID_YAML})
        assert resp.status_code == 404

    def test_update_preserves_file_on_invalid(self, client, role_dir, monkeypatch):
        """Invalid YAML should not overwrite the file."""
        monkeypatch.chdir(role_dir)
        resp = client.get("/api/roles?dirs=.")
        role_id = resp.json()["roles"][0]["id"]

        original = (role_dir / "test-agent.yaml").read_text()

        bad_yaml = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: x
        """)
        resp = client.put(f"/api/roles/{role_id}", json={"yaml_content": bad_yaml})
        assert resp.status_code == 400

        # File should be unchanged
        assert (role_dir / "test-agent.yaml").read_text() == original


class TestRoleCreatePage:
    def test_create_page_loads(self, client):
        resp = client.get("/roles/new")
        assert resp.status_code == 200
        assert "New Role" in resp.text

    def test_create_page_has_form(self, client):
        resp = client.get("/roles/new")
        assert "role-form" in resp.text
        assert "AI Generate" in resp.text


class TestServicesLayer:
    def test_save_role_yaml_sync_valid(self, tmp_path):
        from initrunner.services.roles import save_role_yaml_sync

        path = tmp_path / "out.yaml"
        role = save_role_yaml_sync(path, _VALID_YAML)
        assert role.metadata.name == "new-agent"
        assert path.exists()

    def test_save_role_yaml_sync_invalid(self, tmp_path):
        from initrunner.services.roles import save_role_yaml_sync

        path = tmp_path / "out.yaml"
        with pytest.raises(ValueError):
            save_role_yaml_sync(path, "not yaml: [[")

    def test_save_role_yaml_sync_creates_backup(self, tmp_path):
        from initrunner.services.roles import save_role_yaml_sync

        path = tmp_path / "out.yaml"
        path.write_text("original content")
        save_role_yaml_sync(path, _VALID_YAML)
        bak = tmp_path / "out.yaml.bak"
        assert bak.exists()
        assert bak.read_text() == "original content"

    def test_build_role_yaml_sync(self):
        from initrunner.services.roles import build_role_yaml_sync

        result = build_role_yaml_sync(name="test-agent")
        assert "test-agent" in result
        assert "initrunner/v1" in result
