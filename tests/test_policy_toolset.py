"""Tests for PolicyToolset with agent principals."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from initrunner.agent.permissions import PolicyToolset
from initrunner.authz import (
    Decision,
    Principal,
    set_current_agent_principal,
    set_current_engine,
)


@pytest.fixture(autouse=True)
def _reset_context():
    """Reset ContextVars before and after each test."""
    set_current_agent_principal(None)
    set_current_engine(None)
    yield
    set_current_agent_principal(None)
    set_current_engine(None)


def _make_inner():
    inner = MagicMock()
    inner.id = "test"
    inner.get_tools = AsyncMock(return_value={})
    inner.call_tool = AsyncMock(return_value="tool result")
    inner.__aenter__ = AsyncMock(return_value=inner)
    inner.__aexit__ = AsyncMock(return_value=None)
    return inner


def _make_engine(*, allowed: bool = True, reason: str = "", advice: str = ""):
    engine = MagicMock()
    engine.check_async = AsyncMock(
        return_value=Decision(
            allowed=allowed,
            reason=reason or ("allowed by policy" if allowed else "denied by policy"),
            advice=advice,
        )
    )
    return engine


@pytest.fixture()
def _enable_agent_checks(monkeypatch):
    """Set _cached_config.agent_checks = True in executor module."""
    import initrunner.agent.executor as exc_mod

    mock_config = MagicMock()
    mock_config.agent_checks = True
    monkeypatch.setattr(exc_mod, "_cached_config", mock_config)


@pytest.mark.asyncio
async def test_no_engine_passes_through():
    """When engine is None, tool call passes through."""
    inner = _make_inner()
    ts = PolicyToolset(inner, "shell", "my-agent")
    result = await ts.call_tool("run_command", {"cmd": "ls"}, None, None)  # type: ignore[arg-type]
    assert result == "tool result"
    inner.call_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_principal_passes_through(_enable_agent_checks):
    """When agent principal is None, tool call passes through."""
    inner = _make_inner()
    engine = _make_engine()
    set_current_engine(engine)
    ts = PolicyToolset(inner, "shell", "my-agent")
    result = await ts.call_tool("run_command", {"cmd": "ls"}, None, None)  # type: ignore[arg-type]
    assert result == "tool result"
    engine.check_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_checks_disabled_passes_through(monkeypatch):
    """When agent_checks is False, tool call passes through."""
    import initrunner.agent.executor as exc_mod

    mock_config = MagicMock()
    mock_config.agent_checks = False
    monkeypatch.setattr(exc_mod, "_cached_config", mock_config)

    inner = _make_inner()
    engine = _make_engine()
    principal = Principal(id="agent:test", roles=["agent"])
    set_current_engine(engine)
    set_current_agent_principal(principal)

    ts = PolicyToolset(inner, "shell", "my-agent")
    result = await ts.call_tool("run_command", {"cmd": "ls"}, None, None)  # type: ignore[arg-type]
    assert result == "tool result"
    engine.check_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_allowed_by_policy(_enable_agent_checks):
    """When engine allows, tool call proceeds."""
    inner = _make_inner()
    engine = _make_engine(allowed=True)
    principal = Principal(id="agent:test", roles=["agent"])
    set_current_engine(engine)
    set_current_agent_principal(principal)

    ts = PolicyToolset(inner, "shell", "my-agent")
    result = await ts.call_tool("run_command", {"cmd": "ls"}, None, None)  # type: ignore[arg-type]
    assert result == "tool result"

    engine.check_async.assert_awaited_once()
    call_args = engine.check_async.call_args
    assert call_args[0][0] == principal
    assert call_args[0][1] == "tool"
    assert call_args[0][2] == "execute"
    assert call_args[1]["resource_id"] == "run_command"
    assert call_args[1]["resource_attrs"]["tool_type"] == "shell"
    assert call_args[1]["resource_attrs"]["agent"] == "my-agent"


@pytest.mark.asyncio
async def test_denied_by_policy(_enable_agent_checks):
    """When engine denies, tool call returns permission denied with reason."""
    inner = _make_inner()
    engine = _make_engine(allowed=False, reason="denied by tool_policy.yaml:rules[2]")
    principal = Principal(id="agent:test", roles=["agent"])
    set_current_engine(engine)
    set_current_agent_principal(principal)

    ts = PolicyToolset(inner, "shell", "my-agent")
    result = await ts.call_tool("run_command", {"cmd": "ls"}, None, None)  # type: ignore[arg-type]
    assert "Permission denied" in result
    assert "run_command" in result
    assert "denied by tool_policy.yaml:rules[2]" in result
    inner.call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_denied_with_advice(_enable_agent_checks):
    """When engine denies with advice, advice is included in the message."""
    inner = _make_inner()
    engine = _make_engine(
        allowed=False,
        reason="denied by policy",
        advice="Shell tools require the 'trusted' tag.",
    )
    principal = Principal(id="agent:test", roles=["agent"])
    set_current_engine(engine)
    set_current_agent_principal(principal)

    ts = PolicyToolset(inner, "shell", "my-agent")
    result = await ts.call_tool("run_command", {"cmd": "ls"}, None, None)  # type: ignore[arg-type]
    assert "Permission denied" in result
    assert "Shell tools require the 'trusted' tag." in result


@pytest.mark.asyncio
async def test_instance_key_in_attrs(_enable_agent_checks):
    """Instance key is included in resource_attrs when set."""
    inner = _make_inner()
    engine = _make_engine(allowed=True)
    principal = Principal(id="agent:test", roles=["agent"])
    set_current_engine(engine)
    set_current_agent_principal(principal)

    ts = PolicyToolset(inner, "api", "my-agent", instance_key="github-api")
    await ts.call_tool("fetch", {}, None, None)  # type: ignore[arg-type]

    attrs = engine.check_async.call_args[1]["resource_attrs"]
    assert attrs["instance"] == "github-api"
