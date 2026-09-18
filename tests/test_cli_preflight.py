"""Tests for the CLI YAML pre-flight validation pipeline."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from initrunner.cli._helpers import preflight_validate_or_exit
from initrunner.cli._validation_panel import render_validation_panel
from initrunner.cli.main import app
from initrunner.services._yaml_validation import (
    ValidationIssue,
    parse_yaml_text,
    unwrap_pydantic_error,
)
from initrunner.services.yaml_validation import validate_yaml_file

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixture YAML
# ---------------------------------------------------------------------------


_VALID_ROLE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: test-agent
      description: A test agent
    spec:
      role: You are a helpful assistant.
      model:
        provider: openai
        name: gpt-5-mini
""")


_BAD_INDENT_ROLE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: bad-indent
    spec:
      model:
        provider: openai
        name: gpt-5-mini
       role: oops
""")


_BAD_FIELD_TYPE_ROLE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: bad-type
    spec:
      role: You are helpful.
      model:
        provider: 123
        name: gpt-5-mini
""")


_MISSING_REQUIRED_ROLE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata: {}
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
""")


_SHORT_PROMPT_ROLE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: short-prompt
    spec:
      role: Hi
      model:
        provider: openai
        name: gpt-5-mini
""")


_VALID_TEAM_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Team
    metadata:
      name: test-team
    spec:
      model:
        provider: openai
        name: gpt-5-mini
      personas:
        alpha: "first persona"
        bravo: "second persona"
""")


_BAD_TEAM_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Team
    metadata:
      name: bad-team
    spec:
      model:
        provider: 999
        name: gpt-5-mini
      personas:
        alpha: "p1"
        bravo: "p2"
""")


_VALID_FLOW_YAML_TEMPLATE = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Flow
    metadata:
      name: test-flow
    spec:
      agents:
        worker:
          role: {role_path}
""")


# ---------------------------------------------------------------------------
# parse_yaml_text: 1-based line / column tracking
# ---------------------------------------------------------------------------


class TestParseYamlText:
    def test_indent_error_includes_1_based_line(self):
        _, issues = parse_yaml_text(_BAD_INDENT_ROLE_YAML)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == "error"
        assert issue.field == "yaml"
        # The bad-indent line is line 9 in _BAD_INDENT_ROLE_YAML (1-based).
        assert issue.line is not None
        assert issue.line >= 1
        assert issue.column is not None
        assert issue.column >= 1

    def test_valid_yaml_returns_no_issues(self):
        raw, issues = parse_yaml_text(_VALID_ROLE_YAML)
        assert raw is not None
        assert issues == []


# ---------------------------------------------------------------------------
# unwrap_pydantic_error: preserves field info through ValueError wrapping
# ---------------------------------------------------------------------------


class TestUnwrapPydanticError:
    def test_unwraps_value_error_cause(self):
        from pydantic import BaseModel, ValidationError

        class Model(BaseModel):
            x: str

        try:
            Model.model_validate({"x": 123})
        except ValidationError as ve:
            wrapped = ValueError(str(ve))
            wrapped.__cause__ = ve  # mimic deprecations.py pattern
            issues = unwrap_pydantic_error(wrapped)

        assert len(issues) == 1
        assert issues[0].field == "x"
        assert issues[0].suggestion is not None

    def test_passes_through_raw_validation_error(self):
        from pydantic import BaseModel, ValidationError

        class Model(BaseModel):
            x: str

        try:
            Model.model_validate({"x": 123})
        except ValidationError as ve:
            issues = unwrap_pydantic_error(ve)

        assert len(issues) == 1
        assert issues[0].field == "x"

    def test_unknown_exception_falls_back_to_schema(self):
        issues = unwrap_pydantic_error(RuntimeError("boom"))
        assert len(issues) == 1
        assert issues[0].field == "schema"
        assert "boom" in issues[0].message


# ---------------------------------------------------------------------------
# validate_yaml_file: per-kind dispatch + recursive flow
# ---------------------------------------------------------------------------


class TestValidateYamlFile:
    def test_valid_role_returns_no_errors(self, tmp_path):
        f = tmp_path / "role.yaml"
        f.write_text(_VALID_ROLE_YAML)
        defn, kind, issues = validate_yaml_file(f)
        assert defn is not None
        assert kind == "Agent"
        assert not any(i.severity == "error" for i in issues)

    def test_indent_error_surfaces_with_line_number(self, tmp_path):
        f = tmp_path / "role.yaml"
        f.write_text(_BAD_INDENT_ROLE_YAML)
        defn, _kind, issues = validate_yaml_file(f)
        assert defn is None
        errors = [i for i in issues if i.severity == "error"]
        assert any(i.line is not None for i in errors)

    def test_bad_field_type_yields_per_field_issue(self, tmp_path):
        """The whole point of unwrap_pydantic_error: must NOT collapse to field='schema'."""
        f = tmp_path / "role.yaml"
        f.write_text(_BAD_FIELD_TYPE_ROLE_YAML)
        defn, _kind, issues = validate_yaml_file(f)
        assert defn is None
        errors = [i for i in issues if i.severity == "error"]
        # The provider field is at spec.model.provider
        assert any("provider" in i.field for i in errors), [i.field for i in errors]
        # And specifically not the lossy 'schema' bucket
        assert not all(i.field == "schema" for i in errors)

    def test_missing_required_field_yields_per_field_issue(self, tmp_path):
        f = tmp_path / "role.yaml"
        f.write_text(_MISSING_REQUIRED_ROLE_YAML)
        defn, _kind, issues = validate_yaml_file(f)
        assert defn is None
        errors = [i for i in issues if i.severity == "error"]
        assert any("name" in i.field for i in errors), [i.field for i in errors]
        # Missing-field issues should carry a fix suggestion
        assert any(i.suggestion is not None for i in errors)

    def test_short_system_prompt_yields_warning_only(self, tmp_path):
        f = tmp_path / "role.yaml"
        f.write_text(_SHORT_PROMPT_ROLE_YAML)
        defn, _kind, issues = validate_yaml_file(f)
        assert defn is not None
        assert not any(i.severity == "error" for i in issues)
        warnings = [i for i in issues if i.severity == "warning"]
        assert len(warnings) >= 1

    def test_team_dispatch(self, tmp_path):
        f = tmp_path / "team.yaml"
        f.write_text(_VALID_TEAM_YAML)
        defn, kind, issues = validate_yaml_file(f)
        assert defn is not None
        assert kind == "Team"
        assert not any(i.severity == "error" for i in issues)

    def test_team_bad_field_type(self, tmp_path):
        f = tmp_path / "team.yaml"
        f.write_text(_BAD_TEAM_YAML)
        defn, _kind, issues = validate_yaml_file(f)
        assert defn is None
        errors = [i for i in issues if i.severity == "error"]
        assert any("provider" in i.field for i in errors), [i.field for i in errors]

    def test_flow_recurses_into_role_files_and_prefixes_field(self, tmp_path):
        # Write a broken role and a flow that references it.
        broken_role = tmp_path / "worker.yaml"
        broken_role.write_text(_BAD_FIELD_TYPE_ROLE_YAML)
        flow_path = tmp_path / "flow.yaml"
        flow_path.write_text(_VALID_FLOW_YAML_TEMPLATE.format(role_path="worker.yaml"))

        _defn, kind, issues = validate_yaml_file(flow_path)
        assert kind == "Flow"
        errors = [i for i in issues if i.severity == "error"]
        assert any(i.field.startswith("agents.worker.") for i in errors), [i.field for i in errors]

    def test_flow_missing_role_file_reports_path(self, tmp_path):
        flow_path = tmp_path / "flow.yaml"
        flow_path.write_text(_VALID_FLOW_YAML_TEMPLATE.format(role_path="missing.yaml"))
        _defn, _kind, issues = validate_yaml_file(flow_path)
        errors = [i for i in issues if i.severity == "error"]
        assert any("missing.yaml" in i.message for i in errors)
        assert any(i.field == "agents.worker.use" for i in errors)

    def test_unreadable_file(self, tmp_path):
        defn, _kind, issues = validate_yaml_file(tmp_path / "does-not-exist.yaml")
        assert defn is None
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 1
        assert errors[0].field == "file"


_FLAT_TWO_TYPOS_YAML = textwrap.dedent("""\
    name: typos
    prompt: You are a careful assistant.
    model: openai:gpt-5-mini
    memory:
      retenion_days: 30
    tools:
      - think
      - shell:
          allowd_commands: [ls]
""")


_FLAT_VALID_ROLE_YAML = textwrap.dedent("""\
    name: fine
    prompt: You are a careful assistant.
    model: openai:gpt-5-mini
""")


_FLAT_MEMBER_TYPO_YAML = textwrap.dedent("""\
    name: member
    prompt: You are a careful assistant.
    model: openai:gpt-5-mini
    memory:
      retenion_days: 30
""")


class TestFlatDocumentFieldPaths:
    """Flat files report one issue per field, not one ``document`` blob."""

    def test_each_typo_is_its_own_issue_with_a_fix(self, tmp_path):
        f = tmp_path / "agent.yaml"
        f.write_text(_FLAT_TWO_TYPOS_YAML)
        defn, kind, issues = validate_yaml_file(f)
        assert defn is None
        assert kind == "Agent"
        errors = {i.field: i for i in issues if i.severity == "error"}
        assert set(errors) == {"memory.retenion_days", "tools.1.allowd_commands"}
        assert all(i.suggestion for i in errors.values())

    def test_flow_member_issues_keep_their_prefix(self, tmp_path):
        (tmp_path / "worker.yaml").write_text(_FLAT_MEMBER_TYPO_YAML)
        flow = tmp_path / "flow.yaml"
        flow.write_text(
            textwrap.dedent("""\
                name: pipe
                model: openai:gpt-5-mini
                agents:
                  worker:
                    use: worker.yaml
                    then: {to: sink}
                  sink:
                    prompt: Collect the results.
            """)
        )
        _defn, kind, issues = validate_yaml_file(flow)
        assert kind == "Flow"
        fields = [i.field for i in issues if i.severity == "error"]
        assert "agents.worker.memory.retenion_days" in fields

    def test_group_member_issues_keep_their_prefix(self, tmp_path):
        (tmp_path / "a.yaml").write_text(_FLAT_MEMBER_TYPO_YAML)
        (tmp_path / "b.yaml").write_text(_FLAT_VALID_ROLE_YAML)
        group = tmp_path / "group.yaml"
        group.write_text("name: desk\nagents:\n  a:\n    use: a.yaml\n  b:\n    use: b.yaml\n")
        _defn, kind, issues = validate_yaml_file(group)
        assert kind == "Group"
        fields = [i.field for i in issues if i.severity == "error"]
        assert fields == ["agents.a.memory.retenion_days"]

    def test_referenced_role_errors_carry_the_member_prefix(self, tmp_path):
        """A ``use:`` target with overrides is loaded while composing; check it first."""
        (tmp_path / "bad.yaml").write_text(_FLAT_MEMBER_TYPO_YAML)
        team = tmp_path / "team.yaml"
        team.write_text(
            textwrap.dedent("""\
                name: crew
                model: openai:gpt-5-mini
                run: sequential
                agents:
                  a:
                    use: bad.yaml
                    prompt: Override the prompt.
                  b: Review the work.
            """)
        )
        defn, _kind, issues = validate_yaml_file(team)
        assert defn is None
        fields = [i.field for i in issues if i.severity == "error"]
        assert fields == ["agents.a.memory.retenion_days"]

    def test_flow_member_with_overrides_keeps_its_prefix(self, tmp_path):
        (tmp_path / "worker.yaml").write_text(_FLAT_MEMBER_TYPO_YAML)
        flow = tmp_path / "flow.yaml"
        flow.write_text(
            textwrap.dedent("""\
                name: pipe
                model: openai:gpt-5-mini
                agents:
                  worker:
                    use: worker.yaml
                    prompt: Override the prompt.
                    then: {to: sink}
                  sink:
                    prompt: Collect the results.
            """)
        )
        _defn, _kind, issues = validate_yaml_file(flow)
        fields = [i.field for i in issues if i.severity == "error"]
        assert fields == ["agents.worker.memory.retenion_days"]

    def test_document_rule_is_reported_as_document(self, tmp_path):
        """Model-level rules have no field path; they must not render as a blank row."""
        f = tmp_path / "agent.yaml"
        f.write_text("name: noprompt\nmodel: openai:gpt-5-mini\n")
        defn, _kind, issues = validate_yaml_file(f)
        assert defn is None
        [error] = [i for i in issues if i.severity == "error"]
        assert error.field == "document"
        assert "require 'prompt'" in error.message

    def test_a_file_that_references_itself_is_an_error_not_a_crash(self, tmp_path):
        group = tmp_path / "group.yaml"
        group.write_text(
            "name: desk\nagents:\n  a:\n    use: group.yaml\n  b:\n    use: group.yaml\n"
        )
        defn, _kind, issues = validate_yaml_file(group)
        assert defn is None
        fields = {i.field for i in issues if i.severity == "error"}
        assert fields == {"agents.a.use", "agents.b.use"}

    def test_a_member_that_is_not_an_agent_is_an_error(self, tmp_path):
        (tmp_path / "b.yaml").write_text(_FLAT_VALID_ROLE_YAML)
        (tmp_path / "inner.yaml").write_text(
            "name: inner\nagents:\n  x:\n    use: b.yaml\n  y:\n    use: b.yaml\n"
        )
        group = tmp_path / "group.yaml"
        group.write_text("name: desk\nagents:\n  a:\n    use: inner.yaml\n  b:\n    use: b.yaml\n")
        _defn, _kind, issues = validate_yaml_file(group)
        errors = [i for i in issues if i.severity == "error"]
        assert [i.field for i in errors] == ["agents.a.use"]
        assert "inner.yaml is a Group" in errors[0].message


# ---------------------------------------------------------------------------
# preflight_validate_or_exit: run-path policy
# ---------------------------------------------------------------------------


class TestPreflightOrExit:
    def test_warning_only_does_not_exit_or_print(self, tmp_path, capsys):
        f = tmp_path / "role.yaml"
        f.write_text(_SHORT_PROMPT_ROLE_YAML)
        # Should NOT raise.
        preflight_validate_or_exit(f)
        captured = capsys.readouterr()
        # And should NOT print anything (warning suppression on the run path).
        assert captured.out == ""
        assert captured.err == ""

    def test_error_prints_panel_and_exits(self, tmp_path, capsys):
        f = tmp_path / "role.yaml"
        f.write_text(_BAD_FIELD_TYPE_ROLE_YAML)
        with pytest.raises(typer.Exit):
            preflight_validate_or_exit(f)
        captured = capsys.readouterr()
        assert "ERROR" in captured.out
        assert "provider" in captured.out


# ---------------------------------------------------------------------------
# render_validation_panel: markup escaping + layout
# ---------------------------------------------------------------------------


class TestRenderValidationPanel:
    def test_escapes_pydantic_brackets_in_messages(self):
        from io import StringIO

        from rich.console import Console

        issue = ValidationIssue(
            field="spec.model.provider",
            message="Input should be a valid string [type=string_type, input_value=123]",
            severity="error",
            suggestion="expected a string",
        )
        panel = render_validation_panel(Path("/tmp/role.yaml"), "Agent", [issue])

        buf = StringIO()
        console = Console(file=buf, force_terminal=False, width=100)
        console.print(panel)
        out = buf.getvalue()

        # Rich must NOT have parsed [type=string_type, ...] as markup.
        # The literal bracketed text should be present in the rendered output.
        assert "[type=string_type" in out
        assert "Input should be a valid string" in out

    def test_summary_line_pluralization(self):
        from io import StringIO

        from rich.console import Console

        issues = [
            ValidationIssue(field="a", message="x", severity="error"),
            ValidationIssue(field="b", message="y", severity="error"),
            ValidationIssue(field="c", message="z", severity="warning"),
        ]
        panel = render_validation_panel(Path("/tmp/role.yaml"), "Agent", issues)
        buf = StringIO()
        Console(file=buf, force_terminal=False, width=100).print(panel)
        out = buf.getvalue()
        assert "2 errors" in out
        assert "1 warning" in out

    def test_line_column_displayed_when_present(self):
        from io import StringIO

        from rich.console import Console

        issue = ValidationIssue(
            field="yaml",
            message="bad",
            severity="error",
            line=14,
            column=3,
        )
        panel = render_validation_panel(Path("/tmp/role.yaml"), "Agent", [issue])
        buf = StringIO()
        Console(file=buf, force_terminal=False, width=100).print(panel)
        out = buf.getvalue()
        assert "line 14" in out
        assert "col 3" in out


# ---------------------------------------------------------------------------
# CLI integration: errors block run before any agent build
# ---------------------------------------------------------------------------


class TestCliIntegration:
    def test_run_with_broken_role_does_not_build_agent(self, tmp_path):
        f = tmp_path / "broken.yaml"
        f.write_text(_BAD_FIELD_TYPE_ROLE_YAML)

        with patch("initrunner.services.execution.build_agent_sync") as mock_build:
            result = runner.invoke(app, ["run", str(f), "-p", "hello"])

        assert result.exit_code != 0
        assert mock_build.call_count == 0
        assert "ERROR" in result.output
        assert "provider" in result.output

    def test_validate_command_uses_same_panel(self, tmp_path):
        f = tmp_path / "broken.yaml"
        f.write_text(_BAD_FIELD_TYPE_ROLE_YAML)
        result = runner.invoke(app, ["validate", str(f)])
        assert result.exit_code != 0
        assert "ERROR" in result.output
        assert "provider" in result.output

    def test_validate_command_clean_role_succeeds(self, tmp_path):
        f = tmp_path / "role.yaml"
        f.write_text(_VALID_ROLE_YAML)
        result = runner.invoke(app, ["validate", str(f)])
        assert result.exit_code == 0
        assert "Valid" in result.output

    def test_validate_command_team_without_a_model(self, tmp_path):
        """The model is auto-detected at run time; the summary must not assume one."""
        f = tmp_path / "team.yaml"
        f.write_text(
            "name: crew\nrun: parallel\nagents:\n  architect: Review the design.\n"
            "  tester: Review the tests.\n"
        )
        result = runner.invoke(app, ["validate", str(f)])
        assert result.exit_code == 0, result.output
        assert "auto-detect at runtime" in result.output

    def test_validate_command_warning_only_renders_panel_and_succeeds(self, tmp_path):
        f = tmp_path / "role.yaml"
        f.write_text(_SHORT_PROMPT_ROLE_YAML)
        result = runner.invoke(app, ["validate", str(f)])
        # Warning panel rendered, but command succeeds and shows the table.
        assert result.exit_code == 0
        assert "WARN" in result.output
        assert "Valid" in result.output
