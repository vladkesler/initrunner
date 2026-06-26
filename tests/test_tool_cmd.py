"""Tests for the `initrunner tool new` CLI command."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from initrunner.cli.tool_cmd import app
from initrunner.services.tool_builder import ToolScaffold

runner = CliRunner()

_MODULE_SRC = 'async def fetch_pr_diff() -> str:\n    """Fetch a diff."""\n    return "ok"\n'


def _scaffold() -> ToolScaffold:
    return ToolScaffold(
        module_name="fetch_pr_diff",
        module_source=_MODULE_SRC,
        test_source="def test_smoke():\n    assert True\n",
        function_names=["fetch_pr_diff"],
        yaml_snippet="tools:\n  - type: custom\n    module: fetch_pr_diff",
        explanation="Module: fetch_pr_diff\nFetches a GitHub PR diff.",
        warnings=[],
    )


def _patches():
    return (
        patch("initrunner.services.tool_builder.scaffold_tool", return_value=_scaffold()),
        patch("initrunner._compat.require_provider"),
        patch(
            "initrunner.agent.loader.detect_default_model",
            return_value=("openai", "gpt-5-mini", None, None, "test"),
        ),
    )


def test_tool_new_writes_module_and_test(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        result = runner.invoke(app, ["new", "fetch a github pr diff"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "fetch_pr_diff.py").read_text() == _MODULE_SRC
    assert (tmp_path / "test_fetch_pr_diff.py").exists()
    assert "type: custom" in result.output
    assert "module: fetch_pr_diff" in result.output


def test_tool_new_refuses_overwrite_without_force(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        first = runner.invoke(app, ["new", "fetch a github pr diff"])
        second = runner.invoke(app, ["new", "fetch a github pr diff"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 1
    assert "already exists" in second.output.lower()
