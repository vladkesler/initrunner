"""Tests for starter integration with the run command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.exceptions import Exit as ClickExit
from typer.testing import CliRunner

from initrunner.cli._helpers import prepare_starter, resolve_role_path
from initrunner.cli.main import app
from initrunner.services.starters import STARTERS_DIR

runner = CliRunner()


class TestResolveRolePathStarters:
    """Test that resolve_role_path falls back to bundled starters."""

    def test_resolves_starter_by_name(self):
        """initrunner run helpdesk should resolve to the starter YAML."""
        resolved = resolve_role_path(Path("helpdesk"))
        assert resolved.is_file()
        assert "helpdesk" in resolved.name
        assert STARTERS_DIR in resolved.parents or resolved.parent == STARTERS_DIR

    def test_installed_role_takes_priority(self, tmp_path: Path):
        """An installed role with the same name should win over a starter."""
        # Create a mock installed role
        role_dir = tmp_path / "helpdesk"
        role_dir.mkdir()
        role_file = role_dir / "role.yaml"
        role_file.write_text(
            "apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: helpdesk\n"
            "spec:\n  role: custom\n  model:\n    provider: openai\n    name: gpt-5-mini\n"
        )

        with patch(
            "initrunner.registry.resolve_installed_path",
            return_value=role_dir,
        ):
            resolved = resolve_role_path(Path("helpdesk"))
            assert resolved == role_file

    def test_nonexistent_name_fails(self):
        """Unknown name should still fail."""
        with pytest.raises(ClickExit):
            resolve_role_path(Path("definitely-not-a-real-starter"))


class TestPrepareStarter:
    """Test the prepare_starter helper."""

    def test_non_starter_returns_none(self, tmp_path: Path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text("test")
        result = prepare_starter(role_file, None)
        assert result is None

    def test_starter_with_explicit_model_returns_model(self):
        starter_path = STARTERS_DIR / "memory-assistant.yaml"
        result = prepare_starter(starter_path, "anthropic:claude-sonnet-4-5-20250929")
        assert result == "anthropic:claude-sonnet-4-5-20250929"

    def test_starter_auto_detects_model(self):
        from initrunner.cli.run_config import RunConfig
        from initrunner.services.providers import DetectedProvider

        starter_path = STARTERS_DIR / "memory-assistant.yaml"
        fake_providers = [DetectedProvider(provider="openai", model="gpt-5-mini")]
        with (
            patch(
                "initrunner.cli.run_config.load_run_config",
                return_value=RunConfig(),
            ),
            patch(
                "initrunner.services.providers.list_available_providers",
                return_value=fake_providers,
            ),
        ):
            result = prepare_starter(starter_path, None)
            assert result == "openai:gpt-5-mini"

    def test_starter_uses_run_yaml_model(self):
        """Starters should prefer the user's run.yaml config over auto-detect."""
        from initrunner.cli.run_config import RunConfig

        starter_path = STARTERS_DIR / "memory-assistant.yaml"
        cfg = RunConfig(provider="anthropic", model="claude-sonnet-4-6")
        with patch("initrunner.cli.run_config.load_run_config", return_value=cfg):
            result = prepare_starter(starter_path, None)
            assert result == "anthropic:claude-sonnet-4-6"

    def test_starter_with_missing_prerequisites_exits(self):
        starter_path = STARTERS_DIR / "telegram-assistant.yaml"
        with (
            patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": ""}, clear=False),
            pytest.raises(ClickExit),
        ):
            prepare_starter(starter_path, "openai:gpt-5-mini")


class TestRunList:
    """Test that `initrunner run --list` shows starter listing."""

    def test_list_shows_starters(self):
        result = runner.invoke(app, ["run", "--list"])
        assert result.exit_code == 0
        assert "Starter Agents" in result.output
        assert "helpdesk" in result.output

    def test_list_shows_usage_hint(self):
        result = runner.invoke(app, ["run", "--list"])
        assert "initrunner run <name>" in result.output


class TestRunSave:
    """Test the --save flag."""

    def test_save_copies_single_file_starter(self, tmp_path: Path):
        save_dir = tmp_path / "my-agent"
        result = runner.invoke(app, ["run", "memory-assistant", "--save", str(save_dir)])
        assert result.exit_code == 0
        assert (save_dir / "role.yaml").is_file()

    def test_save_copies_composite_starter(self, tmp_path: Path):
        save_dir = tmp_path / "my-pipeline"
        result = runner.invoke(app, ["run", "ci-pipeline", "--save", str(save_dir)])
        assert result.exit_code == 0
        assert (save_dir / "flow.yaml").is_file()
        assert (save_dir / "roles").is_dir()

    def test_save_non_starter_fails(self, tmp_path: Path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            "apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: t\n"
            "spec:\n  role: test\n  model:\n    provider: openai\n    name: gpt-5-mini\n"
        )
        save_dir = tmp_path / "out"
        result = runner.invoke(app, ["run", str(role_file), "--save", str(save_dir)])
        assert result.exit_code == 1
        assert "only works with bundled starters" in result.output
