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

    def test_summary_critique(self):
        config = ThinkToolConfig(critique=True)
        assert config.summary() == "think (critique)"

    def test_round_trip(self):
        config = ThinkToolConfig()
        data = config.model_dump()
        restored = ThinkToolConfig.model_validate(data)
        assert restored.type == "think"

    def test_from_dict(self):
        config = ThinkToolConfig.model_validate({"type": "think"})
        assert config.type == "think"

    def test_critique_and_max_thoughts(self):
        config = ThinkToolConfig.model_validate(
            {"type": "think", "critique": True, "max_thoughts": 30}
        )
        assert config.critique is True
        assert config.max_thoughts == 30


class TestThinkToolset:
    def test_builds_toolset_with_think(self):
        config = ThinkToolConfig()
        toolset = build_think_toolset(config, _make_ctx())
        assert "think" in toolset.tools

    def test_think_returns_accumulated_chain(self):
        config = ThinkToolConfig()
        toolset = build_think_toolset(config, _make_ctx())
        fn = toolset.tools["think"].function
        result = fn(thought="I should check the user's timezone first")
        assert "Thoughts (1):" in result
        assert "I should check the user's timezone first" in result

    def test_think_accumulates(self):
        config = ThinkToolConfig()
        toolset = build_think_toolset(config, _make_ctx())
        fn = toolset.tools["think"].function
        fn(thought="First")
        result = fn(thought="Second")
        assert "Thoughts (2):" in result
        assert "First" in result
        assert "Second" in result

    def test_think_empty_string(self):
        config = ThinkToolConfig()
        toolset = build_think_toolset(config, _make_ctx())
        fn = toolset.tools["think"].function
        result = fn(thought="")
        assert "Thoughts (1):" in result

    def test_think_critique_nudge(self):
        config = ThinkToolConfig(critique=True, max_thoughts=50)
        toolset = build_think_toolset(config, _make_ctx())
        fn = toolset.tools["think"].function
        for i in range(4):
            fn(thought=f"Thought {i + 1}")
        result = fn(thought="Thought 5")
        assert "critically evaluate" in result


class TestThinkRegistration:
    def test_registered_in_tool_types(self):
        types = get_tool_types()
        assert "think" in types
        assert types["think"] is ThinkToolConfig
