"""Tests for the think tool: config validation and builder."""

from __future__ import annotations

from initrunner.agent.schema.tools import ThinkToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, get_tool_types
from initrunner.agent.tools.think import build_think_toolset


def _make_ctx():
    """Build a minimal ToolBuildContext for tests."""
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
    )
    return ToolBuildContext(role=role)


class TestThinkConfig:
    def test_type_literal(self):
        config = ThinkToolConfig()
        assert config.type == "think"

    def test_summary(self):
        config = ThinkToolConfig()
        assert config.summary() == "think"

    def test_round_trip(self):
        config = ThinkToolConfig()
        data = config.model_dump()
        restored = ThinkToolConfig.model_validate(data)
        assert restored.type == "think"

    def test_from_dict(self):
        config = ThinkToolConfig.model_validate({"type": "think"})
        assert config.type == "think"


class TestThinkToolset:
    def test_builds_toolset_with_think(self):
        config = ThinkToolConfig()
        toolset = build_think_toolset(config, _make_ctx())
        assert "think" in toolset.tools

    def test_think_returns_ack(self):
        config = ThinkToolConfig()
        toolset = build_think_toolset(config, _make_ctx())
        fn = toolset.tools["think"].function
        result = fn(thought="I should check the user's timezone first")
        assert result == "Thought recorded."

    def test_think_empty_string(self):
        config = ThinkToolConfig()
        toolset = build_think_toolset(config, _make_ctx())
        fn = toolset.tools["think"].function
        result = fn(thought="")
        assert result == "Thought recorded."

    def test_think_long_text(self):
        config = ThinkToolConfig()
        toolset = build_think_toolset(config, _make_ctx())
        fn = toolset.tools["think"].function
        result = fn(thought="x" * 10000)
        assert result == "Thought recorded."


class TestThinkRegistration:
    def test_registered_in_tool_types(self):
        types = get_tool_types()
        assert "think" in types
        assert types["think"] is ThinkToolConfig
