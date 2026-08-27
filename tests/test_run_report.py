"""Tests for --export-report and --report-template CLI options."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from initrunner.agent.executor import RunResult
from initrunner.cli.main import app

runner = CliRunner()


def _mock_command_context(role=None, agent=None):
    """Build a mock command_context that yields (role, agent, None, None, None)."""
    from contextlib import contextmanager

    from tests.conftest import make_role

    @contextmanager
    def _ctx(*args, **kwargs):
        r = role or make_role()
        a = agent or MagicMock()
        yield r, a, None, None, None

    return _ctx


def _passthrough_resolve(path):
    """Identity resolve — used to skip path resolution in tests with fake paths."""
    return path


def _passthrough_run_target(path):
    """Identity resolve returning (path, 'Agent') for run target resolution."""
    return path, "Agent"


def _successful_run_result() -> RunResult:
    return RunResult(
        run_id="test-001",
        output="[dry-run] Simulated response.",
        tokens_in=10,
        tokens_out=5,
        total_tokens=15,
        tool_calls=0,
        duration_ms=50,
        success=True,
        error=None,
    )


def _failed_run_result() -> RunResult:
    return RunResult(
        run_id="test-002",
        output="",
        tokens_in=5,
        tokens_out=0,
        total_tokens=5,
        tool_calls=0,
        duration_ms=30,
        success=False,
        error="Model API error: 500",
    )


class TestExportReportCLI:
    def test_export_report_single_shot(self, tmp_path: Path):
        """--report PATH with --dry-run writes a report file."""
        report_file = tmp_path / "report.md"

        result_obj = _successful_run_result()

        with (
            patch("initrunner.cli.run_cmd._command.resolve_run_target", _passthrough_run_target),
            patch("initrunner.cli.run_cmd._command.preflight_validate_or_exit", lambda _p: None),
            patch("initrunner.cli._run_agent.command_context", _mock_command_context()),
        ):
            with patch("initrunner.runner.run_single") as mock_run:
                mock_run.return_value = (result_obj, [])
                result = runner.invoke(
                    app,
                    [
                        "run",
                        "fake-role.yaml",
                        "-p",
                        "Hello",
                        "--dry-run",
                        "--report",
                        str(report_file),
                        "--format",
                        "rich",
                    ],
                )

        assert result.exit_code == 0, result.output
        assert report_file.exists()
        content = report_file.read_text()
        assert "# Agent Run Report" in content

    def test_export_report_with_template(self, tmp_path: Path):
        """--report pr-review:PATH uses the pr-review template."""
        report_file = tmp_path / "review.md"
        result_obj = _successful_run_result()

        with (
            patch("initrunner.cli.run_cmd._command.resolve_run_target", _passthrough_run_target),
            patch("initrunner.cli.run_cmd._command.preflight_validate_or_exit", lambda _p: None),
            patch("initrunner.cli._run_agent.command_context", _mock_command_context()),
        ):
            with patch("initrunner.runner.run_single") as mock_run:
                mock_run.return_value = (result_obj, [])
                result = runner.invoke(
                    app,
                    [
                        "run",
                        "fake-role.yaml",
                        "-p",
                        "Hello",
                        "--dry-run",
                        "--report",
                        f"pr-review:{report_file}",
                        "--format",
                        "rich",
                    ],
                )

        assert result.exit_code == 0, result.output
        assert report_file.exists()
        content = report_file.read_text()
        assert "# PR Review Report" in content

    def test_unknown_template_prefix_is_treated_as_a_path(self, tmp_path: Path):
        """Only a built-in name is a template prefix; anything else is the path."""
        from initrunner.report import parse_report_spec

        assert parse_report_spec("nonexistent:out.md") == (
            "default",
            Path("nonexistent:out.md"),
        )

    def test_missing_path_after_template_errors(self):
        with (
            patch("initrunner.cli.run_cmd._command.resolve_run_target", _passthrough_run_target),
            patch("initrunner.cli.run_cmd._command.preflight_validate_or_exit", lambda _p: None),
            patch("initrunner.cli._run_agent.command_context", _mock_command_context()),
        ):
            result = runner.invoke(
                app, ["run", "fake-role.yaml", "-p", "Hello", "--report", "pr-review:"]
            )

        assert result.exit_code == 1
        assert "missing PATH" in result.output

    def test_export_report_failed_run(self, tmp_path: Path):
        """Report is still written when the run fails."""
        report_file = tmp_path / "report.md"
        result_obj = _failed_run_result()

        with (
            patch("initrunner.cli.run_cmd._command.resolve_run_target", _passthrough_run_target),
            patch("initrunner.cli.run_cmd._command.preflight_validate_or_exit", lambda _p: None),
            patch("initrunner.cli._run_agent.command_context", _mock_command_context()),
        ):
            with patch("initrunner.runner.run_single") as mock_run:
                mock_run.return_value = (result_obj, [])
                result = runner.invoke(
                    app,
                    [
                        "run",
                        "fake-role.yaml",
                        "-p",
                        "Hello",
                        "--dry-run",
                        "--report",
                        str(report_file),
                        "--format",
                        "rich",
                    ],
                )

        assert result.exit_code == 0, result.output
        assert report_file.exists()
        content = report_file.read_text()
        assert "Failed" in content
        assert "Model API error: 500" in content


class TestParseReportSpec:
    """--report takes PATH or TEMPLATE:PATH."""

    def test_bare_path_uses_default_template(self):
        from initrunner.report import parse_report_spec

        assert parse_report_spec("out.md") == ("default", Path("out.md"))

    def test_template_prefix_is_split(self):
        from initrunner.report import parse_report_spec

        assert parse_report_spec("changelog:/tmp/x.md") == ("changelog", Path("/tmp/x.md"))

    def test_windows_drive_letter_stays_a_path(self):
        from initrunner.report import parse_report_spec

        template, path = parse_report_spec(r"C:\reports\out.md")
        assert template == "default"
        assert str(path) == r"C:\reports\out.md"

    def test_colon_in_a_relative_path_stays_a_path(self):
        from initrunner.report import parse_report_spec

        assert parse_report_spec("a:b/out.md") == ("default", Path("a:b/out.md"))

    def test_empty_path_after_template_raises(self):
        import pytest

        from initrunner.report import parse_report_spec

        with pytest.raises(ValueError, match="missing PATH"):
            parse_report_spec("pr-review:")
