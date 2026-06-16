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
    """Reset executor_auth module-level state between tests."""
    import initrunner.agent.executor_auth as auth_mod
    from initrunner.authz import set_current_agent_principal, set_current_engine

    auth_mod._cached_engine = None
    auth_mod._cached_config = None
    auth_mod._authz_resolved = False
    set_current_agent_principal(None)
    set_current_engine(None)
    yield
    auth_mod._cached_engine = None
    auth_mod._cached_config = None
    auth_mod._authz_resolved = False
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
        import initrunner.agent.executor_auth as auth_mod

        mock_engine = MagicMock()
        auth_mod._cached_engine = mock_engine
        auth_mod._authz_resolved = True  # type: ignore[assignment]

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
        import initrunner.agent.executor_auth as auth_mod

        mock_engine = MagicMock()
        auth_mod._cached_engine = mock_engine
        auth_mod._authz_resolved = True  # type: ignore[assignment]

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
        import initrunner.agent.executor_auth as auth_mod
        from initrunner.authz import Principal, set_current_agent_principal

        mock_engine = MagicMock()
        auth_mod._cached_engine = mock_engine
        auth_mod._authz_resolved = True  # type: ignore[assignment]

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

    def test_engine_contextvar_reestablished_each_run(self):
        """Regression: the policy engine must be visible on EVERY run, not just the first.

        execute_run runs each invocation in its own event loop / contextvars context
        (run_sync -> anyio.run). A process-once engine ContextVar set during the first
        run's build is lost on every later run, silently disabling tool authorization.
        _enter_agent_context must re-establish it from the persistent module cache.
        Before the fix the second run observed get_current_engine() == None.
        """
        import anyio

        from initrunner.authz import AuthzConfig, get_current_engine

        config = AuthzConfig(policy_dir=str(POLICIES_DIR), agent_checks=True)
        role = _make_role("cross-run-agent")

        def _run_once() -> tuple[bool, bool]:
            # Mirrors execute_run: a fresh anyio.run / fresh context per call.
            async def _inner() -> tuple[bool, bool]:
                tokens = _enter_agent_context(role)
                try:
                    return tokens is not None, get_current_engine() is not None
                finally:
                    _exit_agent_context(tokens)

            return anyio.run(_inner)

        with patch("initrunner.authz.load_authz_config", return_value=config):
            first = _run_once()
            second = _run_once()

        assert first == (True, True)
        assert second == (True, True)


class TestEnsureAuthzCaching:
    def test_only_resolves_once(self):
        """_ensure_authz should only resolve config once."""
        import initrunner.agent.executor_auth as auth_mod

        with patch("initrunner.authz.load_authz_config", return_value=None) as mock_load:
            auth_mod._ensure_authz()
            auth_mod._ensure_authz()
            auth_mod._ensure_authz()
            mock_load.assert_called_once()

    def test_fail_fast_on_bad_policies(self, tmp_path):
        """When POLICY_DIR is set but policies are invalid, error propagates."""
        import initrunner.agent.executor_auth as auth_mod
        from initrunner.authz import AuthzConfig

        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("apiVersion: initguard/v1\nkind: ResourcePolicy\n")
        config = AuthzConfig(policy_dir=str(tmp_path), agent_checks=True)

        from initguard import PolicyLoadError  # type: ignore[import-not-found]

        with patch("initrunner.authz.load_authz_config", return_value=config):
            with pytest.raises(PolicyLoadError):
                auth_mod._ensure_authz()

    def test_caches_engine_without_setting_contextvar(self):
        """_ensure_authz caches the engine but does NOT set the per-run ContextVar.

        Setting the engine ContextVar at build time binds it to whichever run
        first triggered the build; _enter_agent_context establishes it per run
        instead (see test_engine_contextvar_reestablished_each_run).
        """
        import initrunner.agent.executor_auth as auth_mod
        from initrunner.authz import AuthzConfig, get_current_engine

        config = AuthzConfig(policy_dir=str(POLICIES_DIR), agent_checks=True)

        with patch("initrunner.authz.load_authz_config", return_value=config):
            auth_mod._ensure_authz()

        assert auth_mod._cached_engine is not None
        assert get_current_engine() is None
