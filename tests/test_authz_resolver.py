"""Tests for resource attribute resolver registry and get_role authz guard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from initrunner.api.authz import AuthzGuard, agent_attrs_resolver, requires
from initrunner.authz import AGENT, READ, WRITE, CerbosAuthz, Principal

# ---------------------------------------------------------------------------
# agent_attrs_resolver
# ---------------------------------------------------------------------------


class TestAgentAttrsResolver:
    @pytest.mark.anyio
    async def test_returns_metadata_fields(self):
        """Resolver returns author, team, tags from role metadata."""
        mock_role = MagicMock()
        mock_role.metadata.author = "alice"
        mock_role.metadata.team = "platform"
        mock_role.metadata.tags = ["public", "rag"]

        request = MagicMock()
        request.state = MagicMock(spec=[])  # no _role_cache yet

        with (
            patch(
                "initrunner.api._helpers.resolve_role_path",
                new_callable=AsyncMock,
                return_value="/tmp/role.yaml",
            ),
            patch(
                "initrunner.api._helpers.load_role_async",
                new_callable=AsyncMock,
                return_value=mock_role,
            ),
        ):
            attrs = await agent_attrs_resolver(request, "abc123")

        assert attrs["author"] == "alice"
        assert attrs["team"] == "platform"
        assert attrs["tags"] == ["public", "rag"]

    @pytest.mark.anyio
    async def test_caches_on_request_state(self):
        """Second call for same resource_id uses cached role."""
        mock_role = MagicMock()
        mock_role.metadata.author = "bob"
        mock_role.metadata.team = ""
        mock_role.metadata.tags = []

        request = MagicMock()
        request.state = MagicMock(spec=[])

        load_mock = AsyncMock(return_value=mock_role)
        with (
            patch(
                "initrunner.api._helpers.resolve_role_path",
                new_callable=AsyncMock,
                return_value="/tmp/role.yaml",
            ),
            patch("initrunner.api._helpers.load_role_async", load_mock),
        ):
            await agent_attrs_resolver(request, "abc123")
            # Second call -- should use cache
            await agent_attrs_resolver(request, "abc123")

        assert load_mock.call_count == 1

    @pytest.mark.anyio
    async def test_returns_empty_on_error(self):
        """Resolver returns empty dict if role can't be loaded."""
        request = MagicMock()
        request.state = MagicMock(spec=[])

        with patch(
            "initrunner.api._helpers.resolve_role_path",
            new_callable=AsyncMock,
            side_effect=Exception("not found"),
        ):
            attrs = await agent_attrs_resolver(request, "bad-id")

        assert attrs == {}


# ---------------------------------------------------------------------------
# requires() with resolver registry
# ---------------------------------------------------------------------------


class TestRequiresResolverIntegration:
    @pytest.mark.anyio
    async def test_resolver_called_and_attrs_passed(self):
        """When a resolver is registered, requires() passes attrs to check_async."""
        mock_authz = MagicMock(spec=CerbosAuthz)
        mock_authz.check_async = AsyncMock(return_value=True)

        resolver = AsyncMock(return_value={"author": "alice", "team": "eng", "tags": []})

        principal = Principal(id="alice", roles=["operator"])

        request = MagicMock()
        request.app.state.authz = mock_authz
        request.app.state.resource_resolvers = {AGENT: resolver}
        request.state.principal = principal
        request.path_params = {"role_id": "abc123"}

        dep = requires(AGENT, READ, resource_id_param="role_id")
        guard = await dep(request)

        assert isinstance(guard, AuthzGuard)
        resolver.assert_called_once_with(request, "abc123")

        call_kwargs = mock_authz.check_async.call_args[1]
        assert call_kwargs["resource_attrs"] == {
            "author": "alice",
            "team": "eng",
            "tags": [],
        }

    @pytest.mark.anyio
    async def test_no_resolver_passes_none_attrs(self):
        """When no resolver is registered, resource_attrs is None."""
        mock_authz = MagicMock(spec=CerbosAuthz)
        mock_authz.check_async = AsyncMock(return_value=True)

        principal = Principal(id="alice", roles=["admin"])

        request = MagicMock()
        request.app.state.authz = mock_authz
        request.app.state.resource_resolvers = {}
        request.state.principal = principal
        request.path_params = {"role_id": "abc123"}

        dep = requires(AGENT, WRITE, resource_id_param="role_id")
        await dep(request)

        call_kwargs = mock_authz.check_async.call_args[1]
        assert call_kwargs["resource_attrs"] is None

    @pytest.mark.anyio
    async def test_resolver_skipped_for_wildcard(self):
        """Resolver is not called when resource_id is '*' (collection ops)."""
        mock_authz = MagicMock(spec=CerbosAuthz)
        mock_authz.check_async = AsyncMock(return_value=True)

        resolver = AsyncMock(return_value={"author": "alice"})

        request = MagicMock()
        request.app.state.authz = mock_authz
        request.app.state.resource_resolvers = {AGENT: resolver}
        request.state.principal = Principal(id="alice", roles=["admin"])
        request.path_params = {}

        # No resource_id_param -> resource_id defaults to "*"
        dep = requires(AGENT, READ)
        await dep(request)

        resolver.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/roles/{role_id} authz guard
# ---------------------------------------------------------------------------


class TestGetRoleAuthzGuard:
    @pytest.fixture
    def _app_with_authz(self, tmp_path):
        """Build a test app with mock Cerbos that denies reads."""
        import textwrap

        from initrunner.api.app import create_dashboard_app

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

        app = create_dashboard_app(role_dirs=[tmp_path])

        # Install a mock authz that denies everything
        mock_authz = MagicMock(spec=CerbosAuthz)
        mock_authz.check_async = AsyncMock(return_value=False)
        app.state.authz = mock_authz

        return app, mock_authz

    def test_get_role_returns_403_when_denied(self, _app_with_authz):
        app, _ = _app_with_authz
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/roles/some-role-id")
        assert resp.status_code == 403

    def test_get_role_without_authz_allows(self, tmp_path):
        """Without Cerbos, get_role still works (no authz guard fires)."""
        import textwrap

        from initrunner.api.app import create_dashboard_app

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

        app = create_dashboard_app(role_dirs=[tmp_path])
        client = TestClient(app)

        # Discover to get the role ID
        roles_resp = client.get("/api/roles")
        assert roles_resp.status_code == 200
        roles = roles_resp.json()["roles"]
        assert len(roles) == 1
        role_id = roles[0]["id"]

        resp = client.get(f"/api/roles/{role_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-agent"
