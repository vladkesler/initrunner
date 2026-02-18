"""Tests for initrunner doctor command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()


class TestDoctorConfigScan:
    def test_doctor_no_keys(self, monkeypatch):
        """Doctor with no API keys shows table with Missing entries."""
        # Clear all provider env vars
        for var in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "CO_API_KEY",
        ):
            monkeypatch.delenv(var, raising=False)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Provider Status" in result.output

    def test_doctor_with_key(self, monkeypatch):
        """Doctor with OPENAI_API_KEY set shows 'Set' in output."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Set" in result.output
        assert "Ready" in result.output


class TestDoctorEmbeddingProviders:
    def test_embedding_section_displayed(self, monkeypatch):
        """Doctor should show an 'Embedding Providers' table."""
        for var in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "CO_API_KEY",
        ):
            monkeypatch.delenv(var, raising=False)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Embedding Providers" in result.output

    def test_embedding_key_set_status(self, monkeypatch):
        """When OPENAI_API_KEY is set, embedding status for openai/anthropic shows 'Set'."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        for var in ("GROQ_API_KEY", "MISTRAL_API_KEY", "CO_API_KEY"):
            monkeypatch.delenv(var, raising=False)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        # OPENAI_API_KEY appears in embedding section
        assert "OPENAI_API_KEY" in result.output

    def test_embedding_key_missing_status(self, monkeypatch):
        """When GOOGLE_API_KEY is missing, embedding status for google shows 'Missing'."""
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        for var in ("GROQ_API_KEY", "MISTRAL_API_KEY", "CO_API_KEY"):
            monkeypatch.delenv(var, raising=False)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Missing" in result.output

    def test_anthropic_note_displayed(self, monkeypatch):
        """Doctor should show note about Anthropic using OpenAI embeddings."""
        for var in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "CO_API_KEY",
        ):
            monkeypatch.delenv(var, raising=False)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Anthropic uses OpenAI embeddings" in result.output

    def test_ollama_no_key_needed(self, monkeypatch):
        """Ollama row should show 'No key needed'."""
        for var in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "CO_API_KEY",
        ):
            monkeypatch.delenv(var, raising=False)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "No key needed" in result.output


class TestDoctorQuickstart:
    def test_quickstart_success(self, monkeypatch):
        """--quickstart with mocked successful run shows pass message."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "Hello!"
        mock_result.total_tokens = 15
        mock_result.duration_ms = 100

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                with patch("initrunner.agent.loader.build_agent") as mock_build:
                    mock_build.return_value = MagicMock()
                    with patch("initrunner.agent.executor.execute_run") as mock_exec:
                        mock_exec.return_value = (mock_result, [])
                        result = runner.invoke(app, ["doctor", "--quickstart"])

        assert result.exit_code == 0
        assert "passed" in result.output

    def test_quickstart_failure(self, monkeypatch):
        """--quickstart with failed run exits with code 1."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "API key invalid"

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                with patch("initrunner.agent.loader.build_agent") as mock_build:
                    mock_build.return_value = MagicMock()
                    with patch("initrunner.agent.executor.execute_run") as mock_exec:
                        mock_exec.return_value = (mock_result, [])
                        result = runner.invoke(app, ["doctor", "--quickstart"])

        assert result.exit_code == 1
        assert "failed" in result.output

    def test_quickstart_exception(self, monkeypatch):
        """--quickstart with exception exits with code 1."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                with patch(
                    "initrunner.agent.loader.build_agent",
                    side_effect=RuntimeError("SDK not found"),
                ):
                    result = runner.invoke(app, ["doctor", "--quickstart"])

        assert result.exit_code == 1
        assert "error" in result.output.lower()
