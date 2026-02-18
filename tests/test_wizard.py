"""Tests for the CLI interactive wizard and build_role_yaml."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

from initrunner.agent.schema.role import RoleDefinition
from initrunner.templates import (
    PROVIDER_MODELS,
    TOOL_DESCRIPTIONS,
    TOOL_PROMPT_FIELDS,
    WIZARD_TEMPLATES,
    _default_model_name,
    build_role_yaml,
    template_basic,
    template_rag,
)


class TestBuildRoleYaml:
    """Tests for build_role_yaml() — the composable YAML builder."""

    def test_minimal(self):
        result = build_role_yaml(name="test-agent")
        raw = yaml.safe_load(result)
        assert raw["apiVersion"] == "initrunner/v1"
        assert raw["kind"] == "Agent"
        assert raw["metadata"]["name"] == "test-agent"
        assert raw["spec"]["model"]["provider"] == "openai"

    def test_validates_as_role_definition(self):
        result = build_role_yaml(name="test-agent")
        raw = yaml.safe_load(result)
        role = RoleDefinition.model_validate(raw)
        assert role.metadata.name == "test-agent"

    def test_with_description(self):
        result = build_role_yaml(name="my-bot", description="A test bot")
        raw = yaml.safe_load(result)
        assert raw["metadata"]["description"] == "A test bot"

    def test_with_provider(self):
        result = build_role_yaml(name="test-agent", provider="anthropic")
        raw = yaml.safe_load(result)
        assert raw["spec"]["model"]["provider"] == "anthropic"
        assert raw["spec"]["model"]["name"] == "claude-sonnet-4-5-20250929"

    def test_with_custom_model(self):
        result = build_role_yaml(name="test-agent", model_name="gpt-4o")
        raw = yaml.safe_load(result)
        assert raw["spec"]["model"]["name"] == "gpt-4o"

    def test_with_tools(self):
        tools = [
            {"type": "filesystem", "root_path": "./src", "read_only": True},
            {"type": "git", "repo_path": "."},
        ]
        result = build_role_yaml(name="test-agent", tools=tools)
        raw = yaml.safe_load(result)
        assert len(raw["spec"]["tools"]) == 2
        assert raw["spec"]["tools"][0]["type"] == "filesystem"

    def test_with_memory(self):
        result = build_role_yaml(name="test-agent", memory=True)
        raw = yaml.safe_load(result)
        assert raw["spec"]["memory"]["max_sessions"] == 10
        assert raw["spec"]["memory"]["max_memories"] == 1000

    def test_without_memory(self):
        result = build_role_yaml(name="test-agent", memory=False)
        raw = yaml.safe_load(result)
        assert "memory" not in raw["spec"]

    def test_with_ingest(self):
        ingest = {
            "sources": ["./docs/**/*.md"],
            "chunking": {"strategy": "fixed", "chunk_size": 512, "chunk_overlap": 50},
        }
        result = build_role_yaml(name="test-agent", ingest=ingest)
        raw = yaml.safe_load(result)
        assert raw["spec"]["ingest"]["sources"] == ["./docs/**/*.md"]

    def test_with_triggers(self):
        triggers = [
            {"type": "cron", "schedule": "0 9 * * 1", "prompt": "Weekly report"},
        ]
        result = build_role_yaml(name="test-agent", triggers=triggers)
        raw = yaml.safe_load(result)
        assert len(raw["spec"]["triggers"]) == 1
        assert raw["spec"]["triggers"][0]["type"] == "cron"

    def test_with_sinks(self):
        sinks = [{"type": "file", "path": "./output.jsonl", "format": "json"}]
        result = build_role_yaml(name="test-agent", sinks=sinks)
        raw = yaml.safe_load(result)
        assert len(raw["spec"]["sinks"]) == 1

    def test_guardrails_defaults(self):
        result = build_role_yaml(name="test-agent")
        raw = yaml.safe_load(result)
        assert raw["spec"]["guardrails"]["max_tokens_per_run"] == 50000
        assert raw["spec"]["guardrails"]["max_tool_calls"] == 20
        assert raw["spec"]["guardrails"]["timeout_seconds"] == 300

    def test_system_prompt(self):
        result = build_role_yaml(
            name="test-agent",
            system_prompt="You are a code reviewer.",
        )
        raw = yaml.safe_load(result)
        assert "code reviewer" in raw["spec"]["role"]

    def test_full_config_validates(self):
        """A fully-populated config should pass validation."""
        result = build_role_yaml(
            name="full-agent",
            description="Full test",
            provider="openai",
            model_name="gpt-5-mini",
            system_prompt="Test prompt.",
            tools=[{"type": "filesystem", "root_path": "."}],
            memory=True,
            ingest={
                "sources": ["*.md"],
                "chunking": {"strategy": "fixed", "chunk_size": 256, "chunk_overlap": 25},
            },
            triggers=[{"type": "cron", "schedule": "*/5 * * * *", "prompt": "check"}],
            sinks=[{"type": "file", "path": "out.jsonl", "format": "json"}],
        )
        raw = yaml.safe_load(result)
        role = RoleDefinition.model_validate(raw)
        assert role.metadata.name == "full-agent"
        assert len(role.spec.tools) == 1
        assert role.spec.memory is not None
        assert role.spec.ingest is not None
        assert len(role.spec.triggers) == 1
        assert len(role.spec.sinks) == 1

    def test_ollama_provider(self):
        result = build_role_yaml(name="test-agent", provider="ollama")
        raw = yaml.safe_load(result)
        assert raw["spec"]["model"]["provider"] == "ollama"
        assert raw["spec"]["model"]["name"] == "llama3.2"


class TestTemplateConstants:
    """Test that the wizard-related constants are well-formed."""

    def test_tool_descriptions_has_entries(self):
        assert len(TOOL_DESCRIPTIONS) >= 8

    def test_tool_prompt_fields_keys_match_descriptions(self):
        for key in TOOL_PROMPT_FIELDS:
            assert key in TOOL_DESCRIPTIONS, f"TOOL_PROMPT_FIELDS has unknown tool: {key}"

    def test_wizard_templates_has_entries(self):
        assert "basic" in WIZARD_TEMPLATES
        assert "blank" in WIZARD_TEMPLATES
        assert len(WIZARD_TEMPLATES) >= 5

    def test_tool_prompt_fields_tuples(self):
        for tool_type, fields in TOOL_PROMPT_FIELDS.items():
            for entry in fields:
                assert len(entry) == 3, f"Expected 3-tuple for {tool_type}: {entry}"
                field_name, prompt_text, _default = entry
                assert isinstance(field_name, str)
                assert isinstance(prompt_text, str)


class TestProviderModels:
    """Tests for PROVIDER_MODELS and _default_model_name."""

    _EXPECTED_PROVIDERS = (
        "openai",
        "anthropic",
        "google",
        "groq",
        "mistral",
        "cohere",
        "bedrock",
        "xai",
        "ollama",
    )

    def test_all_providers_present(self):
        for prov in self._EXPECTED_PROVIDERS:
            assert prov in PROVIDER_MODELS, f"Missing provider: {prov}"

    def test_each_provider_has_models(self):
        for prov in self._EXPECTED_PROVIDERS:
            models = PROVIDER_MODELS[prov]
            assert len(models) >= 2, f"Provider {prov} should have at least 2 models"

    def test_model_entries_are_tuples(self):
        for prov, models in PROVIDER_MODELS.items():
            for entry in models:
                assert len(entry) == 2, f"Expected (id, desc) tuple for {prov}: {entry}"
                assert isinstance(entry[0], str)
                assert isinstance(entry[1], str)

    def test_default_model_returns_first_entry(self):
        for prov, models in PROVIDER_MODELS.items():
            assert _default_model_name(prov) == models[0][0]

    def test_default_model_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="No models defined"):
            _default_model_name("unknown-provider")


class TestTemplateModelName:
    """Tests for template functions accepting optional model_name."""

    def test_basic_with_model_name(self):
        result = template_basic("test", "openai", model_name="gpt-4o")
        assert "gpt-4o" in result

    def test_basic_without_model_name(self):
        result = template_basic("test", "openai")
        assert "gpt-5-mini" in result

    def test_rag_with_model_name(self):
        result = template_rag("test", "anthropic", model_name="claude-opus-4-20250514")
        assert "claude-opus-4-20250514" in result

    def test_rag_without_model_name(self):
        result = template_rag("test", "anthropic")
        assert "claude-sonnet-4-5-20250929" in result


class TestWizardEmbeddingWarning:
    """Tests for Anthropic + memory/ingest embedding key warning in the wizard."""

    def _run_wizard_with_inputs(
        self, provider, template="basic", enable_memory=False, enable_ingest=False, *, tmp_path
    ):
        """Run the wizard with mocked prompts and return captured console output."""
        import io

        from rich.console import Console

        output_path = str(tmp_path / "role.yaml")

        # Capture console output
        buf = io.StringIO()
        mock_console = Console(file=buf, width=120, force_terminal=False)

        def mock_ask(prompt, **kwargs):
            if "Agent name" in prompt:
                return "test-agent"
            if "Description" in prompt:
                return ""
            if "Provider" in prompt:
                return provider
            if "Template" in prompt:
                return template
            if "Tools" in prompt:
                return ""
            if "Ingest sources glob" in prompt:
                return "./docs/**/*.md"
            if "Output file" in prompt:
                return output_path
            return kwargs.get("default", "")

        def mock_confirm(prompt, **kwargs):
            if "memory" in prompt.lower():
                return enable_memory
            if "ingest" in prompt.lower() or "rag" in prompt.lower():
                return enable_ingest
            if "overwrite" in prompt.lower():
                return True
            return kwargs.get("default", False)

        model = "claude-sonnet-4-5-20250929" if provider == "anthropic" else "gpt-5-mini"
        with (
            patch("initrunner.cli.wizard.Prompt.ask", side_effect=mock_ask),
            patch("initrunner.cli.wizard.typer.confirm", side_effect=mock_confirm),
            patch("initrunner.cli.wizard.console", mock_console),
            patch(
                "initrunner.cli._helpers.prompt_model_selection",
                return_value=model,
            ),
        ):
            from initrunner.cli.wizard import run_wizard

            run_wizard()

        return buf.getvalue()

    def test_warning_shown_for_anthropic_with_memory(self, tmp_path):
        """Anthropic + memory should show embedding key warning."""
        output = self._run_wizard_with_inputs("anthropic", enable_memory=True, tmp_path=tmp_path)
        assert "OPENAI_API_KEY" in output
        assert "Anthropic does not provide an embeddings API" in output

    def test_warning_shown_for_anthropic_with_ingest(self, tmp_path):
        """Anthropic + ingestion should show embedding key warning."""
        output = self._run_wizard_with_inputs("anthropic", template="rag", tmp_path=tmp_path)
        assert "OPENAI_API_KEY" in output
        assert "Anthropic does not provide an embeddings API" in output

    def test_no_warning_for_anthropic_without_memory_or_ingest(self, tmp_path):
        """Anthropic without memory/ingest should NOT show embedding warning."""
        output = self._run_wizard_with_inputs(
            "anthropic", enable_memory=False, enable_ingest=False, tmp_path=tmp_path
        )
        assert "Anthropic does not provide an embeddings API" not in output

    def test_no_warning_for_openai_with_memory(self, tmp_path):
        """OpenAI + memory should NOT show Anthropic embedding warning."""
        output = self._run_wizard_with_inputs("openai", enable_memory=True, tmp_path=tmp_path)
        assert "Anthropic does not provide an embeddings API" not in output
