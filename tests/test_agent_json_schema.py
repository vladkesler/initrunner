"""The published editor schema (``schemas/agent.v3.json``).

The committed file must be exactly what the models generate, and it must
agree with the loader: every agent file InitRunner ships validates against
it, and the typos the runtime rejects are rejected here too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml
from jsonschema.protocols import Validator

from initrunner import __version__
from initrunner.agent.schema.document import DocumentClass, classify_mapping
from initrunner.agent.schema.json_schema import (
    SCHEMA_URL,
    build_agent_schema,
    render_agent_schema,
)
from initrunner.services.starters import STARTERS_DIR

_REPO = Path(__file__).resolve().parent.parent
_ARTIFACT = _REPO / "schemas" / "agent.v3.json"


@pytest.fixture(scope="module")
def validator() -> Validator:
    return jsonschema.Draft202012Validator(build_agent_schema())


def _error_paths(validator: Validator, body: dict[str, Any]) -> set[str]:
    """Where validation failed, including inside optional (``anyOf``) sections."""
    doc = {"name": "probe", "prompt": "You are a probe.", **body}
    paths: set[str] = set()
    pending = list(validator.iter_errors(doc))
    while pending:
        error = pending.pop()
        paths.add("/".join(map(str, error.absolute_path)))
        pending.extend(error.context or [])
    return paths


def test_committed_schema_is_current() -> None:
    """Regenerate with: initrunner schema > schemas/agent.v3.json"""
    assert _ARTIFACT.read_text(encoding="utf-8") == render_agent_schema()


def test_schema_does_not_change_between_releases() -> None:
    assert __version__ not in render_agent_schema()


def test_schema_is_valid_draft_2020_12() -> None:
    schema = build_agent_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$id"] == SCHEMA_URL


def _shipped_flat_agents() -> list[Path]:
    paths = sorted((_REPO / "examples").rglob("*.yaml")) + sorted(STARTERS_DIR.rglob("*.yaml"))
    return [
        p
        for p in paths
        if classify_mapping(yaml.safe_load(p.read_text(encoding="utf-8"))).document_class
        is DocumentClass.FLAT_AGENT
    ]


@pytest.mark.parametrize("path", _shipped_flat_agents(), ids=lambda p: p.name)
def test_every_shipped_agent_file_validates(validator, path: Path) -> None:
    """Anything the loader accepts, the editor must accept."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    errors = [f"{list(e.absolute_path)}: {e.message}" for e in validator.iter_errors(doc)]
    assert errors == []


@pytest.mark.parametrize(
    "body",
    [
        {"model": "openai:gpt-5-mini"},
        {"model": "gpt-5-mini"},
        {"model": {"provider": "anthropic", "name": "claude", "prompt_cache": True}},
        {"tools": ["think", "search"]},
        {"tools": [{"shell": {"allowed_commands": ["ls"]}}, {"shell": None}]},
        {"tools": [{"type": "filesystem", "root_path": "."}]},
        {"tools": ["my_plugin", {"my_plugin": {"x": 1}}, {"type": "my_plugin", "y": 2}]},
        {"tools": [{"type": "plugin", "config": {"anything": True}}]},
        {"prompt": None, "agents": {"a": "Research the topic.", "b": {"prompt": "Write it up."}}},
        {"output": {"type": "json_schema", "schema": {"type": "object", "x-anything": 1}}},
    ],
    ids=[
        "model-string",
        "model-alias",
        "prompt-cache-bool",
        "tool-names",
        "tool-single-key",
        "tool-typed",
        "plugin-forms",
        "plugin-builtin",
        "inline-child-string",
        "output-schema-open",
    ],
)
def test_shorthand_validates(validator, body: dict[str, Any]) -> None:
    assert _error_paths(validator, body) == set()


@pytest.mark.parametrize(
    ("body", "path"),
    [
        ({"promt": "typo"}, ""),
        ({"memory": {"retenion_days": 30}}, "memory"),
        ({"ingest": {"sources": ["./docs"], "chunking": {"sise": 3}}}, "ingest/chunking"),
        ({"tools": [{"type": "shell", "allowd_commands": ["ls"]}]}, "tools/0"),
        ({"tools": ["think", {"shell": {"allowd_commands": ["ls"]}}]}, "tools/1"),
        # The plugin fallback must not swallow a misconfigured built-in tool.
        ({"tools": [{"type": "shell", "config": {}}]}, "tools/0"),
        ({"model": {"name": "gpt-5-mini", "temprature": 0.2}}, "model"),
    ],
    ids=[
        "top-level",
        "memory",
        "nested",
        "tool-typed",
        "tool-single-key",
        "builtin-as-plugin",
        "model",
    ],
)
def test_typos_fail(validator, body: dict[str, Any], path: str) -> None:
    assert path in _error_paths(validator, body)
