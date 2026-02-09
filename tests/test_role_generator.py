"""Tests for role_generator.py — schema reference and LLM generation."""

from __future__ import annotations

from initrunner.role_generator import build_schema_reference


class TestBuildSchemaReference:
    """Tests for the dynamic schema reference builder."""

    def test_returns_string(self):
        result = build_schema_reference()
        assert isinstance(result, str)
        assert len(result) > 100

    def test_contains_preamble(self):
        result = build_schema_reference()
        assert "apiVersion: initrunner/v1" in result
        assert "kind: Agent" in result

    def test_contains_metadata(self):
        result = build_schema_reference()
        assert "metadata:" in result
        assert "name:" in result
        assert "description:" in result

    def test_contains_model_config(self):
        result = build_schema_reference()
        assert "spec.model:" in result
        assert "provider:" in result
        assert "temperature:" in result

    def test_contains_guardrails(self):
        result = build_schema_reference()
        assert "spec.guardrails:" in result
        assert "max_tokens_per_run:" in result
        assert "timeout_seconds:" in result

    def test_contains_tool_types(self):
        result = build_schema_reference()
        assert "filesystem" in result
        assert "git" in result
        assert "python" in result
        assert "shell" in result

    def test_contains_trigger_types(self):
        result = build_schema_reference()
        assert "cron" in result
        assert "file_watch" in result
        assert "webhook" in result

    def test_contains_sink_types(self):
        result = build_schema_reference()
        assert "Sink types" in result
        assert "file" in result

    def test_contains_ingest(self):
        result = build_schema_reference()
        assert "spec.ingest:" in result
        assert "sources:" in result

    def test_contains_memory(self):
        result = build_schema_reference()
        assert "spec.memory:" in result
        assert "max_sessions:" in result

    def test_reasonable_size(self):
        """Schema reference should be compact (under 10K chars)."""
        result = build_schema_reference()
        assert len(result) < 10_000

    def test_tool_types_from_registry(self):
        """Should include tools discovered via the registry, not just schema classes."""
        from initrunner.agent.tools._registry import get_tool_types

        registered = get_tool_types()
        result = build_schema_reference()
        for type_name in registered:
            assert type_name in result, f"Registered tool '{type_name}' not in schema reference"
