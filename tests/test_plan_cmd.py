"""Tests for the `initrunner plan` CLI command."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()

_ROLE = """\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: plan-cli-agent
spec:
  role: "You help."
  model:
    provider: openai
    name: gpt-5-mini
  tools:
    - type: custom
      module: clitool
  security:
    sandbox:
      backend: none
"""

_TOOL = 'async def cli_fn(x: int) -> str:\n    """Do it."""\n    return str(x)\n'


def _role(tmp_path):
    (tmp_path / "clitool.py").write_text(_TOOL)
    (tmp_path / "role.yaml").write_text(_ROLE)
    return tmp_path / "role.yaml"


def test_plan_renders_sections(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    result = runner.invoke(app, ["plan", str(_role(tmp_path)), "--no-sandbox-probe"])
    assert result.exit_code == 0, result.output
    for heading in ("Reachable tools", "initguard policy", "Guardrails", "Sandbox", "Caveats"):
        assert heading in result.output
    assert "cli_fn" in result.output


def test_plan_json_is_valid(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    result = runner.invoke(app, ["plan", str(_role(tmp_path)), "--json", "--no-sandbox-probe"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["role_name"] == "plan-cli-agent"
    assert any(t["name"] == "cli_fn" for t in payload["tools"])


def test_plan_no_introspect(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    result = runner.invoke(
        app, ["plan", str(_role(tmp_path)), "--no-introspect", "--no-sandbox-probe"]
    )
    assert result.exit_code == 0, result.output
    assert "custom" in result.output


def test_plan_rejects_non_agent_kind(tmp_path):
    (tmp_path / "team.yaml").write_text(
        "apiVersion: initrunner/v1\nkind: Team\n"
        "metadata:\n  name: t\n"
        "spec:\n  model: {provider: openai, name: gpt-5-mini}\n  personas: {}\n"
    )
    result = runner.invoke(app, ["plan", str(tmp_path / "team.yaml")])
    assert result.exit_code == 1
    assert "Agent roles" in result.output
