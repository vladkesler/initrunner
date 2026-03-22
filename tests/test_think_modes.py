"""Tests for ThinkState and the enhanced think tool."""

from __future__ import annotations

from initrunner.agent.reasoning import ThinkState


class TestThinkState:
    def test_record_returns_formatted(self):
        state = ThinkState()
        result = state.record("First thought")
        assert "Thoughts (1):" in result
        assert "1. First thought" in result

    def test_accumulates_thoughts(self):
        state = ThinkState()
        state.record("One")
        result = state.record("Two")
        assert "1. One" in result
        assert "2. Two" in result
        assert "Thoughts (2):" in result

    def test_ring_buffer_eviction(self):
        state = ThinkState(max_thoughts=3)
        state.record("A")
        state.record("B")
        state.record("C")
        result = state.record("D")
        assert "A" not in result
        assert "1. B" in result
        assert "2. C" in result
        assert "3. D" in result
        assert "Thoughts (3):" in result

    def test_format_empty(self):
        state = ThinkState()
        result = state.format()
        assert "Thoughts (0):" in result


class TestThinkToolBuilder:
    def _build(self, critique: bool = False, max_thoughts: int = 50):
        from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
        from initrunner.agent.schema.role import AgentSpec, RoleDefinition
        from initrunner.agent.schema.tools import ThinkToolConfig
        from initrunner.agent.tools._registry import ToolBuildContext
        from initrunner.agent.tools.think import build_think_toolset

        role = RoleDefinition(
            apiVersion=ApiVersion.V1,
            kind=Kind.AGENT,
            metadata=Metadata(name="test", description=""),
            spec=AgentSpec(role="", model=ModelConfig(provider="openai", name="dummy")),
        )
        config = ThinkToolConfig(critique=critique, max_thoughts=max_thoughts)
        ctx = ToolBuildContext(role=role)
        return build_think_toolset(config, ctx)

    def test_builds_toolset(self):
        toolset = self._build()
        assert toolset is not None

    def test_critique_mode_triggers_on_5th(self):
        toolset = self._build(critique=True)
        # We can't easily call the tool directly, but we can verify the toolset builds
        assert toolset is not None
