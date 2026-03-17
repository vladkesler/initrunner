"""Tests for per-run agent principal scoping in the executor."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent.executor import _enter_agent_context, _exit_agent_context
from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.authz import get_current_agent_principal


def _make_role(name: str = "test-agent", team: str = "") -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name=name, description="test", team=team),
        spec=AgentSpec(
            role="test role",
            model=ModelConfig(provider="openai", name="gpt-4o-mini"),
        ),
    )


@pytest.fixture(autouse=True)
def _reset_executor_state():
    """Reset executor module-level state between tests."""
    import initrunner.agent.executor as exc_mod
    from initrunner.authz import set_current_agent_principal, set_current_authz

    exc_mod._cached_authz = None
    exc_mod._authz_resolved = False
    set_current_agent_principal(None)
    set_current_authz(None)
    yield
    exc_mod._cached_authz = None
    exc_mod._authz_resolved = False
    set_current_agent_principal(None)
    set_current_authz(None)


class TestEnterExitAgentContext:
    def test_no_authz_returns_none(self):
        """When Cerbos is not configured, _enter_agent_context returns None."""
        with patch("initrunner.authz.load_authz_config", return_value=None):
            role = _make_role()
            token = _enter_agent_context(role)
            assert token is None
            assert get_current_agent_principal() is None

    def test_sets_principal_when_authz_available(self):
        """When Cerbos is configured, principal is set for the run."""
        import initrunner.agent.executor as exc_mod

        mock_authz = MagicMock()
        mock_authz.health_check.return_value = (True, "ok")
        exc_mod._cached_authz = mock_authz
        exc_mod._authz_resolved = True  # type: ignore[assignment]

        role = _make_role("my-agent", team="backend")
        token = _enter_agent_context(role)

        assert token is not None
        principal = get_current_agent_principal()
        assert principal is not None
        assert principal.id == "agent:my-agent"
        assert "team:backend" in principal.roles

        # Cleanup
        _exit_agent_context(token)
        assert get_current_agent_principal() is None

    def test_different_roles_get_different_principals(self):
        """Each run should get its own principal based on the role."""
        import initrunner.agent.executor as exc_mod

        mock_authz = MagicMock()
        exc_mod._cached_authz = mock_authz
        exc_mod._authz_resolved = True  # type: ignore[assignment]

        role_a = _make_role("agent-a", team="alpha")
        token_a = _enter_agent_context(role_a)
        principal_a = get_current_agent_principal()
        assert principal_a is not None
        assert principal_a.id == "agent:agent-a"
        _exit_agent_context(token_a)

        role_b = _make_role("agent-b", team="beta")
        token_b = _enter_agent_context(role_b)
        principal_b = get_current_agent_principal()
        assert principal_b is not None
        assert principal_b.id == "agent:agent-b"
        assert "team:beta" in principal_b.roles
        _exit_agent_context(token_b)

    def test_exit_resets_to_previous(self):
        """_exit_agent_context resets to the previous ContextVar value."""
        import initrunner.agent.executor as exc_mod
        from initrunner.authz import Principal, set_current_agent_principal

        mock_authz = MagicMock()
        exc_mod._cached_authz = mock_authz
        exc_mod._authz_resolved = True  # type: ignore[assignment]

        # Set an outer principal (simulating nested calls)
        outer = Principal(id="agent:outer", roles=["agent"])
        set_current_agent_principal(outer)

        role = _make_role("inner-agent")
        token = _enter_agent_context(role)
        principal = get_current_agent_principal()
        assert principal is not None
        assert principal.id == "agent:inner-agent"

        _exit_agent_context(token)
        principal = get_current_agent_principal()
        assert principal is not None
        assert principal.id == "agent:outer"


class TestEnsureAuthzCaching:
    def test_only_resolves_once(self):
        """_ensure_authz should only resolve config once."""
        import initrunner.agent.executor as exc_mod

        with patch("initrunner.authz.load_authz_config", return_value=None) as mock_load:
            exc_mod._ensure_authz()
            exc_mod._ensure_authz()
            exc_mod._ensure_authz()
            mock_load.assert_called_once()

    def test_pdp_unreachable_logs_warning(self):
        """When PDP is unreachable, warning is logged and authz stays None."""
        import initrunner.agent.executor as exc_mod
        from initrunner.authz import AuthzConfig

        config = AuthzConfig(enabled=True, agent_checks=True)
        mock_authz_inst = MagicMock()
        mock_authz_inst.health_check.return_value = (False, "unreachable")

        with (
            patch("initrunner.authz.load_authz_config", return_value=config),
            patch("initrunner.authz.require_cerbos"),
            patch("initrunner.authz.CerbosAuthz", return_value=mock_authz_inst),
        ):
            exc_mod._ensure_authz()

        assert exc_mod._cached_authz is None
        assert exc_mod._authz_resolved is True
