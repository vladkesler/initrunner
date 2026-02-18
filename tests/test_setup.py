"""Tests for the setup wizard."""

from __future__ import annotations

import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from initrunner.cli.main import app
from initrunner.cli.setup_cmd import needs_setup

runner = CliRunner()

# All tests that enter an API key mock _validate_api_key to avoid network calls
# and the "Re-enter?" prompt that follows validation failures.
_MOCK_VALIDATE = patch("initrunner.cli.setup_cmd._validate_api_key", return_value=True)


@pytest.fixture()
def clean_env(monkeypatch, tmp_path):
    """Remove all provider API keys from the env and set INITRUNNER_HOME to a temp dir."""
    for var in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "CO_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path / "home"))
    from initrunner.config import get_home_dir

    get_home_dir.cache_clear()
    yield tmp_path
    get_home_dir.cache_clear()


class TestNeedsSetup:
    def test_needs_setup_true_fresh(self, clean_env):
        assert needs_setup() is True

    def test_needs_setup_false_env_var(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert needs_setup() is False

    def test_needs_setup_false_dotenv(self, clean_env):
        tmp_path = clean_env
        home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)
        env_path = home / ".env"
        env_path.write_text('OPENAI_API_KEY="sk-from-dotenv"\n')
        assert needs_setup() is False


class TestFreshSetup:
    def test_fresh_setup(self, clean_env):
        """Fresh environment: no existing config, provider from flag, key from stdin."""
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with _MOCK_VALIDATE:
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
                input="sk-test-key-12345\n",
            )
        assert result.exit_code == 0
        assert output.exists()
        env_path = tmp_path / "home" / ".env"
        assert env_path.exists()
        content = env_path.read_text()
        assert "OPENAI_API_KEY" in content
        assert "sk-test-key-12345" in content

    def test_noninteractive_with_env_var(self, clean_env, monkeypatch):
        """All flags + env var set = skips key entry, proceeds to role creation."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        result = runner.invoke(
            app,
            [
                "setup",
                "-y",
                "--provider",
                "openai",
                "--model",
                "gpt-5-mini",
                "--template",
                "chatbot",
                "--skip-test",
                "--interfaces",
                "skip",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0
        assert "Using existing" in result.output
        assert output.exists()


class TestRerunDetection:
    def test_rerun_detection(self, clean_env, monkeypatch):
        """When key exists, wizard detects provider and skips key entry."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        result = runner.invoke(
            app,
            [
                "setup",
                "-y",
                "--provider",
                "openai",
                "--model",
                "gpt-5-mini",
                "--template",
                "chatbot",
                "--skip-test",
                "--interfaces",
                "skip",
            ],
        )
        assert result.exit_code == 0
        assert "Using provider" in result.output


class TestProviderEnvVars:
    @pytest.mark.parametrize(
        "provider,env_var",
        [
            ("anthropic", "ANTHROPIC_API_KEY"),
            ("google", "GOOGLE_API_KEY"),
            ("groq", "GROQ_API_KEY"),
            ("mistral", "MISTRAL_API_KEY"),
            ("cohere", "CO_API_KEY"),
        ],
    )
    def test_provider_writes_correct_env_var(self, clean_env, provider, env_var):
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with patch("initrunner.cli.setup_cmd.require_provider"), _MOCK_VALIDATE:
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    provider,
                    "--model",
                    "test-model",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
                input="test-api-key\n",
            )
        assert result.exit_code == 0
        env_path = tmp_path / "home" / ".env"
        assert env_path.exists()
        content = env_path.read_text()
        assert env_var in content


class TestOllama:
    def test_ollama_skips_api_key(self, clean_env):
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with (
            patch("initrunner.cli.setup_cmd.check_ollama_running"),
            patch("initrunner.cli.setup_cmd._check_ollama_models", return_value=["llama3.2"]),
        ):
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "ollama",
                    "--model",
                    "llama3.2",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
            )
        assert result.exit_code == 0
        # No .env should have been created (no API key needed)
        env_path = tmp_path / "home" / ".env"
        if env_path.exists():
            content = env_path.read_text()
            assert "API_KEY" not in content

    def test_ollama_no_models_warning(self, clean_env):
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with (
            patch("initrunner.cli.setup_cmd.check_ollama_running"),
            patch("initrunner.cli.setup_cmd._check_ollama_models", return_value=[]),
        ):
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "ollama",
                    "--model",
                    "llama3.2",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
            )
        assert result.exit_code == 0
        assert "No Ollama models found" in result.output
        assert "ollama pull" in result.output


class TestSkipTest:
    def test_skip_test_flag(self, clean_env):
        """--skip-test should complete without running the agent."""
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with _MOCK_VALIDATE:
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
                input="sk-test-key\n",
            )
        assert result.exit_code == 0
        assert "Running a quick test" not in result.output
        assert "Setup Complete" in result.output


class TestSdkInstall:
    def test_sdk_install_failure_nonfatal(self, clean_env):
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with (
            patch(
                "initrunner.cli.setup_cmd.require_provider",
                side_effect=RuntimeError("not installed"),
            ),
            patch(
                "initrunner.cli.setup_cmd._install_provider_sdk",
                return_value=False,
            ),
            _MOCK_VALIDATE,
        ):
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "anthropic",
                    "--model",
                    "claude-sonnet-4-5-20250929",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
                # "Install it now?" yes -> install fails -> "Continue anyway?" yes ->
                # API key entry
                input="y\ny\ntest-key\n",
            )
        assert result.exit_code == 0

    def test_uv_preferred_over_pip(self, clean_env):
        """When uv is on PATH, should use uv pip install."""
        with (
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            from initrunner.cli._helpers import install_extra

            install_extra("anthropic")
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "uv"
            assert "pip" in cmd

    def test_pip_fallback(self, clean_env):
        """When uv is not on PATH, should use pip."""
        with (
            patch("shutil.which", return_value=None),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            from initrunner.cli._helpers import install_extra

            install_extra("anthropic")
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == sys.executable
            assert "-m" in cmd
            assert "pip" in cmd


class TestRoleExists:
    def test_role_exists_skipped(self, clean_env):
        """When role file already exists, skip creation and don't overwrite."""
        tmp_path = clean_env
        output = tmp_path / "role.yaml"
        output.write_text("existing content")

        with _MOCK_VALIDATE:
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
                input="sk-test-key\n",
            )
        assert result.exit_code == 0
        assert "skipping role creation" in result.output
        assert output.read_text() == "existing content"


class TestEnvFilePermissions:
    def test_env_file_permissions(self, clean_env):
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with _MOCK_VALIDATE:
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
                input="sk-test-key\n",
            )
        assert result.exit_code == 0
        env_path = tmp_path / "home" / ".env"
        assert env_path.exists()
        mode = env_path.stat().st_mode
        assert stat.S_IMODE(mode) == 0o600


class TestTestRunFailure:
    def test_test_run_failure_nonfatal(self, clean_env):
        """Test run failure should not crash the wizard."""
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with (
            _MOCK_VALIDATE,
            patch(
                "initrunner.agent.loader.load_and_build",
                side_effect=Exception("connection failed"),
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--template",
                    "chatbot",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
                input="sk-test-key\n",
            )
        assert result.exit_code == 0
        assert "Setup Complete" in result.output


class TestPartialSetupRecovery:
    def test_partial_setup_recovery(self, clean_env):
        """When .env with valid key exists but no role.yaml, key is found and reused."""
        tmp_path = clean_env
        home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)
        env_path = home / ".env"
        env_path.write_text('OPENAI_API_KEY="sk-existing-key"\n')
        output = tmp_path / "role.yaml"

        with _MOCK_VALIDATE:
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
            )
        assert result.exit_code == 0
        assert "Using existing" in result.output
        assert output.exists()


class TestWriteFailure:
    def test_write_failure(self, clean_env):
        """When .env write fails, should print key and export instructions."""
        tmp_path = clean_env
        home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)
        output = tmp_path / "role.yaml"

        with (
            patch(
                "initrunner.cli.setup_cmd.set_key",
                side_effect=PermissionError("permission denied"),
            ),
            _MOCK_VALIDATE,
        ):
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
                input="sk-test-key\n",
            )
        assert result.exit_code == 0
        assert "export" in result.output


class TestTemplatePickerChoices:
    @pytest.mark.parametrize(
        "template_choice,expected_content",
        [
            ("chatbot", "You are a helpful assistant"),
            ("rag", "knowledge assistant"),
            ("memory", "long-term memory"),
            ("daemon", "monitoring assistant"),
        ],
    )
    def test_template_picker_choices(self, clean_env, template_choice, expected_content):
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with _MOCK_VALIDATE:
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--template",
                    template_choice,
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
                input="sk-test-key\n",
            )
        assert result.exit_code == 0
        assert output.exists()
        content = output.read_text()
        assert expected_content in content


class TestSecurityDisclaimer:
    def test_disclaimer_shown_without_flag(self, clean_env):
        """Without -y, the disclaimer is shown and declining exits."""
        result = runner.invoke(
            app,
            ["setup", "--provider", "openai", "--model", "gpt-5-mini", "--skip-test"],
            input="n\n",  # Decline the disclaimer
        )
        assert result.exit_code == 0
        assert "Beta Software Notice" in result.output

    def test_disclaimer_accept_continues(self, clean_env):
        """Accepting the disclaimer continues setup."""
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with _MOCK_VALIDATE:
            result = runner.invoke(
                app,
                [
                    "setup",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
                input="y\nsk-test-key\n",  # Accept disclaimer, enter key
            )
        assert result.exit_code == 0
        assert "Beta Software Notice" in result.output
        assert "Setup Complete" in result.output

    def test_disclaimer_skipped_with_flag(self, clean_env):
        """With -y, the disclaimer is not shown."""
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with _MOCK_VALIDATE:
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
                input="sk-test-key\n",
            )
        assert result.exit_code == 0
        assert "Beta Software Notice" not in result.output


class TestNextStepsIngestHint:
    """Tests for the template-aware 'initrunner ingest' hint in next steps."""

    def test_rag_template_shows_ingest_hint(self, clean_env, monkeypatch):
        """RAG template should include 'initrunner ingest' in next steps."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        result = runner.invoke(
            app,
            [
                "setup",
                "-y",
                "--provider",
                "openai",
                "--model",
                "gpt-5-mini",
                "--template",
                "rag",
                "--skip-test",
                "--interfaces",
                "skip",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0
        assert "initrunner ingest" in result.output

    def test_chatbot_template_no_ingest_hint(self, clean_env, monkeypatch):
        """Chatbot template should NOT include 'initrunner ingest' in next steps."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        result = runner.invoke(
            app,
            [
                "setup",
                "-y",
                "--provider",
                "openai",
                "--model",
                "gpt-5-mini",
                "--template",
                "chatbot",
                "--skip-test",
                "--interfaces",
                "skip",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0
        assert "initrunner ingest" not in result.output

    def test_ollama_rag_template_no_ingest_hint(self, clean_env):
        """Ollama + RAG: no ingest hint (Ollama forces its own template)."""
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with (
            patch("initrunner.cli.setup_cmd.check_ollama_running"),
            patch("initrunner.cli.setup_cmd._check_ollama_models", return_value=["llama3.2"]),
        ):
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "ollama",
                    "--model",
                    "llama3.2",
                    "--template",
                    "rag",
                    "--skip-test",
                    "--interfaces",
                    "skip",
                    "--output",
                    str(output),
                ],
            )
        assert result.exit_code == 0
        assert "initrunner ingest" not in result.output


class TestInterfaceInstall:
    """Tests for the interface picker step in the setup wizard."""

    def _base_args(self, output: Path, *, interfaces: str) -> list[str]:
        return [
            "setup",
            "-y",
            "--provider",
            "openai",
            "--model",
            "gpt-5-mini",
            "--template",
            "chatbot",
            "--skip-test",
            "--output",
            str(output),
            "--interfaces",
            interfaces,
        ]

    def test_interfaces_skip(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with patch("initrunner.cli.setup_cmd.install_extra") as mock_install:
            result = runner.invoke(app, self._base_args(output, interfaces="skip"))

        assert result.exit_code == 0
        mock_install.assert_not_called()
        assert "Install later" in result.output

    def test_interfaces_tui(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with patch("initrunner.cli.setup_cmd.install_extra") as mock_install:
            result = runner.invoke(app, self._base_args(output, interfaces="tui"))

        assert result.exit_code == 0
        mock_install.assert_called_once_with("tui")

    def test_interfaces_dashboard(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with patch("initrunner.cli.setup_cmd.install_extra") as mock_install:
            result = runner.invoke(app, self._base_args(output, interfaces="dashboard"))

        assert result.exit_code == 0
        mock_install.assert_called_once_with("dashboard")
        assert "initrunner ui" in result.output

    def test_interfaces_both(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with patch("initrunner.cli.setup_cmd.install_extra") as mock_install:
            result = runner.invoke(app, self._base_args(output, interfaces="both"))

        assert result.exit_code == 0
        assert mock_install.call_count == 2
        mock_install.assert_any_call("tui")
        mock_install.assert_any_call("dashboard")
        assert "initrunner ui" in result.output

    def test_interactive_number_input(self, clean_env, monkeypatch):
        """Typing '1' in the interactive picker selects tui."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with patch("initrunner.cli.setup_cmd.install_extra") as mock_install:
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="1\n",  # pick tui
            )

        assert result.exit_code == 0
        mock_install.assert_called_once_with("tui")

    def test_interactive_skip_number(self, clean_env, monkeypatch):
        """Typing '4' in the interactive picker skips installation."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with patch("initrunner.cli.setup_cmd.install_extra") as mock_install:
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="4\n",  # skip
            )

        assert result.exit_code == 0
        mock_install.assert_not_called()
        assert "Install later" in result.output

    def test_interactive_invalid_defaults_to_skip(self, clean_env, monkeypatch):
        """Invalid input defaults to skip."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with patch("initrunner.cli.setup_cmd.install_extra") as mock_install:
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--template",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="banana\n",
            )

        assert result.exit_code == 0
        mock_install.assert_not_called()
        assert "Invalid choice" in result.output
