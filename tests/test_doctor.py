"""Tests for initrunner doctor command."""

from __future__ import annotations

import textwrap
from pathlib import Path
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


class TestDoctorDocker:
    def test_docker_row_displayed(self, monkeypatch):
        """Doctor should show a 'docker' row in the provider status table."""
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
                with patch(
                    "initrunner.agent.docker_sandbox.check_docker_available",
                    return_value=False,
                ):
                    result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "docker" in result.output.lower()


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


def _valid_role_yaml() -> str:
    return textwrap.dedent("""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: test-valid
          spec_version: 2
        spec:
          role: You are helpful.
          model:
            provider: openai
            name: gpt-5-mini
    """)


class TestDoctorRoleValidation:
    def test_clean_role(self, tmp_path: Path, monkeypatch):
        """Valid role shows 'valid and up to date'."""
        p = tmp_path / "role.yaml"
        p.write_text(_valid_role_yaml())

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--role", str(p)])

        assert result.exit_code == 0
        assert "valid and up to date" in result.output

    def test_stale_version_note(self, tmp_path: Path, monkeypatch):
        """spec_version: 1 shows stale note but exits 0."""
        content = _valid_role_yaml().replace("spec_version: 2", "spec_version: 1")
        p = tmp_path / "role.yaml"
        p.write_text(content)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--role", str(p)])

        assert result.exit_code == 0
        assert "is behind" in result.output

    def test_zvec_error(self, tmp_path: Path, monkeypatch):
        """Role with zvec shows error table and exits 1."""
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-zvec
            spec:
              role: test
              model:
                provider: openai
                name: gpt-5-mini
              ingest:
                sources: ["*.md"]
                store_backend: zvec
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--role", str(p)])

        assert result.exit_code == 1
        assert "DEP002" in result.output

    def test_max_memories_error(self, tmp_path: Path, monkeypatch):
        """Role with memory.max_memories shows error and exits 1."""
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-maxmem
            spec:
              role: test
              model:
                provider: openai
                name: gpt-5-mini
              memory:
                max_memories: 500
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--role", str(p)])

        assert result.exit_code == 1
        assert "DEP001" in result.output

    def test_yaml_parse_error(self, tmp_path: Path, monkeypatch):
        """Broken YAML shows parse error and exits 1."""
        p = tmp_path / "role.yaml"
        p.write_text(":\n  bad: [yaml\n")

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--role", str(p)])

        assert result.exit_code == 1
        assert "Cannot read" in result.output or "Invalid YAML" in result.output

    def test_error_blocks_quickstart(self, tmp_path: Path, monkeypatch):
        """--role with errors + --quickstart exits at validation, no smoke test."""
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-zvec
            spec:
              role: test
              model:
                provider: openai
                name: gpt-5-mini
              ingest:
                sources: ["*.md"]
                store_backend: zvec
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--role", str(p), "--quickstart"])

        assert result.exit_code == 1
        assert "DEP002" in result.output
        # Should NOT reach the smoke test
        assert "Running quickstart" not in result.output
