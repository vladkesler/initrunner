"""Tests for per-run agent principal scoping in the executor."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent.executor import _enter_agent_context, _exit_agent_context
from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.authz import get_current_agent_principal

POLICIES_DIR = Path(__file__).resolve().parent.parent / "examples" / "policies" / "agent"


def _make_role(name: str = "test-agent", team: str = "") -> RoleDefinition:
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name=name, description="test", team=team),
        spec=AgentSpec(
            role="test role",
            model=ModelConfig(provider="openai", name="gpt-4o-mini"),
        ),
    )


@pytest.fixture(autouse=True)
def _reset_executor_state():
    """Reset executor module-level state between tests."""
    import initrunner.agent.executor as exc_mod
    from initrunner.authz import set_current_agent_principal, set_current_engine

    exc_mod._cached_engine = None
    exc_mod._cached_config = None
    exc_mod._authz_resolved = False
    set_current_agent_principal(None)
    set_current_engine(None)
    yield
    exc_mod._cached_engine = None
    exc_mod._cached_config = None
    exc_mod._authz_resolved = False
    set_current_agent_principal(None)
    set_current_engine(None)


class TestEnterExitAgentContext:
    def test_no_engine_returns_none(self):
        """When policies are not configured, _enter_agent_context returns None."""
        with patch("initrunner.authz.load_authz_config", return_value=None):
            role = _make_role()
            token = _enter_agent_context(role)
            assert token is None
            assert get_current_agent_principal() is None

    def test_sets_principal_when_engine_available(self):
        """When policies are configured, principal is set for the run."""
        import initrunner.agent.executor as exc_mod

        mock_engine = MagicMock()
        exc_mod._cached_engine = mock_engine
        exc_mod._authz_resolved = True  # type: ignore[assignment]

        role = _make_role("my-agent", team="backend")
        token = _enter_agent_context(role)

        assert token is not None
        principal = get_current_agent_principal()
        assert principal is not None
        assert principal.id == "agent:my-agent"
        assert "team:backend" in principal.roles

        _exit_agent_context(token)
        assert get_current_agent_principal() is None

    def test_different_roles_get_different_principals(self):
        """Each run should get its own principal based on the role."""
        import initrunner.agent.executor as exc_mod

        mock_engine = MagicMock()
        exc_mod._cached_engine = mock_engine
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

        mock_engine = MagicMock()
        exc_mod._cached_engine = mock_engine
        exc_mod._authz_resolved = True  # type: ignore[assignment]

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

    def test_fail_fast_on_bad_policies(self, tmp_path):
        """When POLICY_DIR is set but policies are invalid, error propagates."""
        import initrunner.agent.executor as exc_mod
        from initrunner.authz import AuthzConfig

        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("apiVersion: initguard/v1\nkind: ResourcePolicy\n")
        config = AuthzConfig(policy_dir=str(tmp_path), agent_checks=True)

        from initguard import PolicyLoadError  # type: ignore[import-not-found]

        with patch("initrunner.authz.load_authz_config", return_value=config):
            with pytest.raises(PolicyLoadError):
                exc_mod._ensure_authz()

    def test_loads_engine_from_real_policies(self):
        """_ensure_authz loads engine from real example policies."""
        import initrunner.agent.executor as exc_mod
        from initrunner.authz import AuthzConfig, get_current_engine

        config = AuthzConfig(policy_dir=str(POLICIES_DIR), agent_checks=True)

        with patch("initrunner.authz.load_authz_config", return_value=config):
            exc_mod._ensure_authz()

        assert exc_mod._cached_engine is not None
        assert get_current_engine() is not None
