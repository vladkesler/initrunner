"""``initrunner schema`` prints the agent-file JSON Schema."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from initrunner.agent.schema.json_schema import render_agent_schema
from initrunner.cli.main import app


def test_prints_the_schema_without_credentials(monkeypatch) -> None:
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    result = CliRunner().invoke(app, ["schema"])

    assert result.exit_code == 0
    assert result.output == render_agent_schema()
    assert result.output.endswith("}\n")
    assert json.loads(result.output)["title"] == "InitRunner agent"
