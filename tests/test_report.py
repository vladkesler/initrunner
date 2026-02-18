"""Tests for initrunner.report — ReportContext, rendering, and export."""

from __future__ import annotations

from pathlib import Path

import pytest

from initrunner.agent.executor import AutonomousResult, RunResult
from initrunner.report import (
    BUILT_IN_TEMPLATES,
    build_report_context,
    export_report,
    render_report,
)
from tests.conftest import make_role


def _make_run_result(**kwargs) -> RunResult:
    defaults = {
        "run_id": "test-run-001",
        "output": "Hello, world!",
        "tokens_in": 10,
        "tokens_out": 5,
        "total_tokens": 15,
        "tool_calls": 0,
        "duration_ms": 100,
        "success": True,
        "error": None,
    }
    defaults.update(kwargs)
    return RunResult(**defaults)


def _make_autonomous_result(**kwargs) -> AutonomousResult:
    iteration = _make_run_result(run_id="iter-001")
    defaults = {
        "run_id": "auto-run-001",
        "iterations": [iteration],
        "final_output": "Done.",
        "final_status": "completed",
        "finish_summary": "Task completed successfully.",
        "total_tokens_in": 10,
        "total_tokens_out": 5,
        "total_tokens": 15,
        "total_tool_calls": 0,
        "total_duration_ms": 200,
        "iteration_count": 1,
        "success": True,
        "error": None,
    }
    defaults.update(kwargs)
    return AutonomousResult(**defaults)


class TestBuildReportContext:
    def test_single_shot(self):
        role = make_role()
        result = _make_run_result()
        ctx = build_report_context(role, result, "Hello")

        assert ctx.agent_name == "test-agent"
        assert ctx.run_id == "test-run-001"
        assert ctx.prompt == "Hello"
        assert ctx.output == "Hello, world!"
        assert ctx.tokens_in == 10
        assert ctx.tokens_out == 5
        assert ctx.total_tokens == 15
        assert ctx.success is True
        assert ctx.autonomous is False
        assert ctx.iteration_count == 0
        assert ctx.iterations == []

    def test_autonomous(self):
        role = make_role()
        result = _make_autonomous_result()
        ctx = build_report_context(role, result, "Do something")

        assert ctx.autonomous is True
        assert ctx.iteration_count == 1
        assert len(ctx.iterations) == 1
        assert ctx.final_status == "completed"
        assert ctx.finish_summary == "Task completed successfully."
        assert ctx.output == "Done."

    def test_dry_run_flag(self):
        role = make_role()
        result = _make_run_result()
        ctx = build_report_context(role, result, "Test", dry_run=True)
        assert ctx.dry_run is True


class TestRenderReport:
    def test_render_default(self):
        role = make_role()
        result = _make_run_result()
        ctx = build_report_context(role, result, "Hello")
        rendered = render_report(ctx, "default")

        assert "# Agent Run Report" in rendered
        assert "Hello, world!" in rendered
        assert "test-agent" in rendered

    def test_render_pr_review(self):
        role = make_role()
        result = _make_run_result()
        ctx = build_report_context(role, result, "Review this PR")
        rendered = render_report(ctx, "pr-review")

        assert "# PR Review Report" in rendered
        assert "Hello, world!" in rendered

    def test_render_changelog(self):
        role = make_role()
        result = _make_run_result()
        ctx = build_report_context(role, result, "Generate changelog")
        rendered = render_report(ctx, "changelog")

        assert "# Changelog Report" in rendered
        assert "Hello, world!" in rendered

    def test_render_ci_fix(self):
        role = make_role()
        result = _make_run_result()
        ctx = build_report_context(role, result, "Fix CI")
        rendered = render_report(ctx, "ci-fix")

        assert "# CI Fix Analysis" in rendered
        assert "Hello, world!" in rendered

    def test_render_unknown_raises(self):
        role = make_role()
        result = _make_run_result()
        ctx = build_report_context(role, result, "Test")

        with pytest.raises(ValueError, match="Unknown report template"):
            render_report(ctx, "nonexistent")

    def test_all_built_in_templates_render(self):
        role = make_role()
        result = _make_run_result()
        ctx = build_report_context(role, result, "Test")

        for name in BUILT_IN_TEMPLATES:
            rendered = render_report(ctx, name)
            assert len(rendered) > 0


class TestExportReport:
    def test_export_writes_file(self, tmp_path: Path):
        role = make_role()
        result = _make_run_result()
        out = tmp_path / "report.md"

        path = export_report(role, result, "Hello", out)

        assert path.exists()
        content = path.read_text()
        assert "Hello, world!" in content
        assert "# Agent Run Report" in content

    def test_export_dry_run_marker(self, tmp_path: Path):
        role = make_role()
        result = _make_run_result()
        out = tmp_path / "report.md"

        export_report(role, result, "Test", out, dry_run=True)

        content = out.read_text()
        assert "dry-run" in content

    def test_export_failed_run(self, tmp_path: Path):
        role = make_role()
        result = _make_run_result(success=False, error="Model API error: 500", output="")
        out = tmp_path / "report.md"

        export_report(role, result, "Test", out)

        content = out.read_text()
        assert "Failed" in content
        assert "Model API error: 500" in content

    def test_export_with_template(self, tmp_path: Path):
        role = make_role()
        result = _make_run_result()
        out = tmp_path / "report.md"

        export_report(role, result, "Test", out, template_name="pr-review")

        content = out.read_text()
        assert "# PR Review Report" in content
