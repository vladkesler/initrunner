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
        """--export-report with --dry-run writes a report file."""
        report_file = tmp_path / "report.md"

        result_obj = _successful_run_result()

        with patch("initrunner.cli.run_cmd.command_context", _mock_command_context()):
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
                        "--export-report",
                        "--report-path",
                        str(report_file),
                    ],
                )

        assert result.exit_code == 0, result.output
        assert report_file.exists()
        content = report_file.read_text()
        assert "# Agent Run Report" in content

    def test_export_report_with_template(self, tmp_path: Path):
        """--report-template pr-review uses the pr-review template."""
        report_file = tmp_path / "review.md"
        result_obj = _successful_run_result()

        with patch("initrunner.cli.run_cmd.command_context", _mock_command_context()):
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
                        "--export-report",
                        "--report-path",
                        str(report_file),
                        "--report-template",
                        "pr-review",
                    ],
                )

        assert result.exit_code == 0, result.output
        assert report_file.exists()
        content = report_file.read_text()
        assert "# PR Review Report" in content

    def test_export_report_invalid_template(self):
        """Unknown --report-template errors before execution."""
        with patch("initrunner.cli.run_cmd.command_context", _mock_command_context()):
            result = runner.invoke(
                app,
                [
                    "run",
                    "fake-role.yaml",
                    "-p",
                    "Hello",
                    "--export-report",
                    "--report-template",
                    "nonexistent",
                ],
            )

        assert result.exit_code == 1
        assert "Unknown template" in result.output

    def test_export_report_failed_run(self, tmp_path: Path):
        """Report is still written when the run fails."""
        report_file = tmp_path / "report.md"
        result_obj = _failed_run_result()

        with patch("initrunner.cli.run_cmd.command_context", _mock_command_context()):
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
                        "--export-report",
                        "--report-path",
                        str(report_file),
                    ],
                )

        assert result.exit_code == 0, result.output
        assert report_file.exists()
        content = report_file.read_text()
        assert "Failed" in content
        assert "Model API error: 500" in content
