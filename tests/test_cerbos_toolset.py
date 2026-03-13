"""Tests for CerbosToolset tool-level authorization wrapper."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from initrunner.agent.permissions import CerbosToolset, PermissionToolset
from initrunner.agent.schema.tools import ToolPermissions
from initrunner.authz import (
    CerbosAuthz,
    Principal,
    set_current_authz,
    set_current_principal,
)


@pytest.fixture(autouse=True)
def _clear_contextvars():
    """Reset ContextVars before and after each test."""
    set_current_principal(None)
    set_current_authz(None)
    yield
    set_current_principal(None)
    set_current_authz(None)


@pytest.fixture
def inner_toolset():
    """A mock inner toolset."""
    mock = AsyncMock()
    mock.id = "test-toolset"
    mock.get_tools = AsyncMock(return_value={"my_tool": object()})
    mock.call_tool = AsyncMock(return_value="tool result")
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def mock_authz():
    """A mock CerbosAuthz with tool_checks_enabled=True."""
    authz = MagicMock(spec=CerbosAuthz)
    authz.tool_checks_enabled = True
    authz.check_async = AsyncMock(return_value=True)
    return authz


@pytest.fixture
def mock_authz_disabled():
    """A mock CerbosAuthz with tool_checks_enabled=False."""
    authz = MagicMock(spec=CerbosAuthz)
    authz.tool_checks_enabled = False
    authz.check_async = AsyncMock(return_value=True)
    return authz


@pytest.fixture
def principal():
    return Principal(id="alice", roles=["operator"])


# ---------------------------------------------------------------------------
# No-op / pass-through tests
# ---------------------------------------------------------------------------


class TestCerbosToolsetNoop:
    @pytest.mark.anyio
    async def test_noop_when_authz_is_none(self, inner_toolset: Any):
        """No authz ContextVar set -> call passes through."""
        ts = CerbosToolset(inner_toolset, "shell", "test-agent")
        result = await ts.call_tool("run_shell", {"command": "ls"}, None, None)  # type: ignore[arg-type]
        assert result == "tool result"
        inner_toolset.call_tool.assert_called_once()

    @pytest.mark.anyio
    async def test_noop_when_tool_checks_disabled(
        self, inner_toolset: Any, mock_authz_disabled: Any, principal: Principal
    ):
        """authz set but tool_checks=False -> passes through."""
        set_current_authz(mock_authz_disabled)
        set_current_principal(principal)

        ts = CerbosToolset(inner_toolset, "shell", "test-agent")
        result = await ts.call_tool("run_shell", {"command": "ls"}, None, None)  # type: ignore[arg-type]
        assert result == "tool result"
        mock_authz_disabled.check_async.assert_not_called()

    @pytest.mark.anyio
    async def test_noop_when_no_principal(self, inner_toolset: Any, mock_authz: Any):
        """principal ContextVar is None (CLI path) -> passes through."""
        set_current_authz(mock_authz)
        # principal is None (default)

        ts = CerbosToolset(inner_toolset, "shell", "test-agent")
        result = await ts.call_tool("run_shell", {"command": "ls"}, None, None)  # type: ignore[arg-type]
        assert result == "tool result"
        mock_authz.check_async.assert_not_called()


# ---------------------------------------------------------------------------
# Allow / deny tests
# ---------------------------------------------------------------------------


class TestCerbosToolsetAuthz:
    @pytest.mark.anyio
    async def test_allows_when_cerbos_returns_true(
        self, inner_toolset: Any, mock_authz: Any, principal: Principal
    ):
        """Cerbos returns True -> tool executes."""
        set_current_authz(mock_authz)
        set_current_principal(principal)

        ts = CerbosToolset(inner_toolset, "shell", "test-agent")
        result = await ts.call_tool("run_shell", {"command": "ls"}, None, None)  # type: ignore[arg-type]
        assert result == "tool result"
        mock_authz.check_async.assert_called_once()
        inner_toolset.call_tool.assert_called_once()

    @pytest.mark.anyio
    async def test_denies_when_cerbos_returns_false(
        self, inner_toolset: Any, mock_authz: Any, principal: Principal
    ):
        """Cerbos returns False -> returns denial string."""
        mock_authz.check_async = AsyncMock(return_value=False)
        set_current_authz(mock_authz)
        set_current_principal(principal)

        ts = CerbosToolset(inner_toolset, "shell", "test-agent")
        result = await ts.call_tool("run_shell", {"command": "ls"}, None, None)  # type: ignore[arg-type]
        assert "Permission denied" in result
        assert "run_shell" in result
        assert "blocked by policy" in result
        inner_toolset.call_tool.assert_not_called()


# ---------------------------------------------------------------------------
# Resource attrs correctness
# ---------------------------------------------------------------------------


class TestCerbosToolsetResourceAttrs:
    @pytest.mark.anyio
    async def test_resource_attrs_basic(
        self, inner_toolset: Any, mock_authz: Any, principal: Principal
    ):
        """Verify check_async is called with correct attrs."""
        set_current_authz(mock_authz)
        set_current_principal(principal)

        ts = CerbosToolset(inner_toolset, "shell", "my-agent")
        await ts.call_tool("run_shell", {"command": "ls"}, None, None)  # type: ignore[arg-type]

        call_args = mock_authz.check_async.call_args
        assert call_args[0][0] is principal  # principal
        assert call_args[0][1] == "tool"  # resource_kind
        assert call_args[0][2] == "execute"  # action
        assert call_args[1]["resource_id"] == "run_shell"
        attrs = call_args[1]["resource_attrs"]
        assert attrs["tool_type"] == "shell"
        assert attrs["agent"] == "my-agent"
        assert attrs["callable"] == "run_shell"
        assert "instance" not in attrs

    @pytest.mark.anyio
    async def test_resource_attrs_with_instance(
        self, inner_toolset: Any, mock_authz: Any, principal: Principal
    ):
        """Instance key is included when set."""
        set_current_authz(mock_authz)
        set_current_principal(principal)

        ts = CerbosToolset(inner_toolset, "api", "my-agent", instance_key="internal-api")
        await ts.call_tool("get_data", {}, None, None)  # type: ignore[arg-type]

        attrs = mock_authz.check_async.call_args[1]["resource_attrs"]
        assert attrs["instance"] == "internal-api"
        assert attrs["tool_type"] == "api"


# ---------------------------------------------------------------------------
# Wrapper ordering
# ---------------------------------------------------------------------------


class TestCerbosToolsetWrapperOrder:
    @pytest.mark.anyio
    async def test_fnmatch_deny_short_circuits_before_cerbos(
        self, inner_toolset: Any, mock_authz: Any, principal: Principal
    ):
        """PermissionToolset(CerbosToolset(inner)) -- fnmatch deny before Cerbos."""
        set_current_authz(mock_authz)
        set_current_principal(principal)

        cerbos_ts = CerbosToolset(inner_toolset, "shell", "test-agent")
        perms = ToolPermissions(default="deny")
        perm_ts = PermissionToolset(cerbos_ts, perms, "shell")

        result = await perm_ts.call_tool("run_shell", {"command": "ls"}, None, None)  # type: ignore[arg-type]
        assert "Permission denied" in result
        # Cerbos should never have been called
        mock_authz.check_async.assert_not_called()
        inner_toolset.call_tool.assert_not_called()


# ---------------------------------------------------------------------------
# Delegation tests
# ---------------------------------------------------------------------------


class TestCerbosToolsetDelegation:
    @pytest.mark.anyio
    async def test_delegates_id(self, inner_toolset: Any):
        ts = CerbosToolset(inner_toolset, "shell", "test-agent")
        assert ts.id == "test-toolset"

    @pytest.mark.anyio
    async def test_delegates_get_tools(self, inner_toolset: Any):
        ts = CerbosToolset(inner_toolset, "shell", "test-agent")
        tools = await ts.get_tools(None)  # type: ignore[arg-type]
        assert "my_tool" in tools

    @pytest.mark.anyio
    async def test_context_manager_delegates(self, inner_toolset: Any):
        ts = CerbosToolset(inner_toolset, "shell", "test-agent")
        async with ts as entered:
            assert entered is ts
        inner_toolset.__aenter__.assert_called_once()
        inner_toolset.__aexit__.assert_called_once()


# ---------------------------------------------------------------------------
# Context propagation via _run_with_timeout
# ---------------------------------------------------------------------------


class TestContextPropagation:
    def test_run_with_timeout_copies_context(self, mock_authz: Any, principal: Principal):
        """ContextVars set before _run_with_timeout are visible in pool thread."""
        from initrunner.agent.executor import _run_with_timeout
        from initrunner.authz import get_current_authz, get_current_principal

        set_current_principal(principal)
        set_current_authz(mock_authz)

        def check_vars():
            p = get_current_principal()
            a = get_current_authz()
            return (p, a)

        result_p, result_a = _run_with_timeout(check_vars, timeout=5.0)
        assert result_p is principal
        assert result_a is mock_authz


# ---------------------------------------------------------------------------
# build_toolsets integration
# ---------------------------------------------------------------------------


class TestBuildToolsetsCerbosWrapping:
    def test_cerbos_wraps_all_tools(self):
        """All tools from build_toolsets are wrapped with CerbosToolset."""
        from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
        from initrunner.agent.schema.role import AgentSpec, RoleDefinition
        from initrunner.agent.schema.tools import ShellToolConfig

        tool = ShellToolConfig(working_dir=".")
        mock_toolset = MagicMock()

        with patch(
            "initrunner.agent.tools.registry.get_builder",
            return_value=lambda t, c: mock_toolset,
        ):
            from initrunner.agent.tools.registry import build_toolsets

            role = RoleDefinition(
                apiVersion=ApiVersion.V1,
                kind=Kind.AGENT,
                metadata=Metadata(name="test-agent", description=""),
                spec=AgentSpec(
                    role="test",
                    model=ModelConfig(provider="openai", name="gpt-4o"),
                ),
            )
            toolsets = build_toolsets([tool], role)
            # Should be wrapped with CerbosToolset
            assert isinstance(toolsets[0], CerbosToolset)
            assert toolsets[0]._tool_type == "shell"
            assert toolsets[0]._agent_name == "test-agent"

    def test_permissions_wraps_outside_cerbos(self):
        """PermissionToolset is outermost, CerbosToolset is inner."""
        from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
        from initrunner.agent.schema.role import AgentSpec, RoleDefinition
        from initrunner.agent.schema.tools import ShellToolConfig

        tool = ShellToolConfig(
            working_dir=".",
            permissions=ToolPermissions(default="deny", allow=["command=ls *"]),
        )
        mock_toolset = MagicMock()

        with patch(
            "initrunner.agent.tools.registry.get_builder",
            return_value=lambda t, c: mock_toolset,
        ):
            from initrunner.agent.tools.registry import build_toolsets

            role = RoleDefinition(
                apiVersion=ApiVersion.V1,
                kind=Kind.AGENT,
                metadata=Metadata(name="test-agent", description=""),
                spec=AgentSpec(
                    role="test",
                    model=ModelConfig(provider="openai", name="gpt-4o"),
                ),
            )
            toolsets = build_toolsets([tool], role)
            # Outer: PermissionToolset, inner: CerbosToolset
            assert isinstance(toolsets[0], PermissionToolset)
            assert isinstance(toolsets[0]._inner, CerbosToolset)
            assert toolsets[0]._inner._inner is mock_toolset
