"""Tests for delegation policy checks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from initrunner.agent.schema.base import Metadata


class TestCheckDelegationPolicy:
    def test_allow_all_when_disabled(self):
        """When authz is None, delegation is always allowed."""
        from initrunner.agent.delegation import check_delegation_policy

        source = Metadata(name="source-agent", description="")
        with patch("initrunner.authz.get_current_authz", return_value=None):
            assert check_delegation_policy(source, "target-agent") is True

    def test_allow_all_when_agent_checks_disabled(self):
        """When agent_checks_enabled is False, delegation is always allowed."""
        from initrunner.agent.delegation import check_delegation_policy

        mock_authz = MagicMock()
        mock_authz.agent_checks_enabled = False

        source = Metadata(name="source-agent", description="")
        with patch("initrunner.authz.get_current_authz", return_value=mock_authz):
            assert check_delegation_policy(source, "target-agent") is True

    def test_cerbos_check_called_with_correct_args(self):
        """When enabled, Cerbos check is called with correct principal and resource."""
        from initrunner.agent.delegation import check_delegation_policy

        mock_authz = MagicMock()
        mock_authz.agent_checks_enabled = True
        mock_authz.check.return_value = True

        source = Metadata(name="source-agent", description="", team="backend")
        target = Metadata(
            name="target-agent", description="", team="backend", author="bob", tags=["safe"]
        )

        with patch("initrunner.authz.get_current_authz", return_value=mock_authz):
            result = check_delegation_policy(source, "target-agent", target)

        assert result is True
        mock_authz.check.assert_called_once()
        call_args = mock_authz.check.call_args
        # Check principal
        principal = call_args[0][0]
        assert principal.id == "agent:source-agent"
        # Check resource kind and action
        assert call_args[0][1] == "agent"
        assert call_args[0][2] == "delegate"
        # Check resource_id
        assert call_args[1]["resource_id"] == "target-agent"
        # Check resource_attrs includes target metadata
        attrs = call_args[1]["resource_attrs"]
        assert attrs["team"] == "backend"
        assert attrs["author"] == "bob"
        assert attrs["tags"] == ["safe"]

    def test_deny_returns_false(self):
        """When Cerbos denies, check_delegation_policy returns False."""
        from initrunner.agent.delegation import check_delegation_policy

        mock_authz = MagicMock()
        mock_authz.agent_checks_enabled = True
        mock_authz.check.return_value = False

        source = Metadata(name="source-agent", description="")
        with patch("initrunner.authz.get_current_authz", return_value=mock_authz):
            assert check_delegation_policy(source, "target-agent") is False

    def test_mcp_name_only_check(self):
        """MCP delegation (no target_metadata) passes empty attrs."""
        from initrunner.agent.delegation import check_delegation_policy

        mock_authz = MagicMock()
        mock_authz.agent_checks_enabled = True
        mock_authz.check.return_value = True

        source = Metadata(name="source-agent", description="")

        with patch("initrunner.authz.get_current_authz", return_value=mock_authz):
            result = check_delegation_policy(source, "remote-agent")

        assert result is True
        call_args = mock_authz.check.call_args
        # Resource attrs should be empty for MCP (no target metadata)
        assert call_args[1]["resource_attrs"] == {}
        assert call_args[1]["resource_id"] == "remote-agent"


class TestInlineInvokerPolicyCheck:
    def test_policy_denied_returns_error(self, tmp_path):
        """InlineInvoker returns delegation error when policy denies."""
        from initrunner.agent.delegation import InlineInvoker

        # Create a minimal role file
        role_file = tmp_path / "target.yaml"
        role_file.write_text(
            "apiVersion: initrunner/v1\n"
            "kind: Agent\n"
            "metadata:\n"
            "  name: target-agent\n"
            "  description: test\n"
            "spec:\n"
            "  role: test\n"
            "  model:\n"
            "    provider: openai\n"
            "    name: gpt-4o-mini\n"
        )

        source = Metadata(name="source-agent", description="")
        invoker = InlineInvoker(
            role_file,
            max_depth=5,
            timeout=30,
            source_metadata=source,
        )

        with patch(
            "initrunner.agent.delegation.check_delegation_policy",
            return_value=False,
        ):
            result = invoker.invoke("test prompt")

        assert "[DELEGATION ERROR]" in result
        assert "Delegation denied by policy" in result

    def test_no_source_metadata_skips_check(self, tmp_path):
        """InlineInvoker without source_metadata skips policy check."""
        from initrunner.agent.delegation import InlineInvoker

        invoker = InlineInvoker(
            tmp_path / "nonexistent.yaml",
            max_depth=5,
            timeout=30,
            source_metadata=None,
        )
        # Will fail at load, but should not fail at policy check
        result = invoker.invoke("test")
        assert "[DELEGATION ERROR]" in result
        assert "Delegation denied by policy" not in result


class TestMcpInvokerPolicyCheck:
    def test_policy_denied_returns_error(self):
        """McpInvoker returns delegation error when policy denies."""
        from initrunner.agent.delegation import McpInvoker

        source = Metadata(name="source-agent", description="")
        invoker = McpInvoker(
            base_url="http://localhost:8000",
            agent_name="remote-agent",
            timeout=30,
            source_metadata=source,
        )

        with patch(
            "initrunner.agent.delegation.check_delegation_policy",
            return_value=False,
        ):
            result = invoker.invoke("test prompt")

        assert "[DELEGATION ERROR]" in result
        assert "Delegation denied by policy" in result

    def test_no_source_metadata_skips_check(self):
        """McpInvoker without source_metadata skips policy check."""
        from initrunner.agent.delegation import McpInvoker

        invoker = McpInvoker(
            base_url="http://localhost:9999",
            agent_name="remote-agent",
            timeout=1,
            source_metadata=None,
        )
        # Will fail at HTTP, but should not fail at policy check
        result = invoker.invoke("test")
        assert "[DELEGATION ERROR]" in result
        assert "Delegation denied by policy" not in result
