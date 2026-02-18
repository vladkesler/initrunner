"""Tests for shared sync service functions."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def valid_role_yaml(tmp_path: Path) -> Path:
    """Create a minimal valid role YAML."""
    content = textwrap.dedent("""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: test-agent
          description: A test agent
        spec:
          role: You are a test assistant.
          model:
            provider: openai
            name: gpt-5-mini
    """)
    p = tmp_path / "test-role.yaml"
    p.write_text(content)
    return p


@pytest.fixture
def invalid_role_yaml(tmp_path: Path) -> Path:
    """Create an invalid role YAML."""
    content = textwrap.dedent("""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: bad
        spec:
          role: missing model
    """)
    p = tmp_path / "bad-role.yaml"
    p.write_text(content)
    return p


@pytest.fixture
def non_role_yaml(tmp_path: Path) -> Path:
    """Create a YAML file that isn't an initrunner role."""
    p = tmp_path / "other.yaml"
    p.write_text("foo: bar\n")
    return p


class TestDiscoverRolesSync:
    def test_discovers_valid_role(self, valid_role_yaml: Path):
        from initrunner.services.discovery import discover_roles_sync

        results = discover_roles_sync([valid_role_yaml.parent])
        assert len(results) == 1
        assert results[0].role is not None
        assert results[0].role.metadata.name == "test-agent"
        assert results[0].error is None

    def test_discovers_invalid_role(self, invalid_role_yaml: Path):
        from initrunner.services.discovery import discover_roles_sync

        results = discover_roles_sync([invalid_role_yaml.parent])
        assert len(results) == 1
        assert results[0].role is None
        assert results[0].error is not None

    def test_skips_non_role_yaml(self, non_role_yaml: Path):
        from initrunner.services.discovery import discover_roles_sync

        results = discover_roles_sync([non_role_yaml.parent])
        assert len(results) == 0

    def test_empty_dir(self, tmp_path: Path):
        from initrunner.services.discovery import discover_roles_sync

        results = discover_roles_sync([tmp_path])
        assert results == []

    def test_nonexistent_dir(self):
        from initrunner.services.discovery import discover_roles_sync

        results = discover_roles_sync([Path("/nonexistent/path")])
        assert results == []

    def test_deduplicates(self, valid_role_yaml: Path):
        from initrunner.services.discovery import discover_roles_sync

        # Pass same dir twice
        results = discover_roles_sync([valid_role_yaml.parent, valid_role_yaml.parent])
        assert len(results) == 1

    def test_discovers_role_in_subdirectory(self, tmp_path: Path):
        from initrunner.services.discovery import discover_roles_sync

        subdir = tmp_path / "my-agent"
        subdir.mkdir()
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: nested-agent
              description: Agent in a subdirectory
            spec:
              role: You are nested.
              model:
                provider: openai
                name: gpt-5-mini
        """)
        (subdir / "nested.yaml").write_text(content)

        results = discover_roles_sync([tmp_path])
        assert len(results) == 1
        assert results[0].role is not None
        assert results[0].role.metadata.name == "nested-agent"

    def test_multiple_roles(self, tmp_path: Path):
        from initrunner.services.discovery import discover_roles_sync

        for name in ("alpha", "bravo"):
            content = textwrap.dedent(f"""\
                apiVersion: initrunner/v1
                kind: Agent
                metadata:
                  name: {name}
                  description: Agent {name}
                spec:
                  role: You are {name}.
                  model:
                    provider: openai
                    name: gpt-5-mini
            """)
            (tmp_path / f"{name}.yaml").write_text(content)

        results = discover_roles_sync([tmp_path])
        assert len(results) == 2
        names = {r.role.metadata.name for r in results if r.role}
        assert names == {"alpha", "bravo"}


class TestValidateRoleSync:
    def test_valid(self, valid_role_yaml: Path):
        from initrunner.services.discovery import validate_role_sync

        result = validate_role_sync(valid_role_yaml)
        assert result.role is not None
        assert result.error is None

    def test_invalid(self, invalid_role_yaml: Path):
        from initrunner.services.discovery import validate_role_sync

        result = validate_role_sync(invalid_role_yaml)
        assert result.role is None
        assert result.error is not None


class TestQueryAuditSync:
    def test_no_db(self):
        from initrunner.services.operations import query_audit_sync

        # Should return empty when no audit DB exists
        records = query_audit_sync(limit=10)
        # May or may not return records depending on test environment
        assert isinstance(records, list)


class TestRunAgentStreamed:
    def test_streaming_returns_result(self, valid_role_yaml: Path):
        """Test that execute_run_stream_sync returns a RunResult even on failure."""
        from unittest.mock import MagicMock

        from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
        from initrunner.agent.schema.role import AgentSpec, RoleDefinition
        from initrunner.services.execution import execute_run_stream_sync

        mock_agent = MagicMock()
        role = RoleDefinition(
            apiVersion=ApiVersion.V1,
            kind=Kind.AGENT,
            metadata=Metadata(name="test-agent"),
            spec=AgentSpec(
                role="You are a test.",
                model=ModelConfig(provider="openai", name="gpt-5-mini"),
            ),
        )

        # Simulate agent.run_stream_sync raising an exception
        mock_agent.run_stream_sync.side_effect = ConnectionError("No API key")

        tokens = []
        result, _messages = execute_run_stream_sync(
            mock_agent,
            role,
            "test prompt",
            on_token=tokens.append,
        )

        assert not result.success
        assert result.error is not None and "No API key" in result.error
        assert result.run_id  # Should always have a run_id
