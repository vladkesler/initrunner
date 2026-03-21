"""Tests for the memory toolset integration."""

from initrunner.agent.schema.ingestion import EmbeddingConfig
from initrunner.agent.schema.memory import (
    EpisodicMemoryConfig,
    MemoryConfig,
    ProceduralMemoryConfig,
    SemanticMemoryConfig,
)
from initrunner.agent.schema.role import RoleDefinition
from initrunner.agent.tools import _build_memory_toolset, build_toolsets


def _minimal_role_data() -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent", "description": "A test agent"},
        "spec": {
            "role": "You are a test agent.",
            "model": {"provider": "openai", "name": "gpt-5-mini"},
        },
    }


class TestMemoryConfig:
    def test_defaults(self):
        mc = MemoryConfig()
        assert mc.store_path is None
        assert mc.max_sessions == 10
        assert mc.max_resume_messages == 20
        assert mc.semantic.max_memories == 1000
        assert mc.embeddings == EmbeddingConfig()

    def test_custom_values(self):
        mc = MemoryConfig(max_sessions=5, max_resume_messages=10)
        assert mc.max_sessions == 5
        assert mc.max_resume_messages == 10

    def test_memory_config_in_role(self):
        data = _minimal_role_data()
        data["spec"]["memory"] = {"max_sessions": 5, "semantic": {"max_memories": 500}}
        role = RoleDefinition.model_validate(data)
        assert role.spec.memory is not None
        assert role.spec.memory.max_sessions == 5
        assert role.spec.memory.semantic.max_memories == 500

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
        assert "learn_procedure" in names
        assert "record_episode" in names
        assert len(names) == 5

    def test_build_toolsets_with_memory(self):
        data = _minimal_role_data()
        data["spec"]["memory"] = {"max_sessions": 5}
        role = RoleDefinition.model_validate(data)
        toolsets = build_toolsets(role.spec.tools, role)
        # Memory toolset should be included, wrapped in ObservableToolset -> CerbosToolset
        assert len(toolsets) == 1
        mem_toolset = toolsets[0]
        # Unwrap ObservableToolset then CerbosToolset to access inner toolset
        cerbos = getattr(mem_toolset, "_inner", mem_toolset)
        inner = getattr(cerbos, "_inner", cerbos)
        assert hasattr(inner, "tools")
        names = list(inner.tools.keys())  # type: ignore[attr-defined]
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


class TestConditionalToolRegistration:
    def test_disabled_semantic_no_remember(self, tmp_path):
        config = MemoryConfig(
            store_path=str(tmp_path / "mem.db"),
            semantic=SemanticMemoryConfig(enabled=False),
        )
        toolset = _build_memory_toolset(config, "test-agent", "openai")
        names = list(toolset.tools.keys())
        assert "remember" not in names
        assert "recall" in names
        assert "list_memories" in names

    def test_disabled_procedural_no_learn_procedure(self, tmp_path):
        config = MemoryConfig(
            store_path=str(tmp_path / "mem.db"),
            procedural=ProceduralMemoryConfig(enabled=False),
        )
        toolset = _build_memory_toolset(config, "test-agent", "openai")
        names = list(toolset.tools.keys())
        assert "learn_procedure" not in names
        assert "remember" in names

    def test_disabled_episodic_no_record_episode(self, tmp_path):
        config = MemoryConfig(
            store_path=str(tmp_path / "mem.db"),
            episodic=EpisodicMemoryConfig(enabled=False),
        )
        toolset = _build_memory_toolset(config, "test-agent", "openai")
        names = list(toolset.tools.keys())
        assert "record_episode" not in names
        assert "remember" in names


class TestMemoryConfigMigrationError:
    def test_legacy_max_memories_raises(self):
        import pytest

        with pytest.raises(Exception, match="max_memories has been removed"):
            MemoryConfig(max_memories=500)  # type: ignore[unknown-argument]

    def test_legacy_max_memories_with_semantic_raises(self):
        import pytest

        with pytest.raises(Exception, match="max_memories has been removed"):
            MemoryConfig(max_memories=500, semantic=SemanticMemoryConfig(max_memories=200))  # type: ignore[unknown-argument]

    def test_semantic_max_memories_works(self):
        mc = MemoryConfig(semantic=SemanticMemoryConfig(max_memories=200))
        assert mc.semantic.max_memories == 200

    def test_nested_configs_in_role_yaml(self):
        data = {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "A test agent"},
            "spec": {
                "role": "You are a test agent.",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
                "memory": {
                    "episodic": {"enabled": True, "max_episodes": 100},
                    "semantic": {"enabled": True, "max_memories": 500},
                    "procedural": {"enabled": False},
                    "consolidation": {"enabled": True, "interval": "after_autonomous"},
                },
            },
        }
        role = RoleDefinition.model_validate(data)
        mem = role.spec.memory
        assert mem is not None
        assert mem.episodic.max_episodes == 100
        assert mem.semantic.max_memories == 500
        assert mem.procedural.enabled is False
        assert mem.consolidation.interval == "after_autonomous"
