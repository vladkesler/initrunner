"""Tests for the setup wizard."""

from __future__ import annotations

import stat
import sys
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from initrunner.cli.main import app
from initrunner.services.setup import needs_setup

runner = CliRunner()

# All tests that enter an API key mock _validate_api_key to avoid network calls
# and the "Re-enter?" prompt that follows validation failures.
_MOCK_VALIDATE = patch("initrunner.services.setup.validate_api_key", return_value=True)

# Common mock for list_detected_providers (patched at the import location)
_PATCH_DETECTED = "initrunner.cli.setup_cmd.list_detected_providers"


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
        "OPENROUTER_API_KEY",
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
    def test_fresh_setup_creates_run_yaml(self, clean_env):
        """Fresh environment: provider from flag, key from stdin, creates run.yaml."""
        tmp_path = clean_env

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
                    "--skip-test",
                ],
                input="sk-test-key-12345\n",
            )
        assert result.exit_code == 0
        env_path = tmp_path / "home" / ".env"
        assert env_path.exists()
        content = env_path.read_text()
        assert "OPENAI_API_KEY" in content
        assert "sk-test-key-12345" in content
        run_yaml = tmp_path / "home" / "run.yaml"
        assert run_yaml.exists()

    def test_noninteractive_with_env_var(self, clean_env, monkeypatch):
        """All flags + env var set = skips key entry."""
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
                "--skip-test",
            ],
        )
        assert result.exit_code == 0
        assert "Using existing" in result.output


class TestRerunDetection:
    def test_rerun_detection(self, clean_env, monkeypatch):
        """When key exists, wizard detects provider and pre-selects it."""
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
                "--skip-test",
            ],
        )
        assert result.exit_code == 0
        assert "Using existing" in result.output


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
                    "--skip-test",
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
                    "--skip-test",
                ],
            )
        assert result.exit_code == 0
        # No .env should have been created (no API key needed)
        env_path = tmp_path / "home" / ".env"
        if env_path.exists():
            content = env_path.read_text()
            assert "API_KEY" not in content

    def test_ollama_no_models_warning(self, clean_env):
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
                    "--skip-test",
                ],
            )
        assert result.exit_code == 0
        assert "No Ollama models found" in result.output
        assert "ollama pull" in result.output


class TestSkipTest:
    def test_skip_test_flag(self, clean_env, monkeypatch):
        """--skip-test should complete without connectivity messaging."""
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
                "--skip-test",
            ],
        )
        assert result.exit_code == 0
        assert "connectivity" not in result.output.lower()
        assert "Setup Complete" in result.output


class TestSdkInstall:
    def test_sdk_install_failure_nonfatal(self, clean_env):
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
                    "claude-sonnet-4-6",
                    "--skip-test",
                ],
                # "Install it now?" yes -> install fails -> "Continue anyway?" yes ->
                # API key entry
                input="y\ny\ntest-key\n",
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
            patch("initrunner.cli._helpers._display.console", recorded_console),
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


class TestEnvFilePermissions:
    def test_env_file_permissions(self, clean_env):
        tmp_path = clean_env

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
                    "--skip-test",
                ],
                input="sk-test-key\n",
            )
        assert result.exit_code == 0
        env_path = tmp_path / "home" / ".env"
        assert env_path.exists()
        mode = env_path.stat().st_mode
        assert stat.S_IMODE(mode) == 0o600


class TestPartialSetupRecovery:
    def test_partial_setup_recovery(self, clean_env):
        """When .env with valid key exists, key is found and reused."""
        tmp_path = clean_env
        home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)
        env_path = home / ".env"
        env_path.write_text('OPENAI_API_KEY="sk-existing-key"\n')

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
                    "--skip-test",
                ],
            )
        assert result.exit_code == 0
        assert "Using existing" in result.output


class TestWriteFailure:
    def test_write_failure(self, clean_env):
        """When .env write fails, should print key and export instructions."""
        tmp_path = clean_env
        home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)

        with (
            patch(
                "dotenv.set_key",
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
                    "--skip-test",
                ],
                input="sk-test-key\n",
            )
        assert result.exit_code == 0
        assert "export" in result.output


class TestSecurityDisclaimer:
    def test_disclaimer_shown_without_flag(self, clean_env):
        """Without -y, the disclaimer is shown and declining exits."""
        result = runner.invoke(
            app,
            ["setup", "--provider", "openai", "--model", "gpt-5-mini", "--skip-test"],
            input="n\n",  # Decline the disclaimer
        )
        assert result.exit_code == 0
        assert "execute tools" in result.output

    def test_disclaimer_accept_continues(self, clean_env):
        """Accepting the disclaimer continues setup."""
        with _MOCK_VALIDATE:
            result = runner.invoke(
                app,
                [
                    "setup",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--skip-test",
                ],
                input="y\nsk-test-key\n",  # Accept disclaimer, key
            )
        assert result.exit_code == 0
        assert "execute tools" in result.output
        assert "Setup Complete" in result.output

    def test_disclaimer_skipped_with_flag(self, clean_env):
        """With -y, the disclaimer is not shown."""
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
                    "--skip-test",
                ],
                input="sk-test-key\n",
            )
        assert result.exit_code == 0
        assert "security guide" not in result.output


class TestDashboardPrompt:
    """Tests for the dashboard prompt at the end of setup."""

    def test_dashboard_prompt_declined_shows_next_steps(self, clean_env, monkeypatch):
        """Dashboard installed + decline -> shows next steps with starters."""
        import io

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        class _FakeTTY(io.BytesIO):
            def isatty(self):
                return True

        with patch("initrunner.cli.setup_cmd.is_dashboard_available", return_value=True):
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--skip-test",
                ],
                input=_FakeTTY(b"n\n"),  # decline dashboard
            )
        assert result.exit_code == 0
        assert "Open the dashboard?" in result.output
        assert "Next steps" in result.output
        assert "initrunner run helpdesk" in result.output

    def test_dashboard_not_available_shows_next_steps(self, clean_env, monkeypatch):
        """Dashboard not installed -> no prompt, shows next steps."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("initrunner.cli.setup_cmd.is_dashboard_available", return_value=False):
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--skip-test",
                ],
            )
        assert result.exit_code == 0
        assert "Open the dashboard?" not in result.output
        assert "Next steps" in result.output


class TestSkipRunYaml:
    def test_skip_run_yaml(self, clean_env, monkeypatch):
        """--skip-run-yaml should not create run.yaml."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        tmp_path = clean_env

        result = runner.invoke(
            app,
            [
                "setup",
                "-y",
                "--provider",
                "openai",
                "--model",
                "gpt-5-mini",
                "--skip-test",
                "--skip-run-yaml",
            ],
        )
        assert result.exit_code == 0
        run_yaml = tmp_path / "home" / "run.yaml"
        assert not run_yaml.exists()


class TestSummaryPanel:
    def test_summary_shows_provider_and_model(self, clean_env, monkeypatch):
        """Summary panel should show provider and model."""
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
                "--skip-test",
            ],
        )
        assert result.exit_code == 0
        assert "Setup Complete" in result.output
        assert "openai" in result.output
        assert "gpt-5-mini" in result.output


class TestNextStepsStarters:
    def test_next_steps_show_starter_commands(self, clean_env, monkeypatch):
        """Next steps should show starter agent commands."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("initrunner.cli.setup_cmd.is_dashboard_available", return_value=False):
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5-mini",
                    "--skip-test",
                ],
            )
        assert result.exit_code == 0
        assert "initrunner run helpdesk" in result.output
        assert "initrunner run reviewer" in result.output
        assert "initrunner run scout" in result.output


class TestAutoDetectProvider:
    """Tests for the three-branch auto-detect logic in run_setup()."""

    def test_single_provider_auto_confirmed(self, clean_env, monkeypatch):
        """One key detected -> confirm yes -> auto-selects that provider."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        with (
            patch(_PATCH_DETECTED, return_value=[("anthropic", "ANTHROPIC_API_KEY")]),
            patch("initrunner.cli.setup_cmd.require_provider"),
            _MOCK_VALIDATE,
        ):
            result = runner.invoke(
                app,
                ["setup", "-y", "--model", "test-model", "--skip-test"],
                input="y\n",  # confirm auto-detect
            )
        assert result.exit_code == 0
        assert "Detected anthropic" in result.output
        assert "Setup Complete" in result.output

    def test_single_provider_declined_shows_detected_chooser(self, clean_env, monkeypatch):
        """One key detected -> decline -> shows detected chooser."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        with (
            patch(
                _PATCH_DETECTED,
                return_value=[("anthropic", "ANTHROPIC_API_KEY")],
            ),
            patch("initrunner.cli.setup_cmd.require_provider"),
            _MOCK_VALIDATE,
        ):
            result = runner.invoke(
                app,
                ["setup", "-y", "--model", "test-model", "--skip-test"],
                input="n\n1\n",  # decline auto, pick first from chooser
            )
        assert result.exit_code == 0
        assert "Detected providers" in result.output

    def test_multiple_providers_filtered_menu(self, clean_env, monkeypatch):
        """Two keys detected -> shows only those two in the menu."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with (
            patch(
                _PATCH_DETECTED,
                return_value=[
                    ("anthropic", "ANTHROPIC_API_KEY"),
                    ("openai", "OPENAI_API_KEY"),
                ],
            ),
            patch("initrunner.cli.setup_cmd.require_provider"),
            _MOCK_VALIDATE,
        ):
            result = runner.invoke(
                app,
                ["setup", "-y", "--model", "test-model", "--skip-test"],
                input="1\n",  # pick first (anthropic)
            )
        assert result.exit_code == 0
        assert "Detected providers" in result.output
        assert "anthropic" in result.output
        assert "openai" in result.output
        # Should NOT show the full provider list (e.g. groq, cohere)
        assert "groq" not in result.output.lower().split("setup complete")[0]

    def test_zero_providers_full_menu(self, clean_env):
        """No keys detected -> shows full 9-provider menu."""
        with (
            patch(_PATCH_DETECTED, return_value=[]),
            patch("initrunner.cli.setup_cmd.require_provider"),
            _MOCK_VALIDATE,
        ):
            result = runner.invoke(
                app,
                ["setup", "-y", "--model", "test-model", "--skip-test"],
                input="1\nsk-test-key\n",  # pick openai, enter key
            )
        assert result.exit_code == 0
        assert "Cloud providers" in result.output

    def test_ollama_only_auto_confirm(self, clean_env):
        """Ollama running, no keys -> confirms 'Ollama (running locally)'."""
        with (
            patch(_PATCH_DETECTED, return_value=[("ollama", "")]),
            patch("initrunner.cli.setup_cmd.check_ollama_running"),
            patch("initrunner.cli.setup_cmd.check_ollama_models", return_value=["llama3.2"]),
        ):
            result = runner.invoke(
                app,
                ["setup", "-y", "--model", "llama3.2", "--skip-test"],
                input="y\n",
            )
        assert result.exit_code == 0
        assert "Ollama (running locally)" in result.output

    def test_openrouter_detected_and_confirmed(self, clean_env, monkeypatch):
        """OPENROUTER_API_KEY set -> detects OpenRouter preset."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

        with (
            patch(
                _PATCH_DETECTED,
                return_value=[("openrouter", "OPENROUTER_API_KEY")],
            ),
            patch("initrunner.cli.setup_cmd.require_provider"),
        ):
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--model",
                    "anthropic/claude-sonnet-4",
                    "--skip-test",
                ],
                input="y\n",  # confirm auto-detect
            )
        assert result.exit_code == 0
        assert "OpenRouter" in result.output

    def test_openrouter_writes_canonical_run_yaml(self, clean_env, monkeypatch):
        """OpenRouter selection writes run.yaml with canonical runtime config."""
        tmp_path = clean_env
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

        with (
            patch(
                _PATCH_DETECTED,
                return_value=[("openrouter", "OPENROUTER_API_KEY")],
            ),
            patch("initrunner.cli.setup_cmd.require_provider"),
        ):
            result = runner.invoke(
                app,
                [
                    "setup",
                    "-y",
                    "--model",
                    "anthropic/claude-sonnet-4",
                    "--skip-test",
                ],
                input="y\n",
            )
        assert result.exit_code == 0
        run_yaml = tmp_path / "home" / "run.yaml"
        assert run_yaml.exists()
        content = run_yaml.read_text()
        assert "provider: openai" in content
        assert "base_url: https://openrouter.ai/api/v1" in content
        assert "api_key_env: OPENROUTER_API_KEY" in content

    def test_needs_setup_false_with_openrouter(self, clean_env, monkeypatch):
        """needs_setup() returns False when only OPENROUTER_API_KEY is set."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        assert needs_setup() is False
