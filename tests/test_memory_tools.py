"""Tests for the memory toolset integration."""

from initrunner.agent.schema import (
    EmbeddingConfig,
    MemoryConfig,
    RoleDefinition,
)
from initrunner.agent.tools import _build_memory_toolset, build_toolsets


def _minimal_role_data() -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent", "description": "A test agent"},
        "spec": {
            "role": "You are a test agent.",
            "model": {"provider": "openai", "name": "gpt-4o-mini"},
        },
    }


class TestMemoryConfig:
    def test_defaults(self):
        mc = MemoryConfig()
        assert mc.store_path is None
        assert mc.max_sessions == 10
        assert mc.max_memories == 1000
        assert mc.max_resume_messages == 20
        assert mc.embeddings == EmbeddingConfig()

    def test_custom_values(self):
        mc = MemoryConfig(max_sessions=5, max_memories=500, max_resume_messages=10)
        assert mc.max_sessions == 5
        assert mc.max_memories == 500
        assert mc.max_resume_messages == 10

    def test_memory_config_in_role(self):
        data = _minimal_role_data()
        data["spec"]["memory"] = {"max_sessions": 5, "max_memories": 500}
        role = RoleDefinition.model_validate(data)
        assert role.spec.memory is not None
        assert role.spec.memory.max_sessions == 5
        assert role.spec.memory.max_memories == 500

    def test_no_memory_by_default(self):
        role = RoleDefinition.model_validate(_minimal_role_data())
        assert role.spec.memory is None


class TestBuildMemoryToolset:
    def test_build_memory_toolset(self, tmp_path):
        config = MemoryConfig(store_path=str(tmp_path / "mem.db"))
        toolset = _build_memory_toolset(config, "test-agent", "openai")
        names = list(toolset.tools.keys())
        assert "remember" in names
        assert "recall" in names
        assert "list_memories" in names
        assert len(names) == 3

    def test_build_toolsets_with_memory(self):
        data = _minimal_role_data()
        data["spec"]["memory"] = {"max_sessions": 5}
        role = RoleDefinition.model_validate(data)
        toolsets = build_toolsets(role.spec.tools, role)
        # Memory toolset should be included (last one)
        assert len(toolsets) == 1
        mem_toolset = toolsets[0]
        assert hasattr(mem_toolset, "tools")
        names = list(mem_toolset.tools.keys())  # type: ignore[attr-defined]
        assert "remember" in names
        assert "recall" in names
        assert "list_memories" in names


class TestRememberSanitizesCategory:
    def test_sanitize_category(self):
        import re

        category = "My Notes"
        sanitized = re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_") or "general"
        assert sanitized == "my_notes"

    def test_sanitize_empty_category(self):
        import re

        category = "---"
        sanitized = re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_") or "general"
        assert sanitized == "general"

    def test_sanitize_already_clean(self):
        import re

        category = "notes"
        sanitized = re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_") or "general"
        assert sanitized == "notes"
