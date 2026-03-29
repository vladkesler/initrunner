"""Tests for delegation policy checks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from initrunner.agent.schema.base import Metadata
from initrunner.authz import Decision


class TestCheckDelegationPolicy:
    def test_allow_all_when_disabled(self):
        """When engine is None, delegation is always allowed."""
        from initrunner.agent.delegation import check_delegation_policy

        source = Metadata(name="source-agent", description="")
        with patch("initrunner.authz.get_current_engine", return_value=None):
            assert check_delegation_policy(source, "target-agent") is True

    def test_allow_all_when_agent_checks_disabled(self):
        """When agent_checks is False, delegation is always allowed."""
        from initrunner.agent.delegation import check_delegation_policy

        mock_engine = MagicMock()
        mock_config = MagicMock()
        mock_config.agent_checks = False

        source = Metadata(name="source-agent", description="")
        with (
            patch("initrunner.authz.get_current_engine", return_value=mock_engine),
            patch("initrunner.agent.executor._cached_config", mock_config),
        ):
            assert check_delegation_policy(source, "target-agent") is True

    def test_engine_check_called_with_correct_args(self):
        """When enabled, engine check is called with correct principal and resource."""
        from initrunner.agent.delegation import check_delegation_policy

        mock_engine = MagicMock()
        mock_engine.check.return_value = Decision(allowed=True, reason="allowed by policy")
        mock_config = MagicMock()
        mock_config.agent_checks = True

        source = Metadata(name="source-agent", description="", team="backend")
        target = Metadata(
            name="target-agent", description="", team="backend", author="bob", tags=["safe"]
        )

        with (
            patch("initrunner.authz.get_current_engine", return_value=mock_engine),
            patch("initrunner.agent.executor._cached_config", mock_config),
        ):
            result = check_delegation_policy(source, "target-agent", target)

        assert result is True
        mock_engine.check.assert_called_once()
        call_args = mock_engine.check.call_args
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
        """When engine denies, check_delegation_policy returns False."""
        from initrunner.agent.delegation import check_delegation_policy

        mock_engine = MagicMock()
        mock_engine.check.return_value = Decision(allowed=False, reason="denied by policy")
        mock_config = MagicMock()
        mock_config.agent_checks = True

        source = Metadata(name="source-agent", description="")
        with (
            patch("initrunner.authz.get_current_engine", return_value=mock_engine),
            patch("initrunner.agent.executor._cached_config", mock_config),
        ):
            assert check_delegation_policy(source, "target-agent") is False

    def test_mcp_name_only_check(self):
        """MCP delegation (no target_metadata) passes empty attrs."""
        from initrunner.agent.delegation import check_delegation_policy

        mock_engine = MagicMock()
        mock_engine.check.return_value = Decision(allowed=True, reason="allowed")
        mock_config = MagicMock()
        mock_config.agent_checks = True

        source = Metadata(name="source-agent", description="")

        with (
            patch("initrunner.authz.get_current_engine", return_value=mock_engine),
            patch("initrunner.agent.executor._cached_config", mock_config),
        ):
            result = check_delegation_policy(source, "remote-agent")

        assert result is True
        call_args = mock_engine.check.call_args
        assert call_args[1]["resource_attrs"] == {}
        assert call_args[1]["resource_id"] == "remote-agent"


class TestInlineInvokerPolicyCheck:
    def test_policy_denied_returns_error(self, tmp_path):
        """InlineInvoker returns delegation error when policy denies."""
        from initrunner.agent.delegation import InlineInvoker
        from initrunner.agent.schema.base import Metadata as _Meta

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

        mock_role = MagicMock()
        mock_role.metadata = _Meta(name="target-agent", description="test")
        mock_agent = MagicMock()

        with (
            patch(
                "initrunner.agent.delegation.check_delegation_policy",
                return_value=False,
            ),
            patch(
                "initrunner.agent.loader.load_and_build",
                return_value=(mock_role, mock_agent),
            ),
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
        result = invoker.invoke("test")
        assert "[DELEGATION ERROR]" in result
        assert "Delegation denied by policy" not in result
