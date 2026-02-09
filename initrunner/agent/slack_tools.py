"""Slack tool: sends messages via incoming webhooks."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._env import resolve_env_vars
from initrunner.agent._truncate import truncate_output
from initrunner.agent.schema import SlackToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool


@register_tool("slack", SlackToolConfig)
def build_slack_toolset(config: SlackToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for sending Slack messages via webhooks."""
    webhook_url = resolve_env_vars(config.webhook_url)

    toolset = FunctionToolset()

    @toolset.tool
    def send_slack_message(
        text: str,
        channel: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
    ) -> str:
        """Send a message to Slack via an incoming webhook.

        Args:
            text: The message text (used as fallback when blocks are provided).
            channel: Override the default channel (if configured).
            blocks: Optional Block Kit blocks for rich formatting.
        """
        payload: dict[str, Any] = {"text": text}

        target_channel = channel or config.default_channel
        if target_channel:
            payload["channel"] = target_channel
        if config.username:
            payload["username"] = config.username
        if config.icon_emoji:
            payload["icon_emoji"] = config.icon_emoji
        if blocks:
            payload["blocks"] = blocks

        try:
            from initrunner.agent._urls import SSRFSafeTransport

            with httpx.Client(
                timeout=config.timeout_seconds,
                transport=SSRFSafeTransport(),
            ) as client:
                response = client.post(webhook_url, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return f"Slack API error: {exc.response.status_code} {exc.response.text}"
        except httpx.HTTPError as exc:
            return f"Slack connection error: {exc}"

        body = response.text
        return truncate_output(body, config.max_response_bytes)

    return toolset
