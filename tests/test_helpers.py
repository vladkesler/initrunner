"""Tests for CLI helpers — prompt_model_selection."""

from __future__ import annotations

from unittest.mock import patch

from initrunner.cli._helpers import prompt_model_selection


class TestPromptModelSelection:
    """Tests for prompt_model_selection()."""

    def test_default_on_enter(self):
        """Pressing Enter returns the default (first) model."""
        with patch("rich.prompt.Prompt.ask", return_value="gpt-4o-mini"):
            result = prompt_model_selection("openai")
        assert result == "gpt-4o-mini"

    def test_number_input_selects_model(self):
        """Typing '2' selects the second model in the list."""
        with patch("rich.prompt.Prompt.ask", return_value="2"):
            result = prompt_model_selection("openai")
        assert result == "gpt-4o"

    def test_number_input_first(self):
        """Typing '1' selects the first model."""
        with patch("rich.prompt.Prompt.ask", return_value="1"):
            result = prompt_model_selection("anthropic")
        assert result == "claude-sonnet-4-5-20250929"

    def test_custom_model_name(self):
        """Typing a custom model name returns it verbatim."""
        with patch("rich.prompt.Prompt.ask", return_value="my-finetuned-model-v1"):
            result = prompt_model_selection("openai")
        assert result == "my-finetuned-model-v1"

    def test_out_of_range_number_used_as_string(self):
        """A number beyond the list range is treated as a custom string."""
        with patch("rich.prompt.Prompt.ask", return_value="99"):
            result = prompt_model_selection("openai")
        assert result == "99"

    def test_ollama_with_local_models(self):
        """When Ollama local models are provided, they replace the static list."""
        local_models = ["my-local-model:latest", "llama3.2:q4"]
        with patch("rich.prompt.Prompt.ask", return_value="1"):
            result = prompt_model_selection("ollama", ollama_models=local_models)
        assert result == "my-local-model:latest"

    def test_ollama_local_models_second_selection(self):
        """Number selection works with local Ollama models."""
        local_models = ["model-a", "model-b"]
        with patch("rich.prompt.Prompt.ask", return_value="2"):
            result = prompt_model_selection("ollama", ollama_models=local_models)
        assert result == "model-b"

    def test_ollama_none_falls_back_to_static(self):
        """When ollama_models is None, uses static PROVIDER_MODELS."""
        with patch("rich.prompt.Prompt.ask", return_value="1"):
            result = prompt_model_selection("ollama", ollama_models=None)
        assert result == "llama3.2"

    def test_ollama_empty_list_falls_back_to_static(self):
        """When ollama_models is empty, uses static PROVIDER_MODELS."""
        with patch("rich.prompt.Prompt.ask", return_value="1"):
            result = prompt_model_selection("ollama", ollama_models=[])
        assert result == "llama3.2"

    def test_empty_input_returns_default(self):
        """Empty string returns the default model."""
        with patch("rich.prompt.Prompt.ask", return_value=""):
            result = prompt_model_selection("openai")
        assert result == "gpt-4o-mini"
