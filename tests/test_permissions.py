"""Tests for tool call permission checking and PermissionToolset."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from initrunner.agent.permissions import PermissionToolset, check_tool_permission
from initrunner.agent.schema.tools import ToolPermissions

# ---------------------------------------------------------------------------
# check_tool_permission unit tests
# ---------------------------------------------------------------------------


class TestCheckToolPermission:
    def test_allow_pattern_matches(self):
        perms = ToolPermissions(default="deny", allow=["command=ls *"])
        allowed, pattern = check_tool_permission({"command": "ls -la"}, perms)
        assert allowed is True
        assert pattern == "command=ls *"

    def test_deny_pattern_matches(self):
        perms = ToolPermissions(default="allow", deny=["command=rm *"])
        allowed, pattern = check_tool_permission({"command": "rm -rf /"}, perms)
        assert allowed is False
        assert pattern == "command=rm *"

    def test_deny_wins_over_allow(self):
        perms = ToolPermissions(
            default="allow",
            allow=["command=rm *"],
            deny=["command=rm *"],
        )
        allowed, _ = check_tool_permission({"command": "rm file.txt"}, perms)
        assert allowed is False

    def test_default_allow(self):
        perms = ToolPermissions(default="allow")
        allowed, pattern = check_tool_permission({"command": "anything"}, perms)
        assert allowed is True
        assert pattern == ""

    def test_default_deny(self):
        perms = ToolPermissions(default="deny")
        allowed, pattern = check_tool_permission({"command": "anything"}, perms)
        assert allowed is False
        assert pattern == ""

    def test_bare_pattern_matches_any_arg(self):
        perms = ToolPermissions(default="deny", allow=["*.py"])
        allowed, _ = check_tool_permission({"path": "script.py"}, perms)
        assert allowed is True

    def test_bare_pattern_no_match(self):
        perms = ToolPermissions(default="deny", allow=["*.py"])
        allowed, _ = check_tool_permission({"path": "data.csv"}, perms)
        assert allowed is False

    def test_bare_pattern_only_matches_strings(self):
        perms = ToolPermissions(default="deny", allow=["*.py"])
        allowed, _ = check_tool_permission({"count": 42}, perms)
        assert allowed is False

    def test_multiple_allow_patterns(self):
        perms = ToolPermissions(
            default="deny",
            allow=["command=ls *", "command=cat *", "command=grep *"],
        )
        assert check_tool_permission({"command": "cat README.md"}, perms)[0] is True
        assert check_tool_permission({"command": "grep foo bar"}, perms)[0] is True
        assert check_tool_permission({"command": "rm file"}, perms)[0] is False

    def test_arg_name_not_present(self):
        perms = ToolPermissions(default="allow", deny=["path=*.env"])
        allowed, _ = check_tool_permission({"url": "https://example.com"}, perms)
        assert allowed is True

    def test_non_string_arg_coerced(self):
        """Non-string values are str()-coerced for named patterns."""
        perms = ToolPermissions(default="deny", allow=["port=80*"])
        allowed, _ = check_tool_permission({"port": 8080}, perms)
        assert allowed is True

    def test_empty_args(self):
        perms = ToolPermissions(default="deny", allow=["command=ls *"])
        allowed, _ = check_tool_permission({}, perms)
        assert allowed is False

    def test_multiple_deny_first_match_wins(self):
        perms = ToolPermissions(
            default="allow",
            deny=["path=*.env", "path=*credentials*"],
        )
        allowed, pattern = check_tool_permission({"path": "prod.env"}, perms)
        assert allowed is False
        assert pattern == "path=*.env"


# ---------------------------------------------------------------------------
# PermissionToolset tests
# ---------------------------------------------------------------------------


class TestPermissionToolset:
    @pytest.fixture
    def inner_toolset(self):
        """A mock inner toolset."""
        mock = AsyncMock()
        mock.id = "test-toolset"
        mock.get_tools = AsyncMock(return_value={"my_tool": object()})
        mock.call_tool = AsyncMock(return_value="tool result")
        mock.__aenter__ = AsyncMock(return_value=mock)
        mock.__aexit__ = AsyncMock(return_value=None)
        return mock

    @pytest.mark.anyio
    async def test_blocks_denied_call(self, inner_toolset: Any):
        perms = ToolPermissions(default="deny")
        ts = PermissionToolset(inner_toolset, perms, "shell")
        result = await ts.call_tool("run_shell", {"command": "rm -rf /"}, None, None)  # type: ignore[arg-type]
        assert "Permission denied" in result
        assert "run_shell" in result
        inner_toolset.call_tool.assert_not_called()

    @pytest.mark.anyio
    async def test_allows_permitted_call(self, inner_toolset: Any):
        perms = ToolPermissions(default="allow")
        ts = PermissionToolset(inner_toolset, perms, "shell")
        result = await ts.call_tool("run_shell", {"command": "ls"}, None, None)  # type: ignore[arg-type]
        assert result == "tool result"
        inner_toolset.call_tool.assert_called_once()

    @pytest.mark.anyio
    async def test_deny_message_no_arg_leak(self, inner_toolset: Any):
        perms = ToolPermissions(default="allow", deny=["command=rm *"])
        ts = PermissionToolset(inner_toolset, perms, "shell")
        result = await ts.call_tool(
            "run_shell",
            {"command": "rm secret_file.txt"},
            None,
            None,  # type: ignore[arg-type]
        )
        assert "Permission denied" in result
        assert "command=rm *" in result
        # Raw arg value must NOT appear in the message
        assert "secret_file.txt" not in result

    @pytest.mark.anyio
    async def test_delegates_id(self, inner_toolset: Any):
        perms = ToolPermissions()
        ts = PermissionToolset(inner_toolset, perms, "shell")
        assert ts.id == "test-toolset"

    @pytest.mark.anyio
    async def test_delegates_get_tools(self, inner_toolset: Any):
        perms = ToolPermissions()
        ts = PermissionToolset(inner_toolset, perms, "shell")
        tools = await ts.get_tools(None)  # type: ignore[arg-type]
        assert "my_tool" in tools

    @pytest.mark.anyio
    async def test_context_manager_delegates(self, inner_toolset: Any):
        perms = ToolPermissions()
        ts = PermissionToolset(inner_toolset, perms, "shell")
        async with ts as entered:
            assert entered is ts
        inner_toolset.__aenter__.assert_called_once()
        inner_toolset.__aexit__.assert_called_once()

    @pytest.mark.anyio
    async def test_deny_default_policy_message(self, inner_toolset: Any):
        perms = ToolPermissions(default="deny")
        ts = PermissionToolset(inner_toolset, perms, "shell")
        result = await ts.call_tool("run_shell", {"command": "ls"}, None, None)  # type: ignore[arg-type]
        assert "blocked by default policy" in result


# ---------------------------------------------------------------------------
# ToolPermissions schema validation tests
# ---------------------------------------------------------------------------


class TestToolPermissionsSchema:
    def test_defaults(self):
        p = ToolPermissions()
        assert p.default == "allow"
        assert p.allow == []
        assert p.deny == []

    def test_parses_from_dict(self):
        p = ToolPermissions.model_validate(
            {
                "default": "deny",
                "allow": ["command=ls *", "command=cat *"],
                "deny": ["command=rm *"],
            }
        )
        assert p.default == "deny"
        assert len(p.allow) == 2
        assert len(p.deny) == 1

    def test_rejects_empty_arg_name(self):
        with pytest.raises(ValidationError, match="empty argument name"):
            ToolPermissions(allow=["=ls *"])

    def test_rejects_empty_glob(self):
        with pytest.raises(ValidationError, match="empty glob"):
            ToolPermissions(deny=["command="])

    def test_bare_patterns_valid(self):
        p = ToolPermissions(allow=["*.py", "*.txt"])
        assert len(p.allow) == 2

    def test_invalid_default(self):
        with pytest.raises(ValidationError):
            ToolPermissions(default="maybe")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# build_toolsets integration test
# ---------------------------------------------------------------------------


class TestBuildToolsetsPermissions:
    def test_no_permissions_no_wrapping(self):
        """When permissions is None, toolset is not wrapped."""
        from unittest.mock import MagicMock, patch

        from initrunner.agent.schema.tools import ShellToolConfig

        tool = ShellToolConfig(working_dir=".")
        assert tool.permissions is None

        mock_toolset = MagicMock()
        with patch(
            "initrunner.agent.tools.registry.get_builder",
            return_value=lambda t, c: mock_toolset,
        ):
            from initrunner.agent.schema.base import (
                ApiVersion,
                Kind,
                Metadata,
                ModelConfig,
            )
            from initrunner.agent.schema.role import AgentSpec, RoleDefinition
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
            # Should be the raw mock, not wrapped
            assert toolsets[0] is mock_toolset

    def test_permissions_wraps_toolset(self):
        """When permissions is set, toolset is wrapped with PermissionToolset."""
        from unittest.mock import MagicMock, patch

        from initrunner.agent.permissions import PermissionToolset
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
            from initrunner.agent.schema.base import (
                ApiVersion,
                Kind,
                Metadata,
                ModelConfig,
            )
            from initrunner.agent.schema.role import AgentSpec, RoleDefinition
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
            assert isinstance(toolsets[0], PermissionToolset)
