"""Tests for the memory import CLI command."""

from __future__ import annotations

import json
import textwrap

from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()

_ROLE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: test-agent
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
      memory:
        enabled: true
""")

_ROLE_NO_MEMORY_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: test-agent
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
""")


class TestMemoryImportCli:
    def test_memory_import_invalid_json(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(_ROLE_YAML)
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("not valid json {{{")

        result = runner.invoke(app, ["memory", "import", str(role_file), str(bad_json)])
        assert result.exit_code == 1
        assert "Invalid JSON" in result.output

    def test_memory_import_non_array_json(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(_ROLE_YAML)
        obj_json = tmp_path / "obj.json"
        obj_json.write_text(json.dumps({"key": "value"}))

        result = runner.invoke(app, ["memory", "import", str(role_file), str(obj_json)])
        assert result.exit_code == 1
        assert "Expected a JSON array" in result.output

    def test_memory_import_missing_memory_config(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(_ROLE_NO_MEMORY_YAML)
        data_json = tmp_path / "data.json"
        data_json.write_text(json.dumps([{"content": "test"}]))

        result = runner.invoke(app, ["memory", "import", str(role_file), str(data_json)])
        assert result.exit_code == 1
        assert "No memory config" in result.output

    def test_memory_import_file_not_found(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(_ROLE_YAML)
        missing = tmp_path / "missing.json"

        result = runner.invoke(app, ["memory", "import", str(role_file), str(missing)])
        assert result.exit_code == 1
        assert "File not found" in result.output
