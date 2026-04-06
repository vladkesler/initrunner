"""Tests for role_generator.py -- schema reference and LLM generation."""

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
        assert "metadata" in result
        assert "name" in result

    def test_contains_model_section(self):
        result = build_schema_reference()
        assert "Model" in result
        assert "provider" in result
        assert "name" in result

    def test_contains_guardrails_section(self):
        result = build_schema_reference()
        assert "Guardrails" in result

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
        assert "Sinks" in result
        assert "file" in result

    def test_contains_optional_sections(self):
        result = build_schema_reference()
        assert "Ingest (spec.ingest)" in result
        assert "Required: sources" in result
        assert "Memory (spec.memory)" in result
        assert "Reasoning (spec.reasoning)" in result
        assert "Autonomy (spec.autonomy)" in result
        assert "Security (spec.security)" in result
        assert "Observability (spec.observability)" in result

    def test_no_default_values_exposed(self):
        """Schema reference must not expose default values that cause over-specification."""
        result = build_schema_reference()
        assert "safe_search=True" not in result
        assert "timeout_seconds=15" not in result
        assert "schema: null" not in result
        assert "=50000" not in result

    def test_reasonable_size(self):
        """Schema reference should be compact (under 10K chars)."""
        result = build_schema_reference()
        assert len(result) < 10_000

    def test_tool_types_from_registry(self):
        """Should include tools discovered via the registry, not just schema classes."""
        from initrunner.agent.tools._registry import get_tool_types

        result = build_schema_reference()
        for tool_type in get_tool_types():
            assert tool_type in result, f"Registry tool '{tool_type}' missing from reference"

    def test_capabilities_section(self):
        result = build_schema_reference()
        assert "Capabilities" in result
        assert "Thinking" in result
        assert "WebSearch" in result
