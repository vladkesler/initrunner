"""Tests for CerbosToolset with agent principals."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from initrunner.agent.permissions import CerbosToolset
from initrunner.authz import (
    Principal,
    set_current_agent_principal,
    set_current_authz,
)


@pytest.fixture(autouse=True)
def _reset_context():
    """Reset ContextVars before and after each test."""
    set_current_agent_principal(None)
    set_current_authz(None)
    yield
    set_current_agent_principal(None)
    set_current_authz(None)


def _make_inner():
    inner = MagicMock()
    inner.id = "test"
    inner.get_tools = AsyncMock(return_value={})
    inner.call_tool = AsyncMock(return_value="tool result")
    inner.__aenter__ = AsyncMock(return_value=inner)
    inner.__aexit__ = AsyncMock(return_value=None)
    return inner


def _make_authz(*, agent_checks: bool = True, allowed: bool = True):
    authz = MagicMock()
    authz.agent_checks_enabled = agent_checks
    authz.check_async = AsyncMock(return_value=allowed)
    return authz


@pytest.mark.asyncio
async def test_no_authz_passes_through():
    """When authz is None, tool call passes through."""
    inner = _make_inner()
    ts = CerbosToolset(inner, "shell", "my-agent")
    # No authz set
    result = await ts.call_tool("run_command", {"cmd": "ls"}, None, None)  # type: ignore[arg-type]
    assert result == "tool result"
    inner.call_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_principal_passes_through():
    """When agent principal is None, tool call passes through."""
    inner = _make_inner()
    authz = _make_authz()
    set_current_authz(authz)
    # No principal set
    ts = CerbosToolset(inner, "shell", "my-agent")
    result = await ts.call_tool("run_command", {"cmd": "ls"}, None, None)  # type: ignore[arg-type]
    assert result == "tool result"
    authz.check_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_checks_disabled_passes_through():
    """When agent_checks_enabled is False, tool call passes through."""
    inner = _make_inner()
    authz = _make_authz(agent_checks=False)
    principal = Principal(id="agent:test", roles=["agent"])
    set_current_authz(authz)
    set_current_agent_principal(principal)

    ts = CerbosToolset(inner, "shell", "my-agent")
    result = await ts.call_tool("run_command", {"cmd": "ls"}, None, None)  # type: ignore[arg-type]
    assert result == "tool result"
    authz.check_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_allowed_by_policy():
    """When Cerbos allows, tool call proceeds."""
    inner = _make_inner()
    authz = _make_authz(allowed=True)
    principal = Principal(id="agent:test", roles=["agent"])
    set_current_authz(authz)
    set_current_agent_principal(principal)

    ts = CerbosToolset(inner, "shell", "my-agent")
    result = await ts.call_tool("run_command", {"cmd": "ls"}, None, None)  # type: ignore[arg-type]
    assert result == "tool result"

    authz.check_async.assert_awaited_once()
    call_args = authz.check_async.call_args
    assert call_args[0][0] == principal
    assert call_args[0][1] == "tool"
    assert call_args[0][2] == "execute"
    assert call_args[1]["resource_id"] == "run_command"
    assert call_args[1]["resource_attrs"]["tool_type"] == "shell"
    assert call_args[1]["resource_attrs"]["agent"] == "my-agent"


@pytest.mark.asyncio
async def test_denied_by_policy():
    """When Cerbos denies, tool call returns permission denied."""
    inner = _make_inner()
    authz = _make_authz(allowed=False)
    principal = Principal(id="agent:test", roles=["agent"])
    set_current_authz(authz)
    set_current_agent_principal(principal)

    ts = CerbosToolset(inner, "shell", "my-agent")
    result = await ts.call_tool("run_command", {"cmd": "ls"}, None, None)  # type: ignore[arg-type]
    assert "Permission denied" in result
    assert "run_command" in result
    inner.call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_instance_key_in_attrs():
    """Instance key is included in resource_attrs when set."""
    inner = _make_inner()
    authz = _make_authz(allowed=True)
    principal = Principal(id="agent:test", roles=["agent"])
    set_current_authz(authz)
    set_current_agent_principal(principal)

    ts = CerbosToolset(inner, "api", "my-agent", instance_key="github-api")
    await ts.call_tool("fetch", {}, None, None)  # type: ignore[arg-type]

    attrs = authz.check_async.call_args[1]["resource_attrs"]
    assert attrs["instance"] == "github-api"
