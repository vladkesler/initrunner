"""Tests for the setup wizard."""

from __future__ import annotations

import stat
import sys
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
        "XAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path / "home"))
    from initrunner.config import get_home_dir

    get_home_dir.cache_clear()
    yield tmp_path
    get_home_dir.cache_clear()


class TestNeedsSetup:
    def test_needs_setup_true_fresh(self, clean_env):
        with patch("initrunner.services.providers._is_ollama_running", return_value=False):
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
                    "--intent",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="sk-test-key-12345\n\n",  # key + accept default tools
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
                "--intent",
                "chatbot",
                "--skip-test",
                "--output",
                str(output),
            ],
            input="\n",  # accept default tools
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
                "--intent",
                "chatbot",
                "--skip-test",
            ],
            input="\n",  # accept default tools
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
                    "--intent",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="test-api-key\n\n",  # key + accept default tools
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
            patch("initrunner.cli.setup_cmd.check_ollama_models", return_value=["llama3.2"]),
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
                    "--intent",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="\n",  # accept default tools
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
            patch("initrunner.cli.setup_cmd.check_ollama_models", return_value=[]),
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
                    "--intent",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="\n",  # accept default tools
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
                    "--intent",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="sk-test-key\n\n",  # key + accept default tools
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
                    "--intent",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                # "Install it now?" yes -> install fails -> "Continue anyway?" yes ->
                # API key entry + accept default tools
                input="y\ny\ntest-key\n\n",
            )
        assert result.exit_code == 0

    def test_uv_tool_env_uses_uv_tool_install(self, clean_env):
        """When sys.executable is in a uv tool env and uv is on PATH, use uv tool install."""
        with (
            patch("sys.executable", "/home/user/.local/share/uv/tools/initrunner/bin/python"),
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            from initrunner.cli._helpers import install_extra

            install_extra("anthropic")
            cmd = mock_run.call_args[0][0]
            assert cmd == ["uv", "tool", "install", "--force", "initrunner[anthropic]"]

    def test_pipx_env_uses_pipx_install(self, clean_env):
        """When sys.executable is in a pipx venv and pipx is on PATH, use pipx install --force."""

        def which_side_effect(name):
            return "/usr/bin/pipx" if name == "pipx" else None

        with (
            patch(
                "sys.executable",
                "/home/user/.local/share/pipx/venvs/initrunner/bin/python",
            ),
            patch("shutil.which", side_effect=which_side_effect),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            from initrunner.cli._helpers import install_extra

            install_extra("anthropic")
            cmd = mock_run.call_args[0][0]
            assert cmd == ["pipx", "install", "--force", "initrunner[anthropic]"]

    def test_pipx_env_without_pipx_falls_back_to_interpreter_pip(self, clean_env):
        """When sys.executable is in a pipx venv but pipx not on PATH, use sys.executable -m pip."""
        fake_exe = "/home/user/.local/share/pipx/venvs/initrunner/bin/python"
        with (
            patch("sys.executable", fake_exe),
            patch("shutil.which", return_value=None),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            from initrunner.cli._helpers import install_extra

            install_extra("anthropic")
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == fake_exe
            assert cmd[1:] == ["-m", "pip", "install", "initrunner[anthropic]"]

    def test_uv_preferred_over_pip(self, clean_env):
        """When uv is on PATH (non-tool env), should use uv pip install."""
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

    def test_failure_output_escapes_extras_brackets(self, clean_env):
        """When install fails, [extra] brackets must appear literally in the warning."""
        import subprocess
        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        recorded_console = Console(file=buf, no_color=True)

        with (
            patch("initrunner.cli._helpers.console", recorded_console),
            patch("shutil.which", return_value=None),
            patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(1, ["pip"]),
            ),
        ):
            from initrunner.cli._helpers import install_extra

            result = install_extra("anthropic")
            output = buf.getvalue()

        assert result is False
        assert "[anthropic]" in output

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
                    "--intent",
                    "chatbot",
                    "--skip-test",
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
                    "--intent",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="sk-test-key\n\n",  # key + accept default tools
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
                    "--intent",
                    "chatbot",
                    "--output",
                    str(output),
                ],
                input="sk-test-key\n\n",  # key + accept default tools
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
                    "--intent",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="\n",  # accept default tools
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
                    "--intent",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="sk-test-key\n\n",  # key + accept default tools
            )
        assert result.exit_code == 0
        assert "export" in result.output


class TestIntentPickerChoices:
    @pytest.mark.parametrize(
        "intent_choice,expected_content,extra_input",
        [
            ("chatbot", "You are a helpful assistant", ""),
            ("knowledge", "knowledge assistant", "\n"),  # doc sources prompt
            ("memory", "long-term memory", ""),
            ("daemon", "monitoring assistant", "\n\n"),  # trigger type + watch paths
        ],
    )
    def test_intent_picker_choices(self, clean_env, intent_choice, expected_content, extra_input):
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
                    "--intent",
                    intent_choice,
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input=f"sk-test-key\n\n{extra_input}",  # key + tools + intent-specific
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
                    "--intent",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="y\nsk-test-key\n\n",  # Accept disclaimer, key, tools
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
                    "--intent",
                    "chatbot",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="sk-test-key\n\n",  # key + accept default tools
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
                "--intent",
                "knowledge",
                "--skip-test",
                "--output",
                str(output),
            ],
            input="\n\n",  # accept default tools + default doc sources
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
                "--intent",
                "chatbot",
                "--skip-test",
                "--output",
                str(output),
            ],
            input="\n",  # accept default tools
        )
        assert result.exit_code == 0
        assert "initrunner ingest" not in result.output

    def test_ollama_rag_template_shows_ingest_hint(self, clean_env):
        """Ollama + RAG: ingest hint shown (bug fix — no longer overrides template)."""
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with (
            patch("initrunner.cli.setup_cmd.check_ollama_running"),
            patch("initrunner.cli.setup_cmd.check_ollama_models", return_value=["llama3.2"]),
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
                    "--intent",
                    "knowledge",
                    "--skip-test",
                    "--output",
                    str(output),
                ],
                input="n\n\n\n",  # decline embedding key + tools + doc sources
            )
        assert result.exit_code == 0
        assert "initrunner ingest" in result.output


class TestIntentSetup:
    """Tests for the new --intent flag."""

    def test_intent_chatbot(self, clean_env, monkeypatch):
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
                "--intent",
                "chatbot",
                "--skip-test",
                "--skip-chat-yaml",
                "--output",
                str(output),
            ],
            input="\n",  # accept default tools
        )
        assert result.exit_code == 0
        assert output.exists()
        content = output.read_text()
        assert "You are a helpful assistant" in content

    def test_intent_knowledge(self, clean_env, monkeypatch):
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
                "--intent",
                "knowledge",
                "--skip-test",
                "--skip-chat-yaml",
                "--output",
                str(output),
            ],
            input="\n\n",  # accept default tools + default doc sources
        )
        assert result.exit_code == 0
        assert output.exists()
        content = output.read_text()
        assert "knowledge assistant" in content.lower()
        assert "ingest" in content

    def test_intent_knowledge_provider_ollama(self, clean_env):
        """--intent knowledge --provider ollama produces YAML with ingest section."""
        tmp_path = clean_env
        output = tmp_path / "role.yaml"

        with (
            patch("initrunner.cli.setup_cmd.check_ollama_running"),
            patch("initrunner.cli.setup_cmd.check_ollama_models", return_value=["llama3.2"]),
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
                    "--intent",
                    "knowledge",
                    "--skip-test",
                    "--skip-chat-yaml",
                    "--output",
                    str(output),
                ],
                input="n\n\n\n",  # decline embedding key + accept default tools + doc sources
            )
        assert result.exit_code == 0
        assert output.exists()
        import yaml

        data = yaml.safe_load(output.read_text())
        assert "ingest" in data["spec"]
        assert data["spec"]["model"]["provider"] == "ollama"

    def test_intent_telegram_bot(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
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
                "--intent",
                "telegram-bot",
                "--skip-test",
                "--skip-chat-yaml",
                "--output",
                str(output),
            ],
            input="\n",  # accept default tools
        )
        assert result.exit_code == 0
        assert output.exists()
        content = output.read_text()
        assert "telegram" in content.lower()


class TestSkipChatYaml:
    def test_skip_chat_yaml(self, clean_env, monkeypatch):
        """--skip-chat-yaml should not create chat.yaml."""
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
                "--intent",
                "chatbot",
                "--skip-test",
                "--skip-chat-yaml",
                "--output",
                str(output),
            ],
            input="\n",  # accept default tools
        )
        assert result.exit_code == 0
        chat_yaml = tmp_path / "home" / "chat.yaml"
        assert not chat_yaml.exists()
