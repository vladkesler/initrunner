"""Tests for the slack tool: build_slack_toolset, env var resolution, message sending."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from initrunner.agent._env import resolve_env_vars
from initrunner.agent.schema import AgentSpec, SlackToolConfig
from initrunner.agent.slack_tools import build_slack_toolset
from initrunner.agent.tools._registry import ToolBuildContext


def _make_ctx(role_dir=None):
    """Build a minimal ToolBuildContext for tests."""
    from initrunner.agent.schema import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-4o-mini"},
            },
        }
    )
    return ToolBuildContext(role=role, role_dir=role_dir)


class TestEnvVarResolution:
    def test_resolves_set_var(self):
        os.environ["TEST_SLACK_VAR"] = "resolved_value"
        try:
            assert resolve_env_vars("${TEST_SLACK_VAR}") == "resolved_value"
        finally:
            os.environ.pop("TEST_SLACK_VAR")

    def test_unset_var_kept_as_is(self):
        os.environ.pop("NONEXISTENT_VAR_XYZ", None)
        assert resolve_env_vars("${NONEXISTENT_VAR_XYZ}") == "${NONEXISTENT_VAR_XYZ}"

    def test_multiple_vars(self):
        os.environ["SLACK_A"] = "aaa"
        os.environ["SLACK_B"] = "bbb"
        try:
            result = resolve_env_vars("${SLACK_A}/path/${SLACK_B}")
            assert result == "aaa/path/bbb"
        finally:
            os.environ.pop("SLACK_A")
            os.environ.pop("SLACK_B")

    def test_no_vars(self):
        assert resolve_env_vars("https://hooks.slack.com/test") == "https://hooks.slack.com/test"


class TestSlackToolset:
    def test_builds_toolset(self):
        config = SlackToolConfig(webhook_url="https://hooks.slack.com/test")
        toolset = build_slack_toolset(config, _make_ctx())
        assert "send_slack_message" in toolset.tools

    @patch("initrunner.agent.slack_tools.httpx.Client")
    def test_send_simple_message(self, mock_client_cls: MagicMock):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        config = SlackToolConfig(webhook_url="https://hooks.slack.com/test")
        toolset = build_slack_toolset(config, _make_ctx())
        fn = toolset.tools["send_slack_message"].function

        result = fn(text="Hello Slack")
        assert result == "ok"

        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://hooks.slack.com/test"
        payload = call_args[1]["json"]
        assert payload["text"] == "Hello Slack"

    @patch("initrunner.agent.slack_tools.httpx.Client")
    def test_send_with_channel_and_username(self, mock_client_cls: MagicMock):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        config = SlackToolConfig(
            webhook_url="https://hooks.slack.com/test",
            default_channel="#alerts",
            username="InitRunner Bot",
            icon_emoji=":robot_face:",
        )
        toolset = build_slack_toolset(config, _make_ctx())
        fn = toolset.tools["send_slack_message"].function

        result = fn(text="alert!")
        assert result == "ok"

        payload = mock_client.post.call_args[1]["json"]
        assert payload["channel"] == "#alerts"
        assert payload["username"] == "InitRunner Bot"
        assert payload["icon_emoji"] == ":robot_face:"

    @patch("initrunner.agent.slack_tools.httpx.Client")
    def test_send_with_blocks(self, mock_client_cls: MagicMock):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        config = SlackToolConfig(webhook_url="https://hooks.slack.com/test")
        toolset = build_slack_toolset(config, _make_ctx())
        fn = toolset.tools["send_slack_message"].function

        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "*Bold*"}}]
        result = fn(text="fallback", blocks=blocks)
        assert result == "ok"

        payload = mock_client.post.call_args[1]["json"]
        assert payload["blocks"] == blocks
        assert payload["text"] == "fallback"

    @patch("initrunner.agent.slack_tools.httpx.Client")
    def test_channel_override(self, mock_client_cls: MagicMock):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        config = SlackToolConfig(
            webhook_url="https://hooks.slack.com/test",
            default_channel="#general",
        )
        toolset = build_slack_toolset(config, _make_ctx())
        fn = toolset.tools["send_slack_message"].function

        fn(text="hi", channel="#override")
        payload = mock_client.post.call_args[1]["json"]
        assert payload["channel"] == "#override"

    @patch("initrunner.agent.slack_tools.httpx.Client")
    def test_http_error(self, mock_client_cls: MagicMock):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=mock_response
        )

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        config = SlackToolConfig(webhook_url="https://hooks.slack.com/test")
        toolset = build_slack_toolset(config, _make_ctx())
        fn = toolset.tools["send_slack_message"].function

        result = fn(text="hello")
        assert "Slack API error" in result
        assert "404" in result

    @patch("initrunner.agent.slack_tools.httpx.Client")
    def test_connection_error(self, mock_client_cls: MagicMock):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        config = SlackToolConfig(webhook_url="https://hooks.slack.com/test")
        toolset = build_slack_toolset(config, _make_ctx())
        fn = toolset.tools["send_slack_message"].function

        result = fn(text="hello")
        assert "Slack connection error" in result


class TestSlackSchema:
    def test_parses_from_dict(self):
        data = {
            "type": "slack",
            "webhook_url": "https://hooks.slack.com/services/T/B/X",
            "default_channel": "#alerts",
        }
        config = SlackToolConfig.model_validate(data)
        assert config.webhook_url == "https://hooks.slack.com/services/T/B/X"
        assert config.default_channel == "#alerts"

    def test_summary(self):
        config = SlackToolConfig(webhook_url="https://hooks.slack.com/test")
        assert "slack:" in config.summary()

    def test_in_agent_spec(self):
        spec_data = {
            "role": "Test agent",
            "model": {"provider": "openai", "name": "gpt-4o-mini"},
            "tools": [
                {
                    "type": "slack",
                    "webhook_url": "${SLACK_WEBHOOK_URL}",
                }
            ],
        }
        spec = AgentSpec.model_validate(spec_data)
        assert len(spec.tools) == 1
        assert isinstance(spec.tools[0], SlackToolConfig)

    def test_webhook_url_required(self):
        with pytest.raises(ValueError):
            SlackToolConfig.model_validate({"type": "slack"})
