"""Tests for the {{var}} templating renderer."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import ClassVar

import pytest

from initrunner.agent.loader import RoleLoadError, build_agent, load_role
from initrunner.agent.templating import (
    TemplatingError,
    extract_vars,
    has_templates,
    render,
    validate_schema_and_template,
)


class TestExtraction:
    def test_has_templates(self):
        assert has_templates("hi {{name}}")
        assert has_templates("a {{ x }} b")
        assert not has_templates("no templates here")
        assert not has_templates("")

    def test_extract_vars(self):
        assert extract_vars("hi {{name}}, {{count}} times") == {"name", "count"}
        assert extract_vars("plain text") == set()

    def test_whitespace_tolerated(self):
        assert extract_vars("{{  name  }}") == {"name"}


class TestSchemaValidation:
    SCHEMA_OK: ClassVar[dict] = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
        "required": ["name"],
    }

    def test_flat_scalar_schema_ok(self):
        validate_schema_and_template("hi {{name}} {{count}}", self.SCHEMA_OK)

    def test_undeclared_var_rejected(self):
        with pytest.raises(TemplatingError, match="undeclared"):
            validate_schema_and_template("hi {{stranger}}", self.SCHEMA_OK)

    def test_non_object_schema_rejected(self):
        with pytest.raises(TemplatingError, match="object"):
            validate_schema_and_template("hi", {"type": "string"})

    def test_nested_object_rejected(self):
        schema = {
            "type": "object",
            "properties": {"user": {"type": "object", "properties": {"name": {"type": "string"}}}},
        }
        with pytest.raises(TemplatingError, match="must be one of"):
            validate_schema_and_template("hi", schema)

    def test_array_rejected(self):
        schema = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        }
        with pytest.raises(TemplatingError, match="must be one of"):
            validate_schema_and_template("hi", schema)

    def test_ref_rejected(self):
        schema = {"type": "object", "$ref": "#/defs/foo", "properties": {}}
        with pytest.raises(TemplatingError, match="\\$ref"):
            validate_schema_and_template("hi", schema)

    def test_oneOf_rejected(self):
        schema = {"type": "object", "oneOf": [], "properties": {}}
        with pytest.raises(TemplatingError, match="oneOf"):
            validate_schema_and_template("hi", schema)


class TestRender:
    SCHEMA: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer"},
            "score": {"type": "number"},
            "active": {"type": "boolean"},
        },
        "required": ["name"],
    }

    def test_string_substitution(self):
        assert render("hi {{name}}", self.SCHEMA, {"name": "alice"}) == "hi alice"

    def test_integer_coercion(self):
        assert render("{{count}}", self.SCHEMA, {"name": "x", "count": 42}) == "42"

    def test_boolean_coercion(self):
        assert render("{{active}}", self.SCHEMA, {"name": "x", "active": True}) == "true"
        assert render("{{active}}", self.SCHEMA, {"name": "x", "active": False}) == "false"

    def test_missing_required_raises(self):
        with pytest.raises(TemplatingError, match="required"):
            render("hi {{name}}", self.SCHEMA, {})

    def test_extra_values_ignored(self):
        assert render("hi {{name}}", self.SCHEMA, {"name": "bob", "unused": "x"}) == "hi bob"

    def test_whitespace_placeholder(self):
        assert render("hi {{ name }}", self.SCHEMA, {"name": "alice"}) == "hi alice"


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "role.yaml"
    p.write_text(body)
    return p


class TestLoaderIntegration:
    def test_templates_without_deps_schema_rejected(self, tmp_path: Path):
        body = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: t-agent
            spec:
              role: "hi {{name}}"
              model:
                provider: openai
                name: gpt-4o
        """)
        with pytest.raises(RoleLoadError, match="deps_schema"):
            load_role(_write(tmp_path, body))

    def test_undeclared_var_rejected_at_load(self, tmp_path: Path):
        body = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: t-agent
            spec:
              role: "hi {{stranger}}"
              model:
                provider: openai
                name: gpt-4o
              deps_schema:
                type: object
                properties:
                  name: {type: string}
        """)
        with pytest.raises(RoleLoadError, match="undeclared"):
            load_role(_write(tmp_path, body))

    def test_nested_deps_schema_rejected(self, tmp_path: Path):
        body = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: t-agent
            spec:
              role: "hi {{name}}"
              model:
                provider: openai
                name: gpt-4o
              deps_schema:
                type: object
                properties:
                  name:
                    type: object
                    properties:
                      inner: {type: string}
        """)
        with pytest.raises(RoleLoadError, match="must be one of"):
            load_role(_write(tmp_path, body))

    def test_valid_template_loads(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        body = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: t-agent
            spec:
              role: "hi {{name}}"
              model:
                provider: openai
                name: gpt-4o
              deps_schema:
                type: object
                properties:
                  name: {type: string}
                required: [name]
        """)
        role = load_role(_write(tmp_path, body))
        agent = build_agent(role)

        # The raw role prompt should NOT be baked into the static instructions;
        # it is rendered at run time via a @system_prompt hook.
        assert "{{name}}" not in (agent._instructions or "")
        assert "hi " not in (agent._instructions or "")

        # Simulate runtime: set template values and invoke registered hooks.
        agent._template_values = {"name": "alice"}  # type: ignore[attr-defined]
        hooks = list(agent._system_prompt_functions) + list(
            agent._system_prompt_dynamic_functions.values()
        )
        rendered: list[str] = []
        for h in hooks:
            func = h.function  # type: ignore[union-attr]
            try:
                result = func()  # type: ignore[call-arg]
            except TypeError:
                continue  # skip ctx-requiring dynamic hooks
            if isinstance(result, str):
                rendered.append(result)
        assert any("hi alice" in r for r in rendered), rendered
