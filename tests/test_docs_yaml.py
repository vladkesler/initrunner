"""Validate every YAML example in README and docs/ against the real schema.

The 2026.8.4 release flattened public Agent/Team/Flow YAML (no ``apiVersion`` /
``kind`` / ``metadata`` / ``spec`` wrapper). Docs drifted because nothing checked
them. ``tests/test_examples.py`` guards ``examples/``; this guards the prose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from initrunner.agent.schema.document import DocumentClass, classify_mapping
from initrunner.agent.schema.normalize import normalize_mapping
from initrunner.agent.schema.v3 import AgentDocument

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files that intentionally show the removed envelope shape.
ENVELOPE_ALLOWLIST = {
    "docs/getting-started/envelope-migration.md",  # before/after migration example
    "docs/operations/deprecations.md",  # documents the removed spec.* paths
}

# Blocks that look like flat agents to the classifier but document another format.
# Keyed by ``(file, substring unique to that block)`` so they survive line moves.
NON_AGENT_BLOCKS = {
    ("docs/getting-started/setup.md", "tool_profile:"),  # ~/.initrunner/run.yaml
    ("docs/getting-started/setup.md", "base_url:"),  # run.yaml custom endpoint
    ("docs/getting-started/agent-spec-import.md", "agent-spec.yaml"),  # PydanticAI spec
}


def _is_non_agent_block(rel: str, text: str) -> bool:
    return any(rel == f and marker in text for f, marker in NON_AGENT_BLOCKS)


_FENCE = re.compile(r"^(\s*)```+(\w[\w+-]*)?\s*$")


def _yaml_blocks(path: Path) -> list[tuple[int, str]]:
    """Return ``(line_number, text)`` for each fenced yaml block in *path*."""
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        opening = _FENCE.match(lines[i])
        if not opening or (opening.group(2) or "").lower() not in ("yaml", "yml"):
            i += 1
            continue
        indent = opening.group(1)
        start = i + 1
        j = start
        while j < len(lines) and lines[j].strip() != "```":
            j += 1
        body = lines[start:j]
        if indent:
            body = [b[len(indent) :] if b.startswith(indent) else b for b in body]
        blocks.append((start + 1, "\n".join(body)))
        i = j + 1
    return blocks


def _doc_files() -> list[Path]:
    files = sorted(REPO_ROOT.glob("README*.md"))
    files.extend(sorted((REPO_ROOT / "docs").rglob("*.md")))
    return files


def _all_blocks() -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for path in _doc_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for line, text in _yaml_blocks(path):
            out.append((rel, line, text))
    return out


_BLOCKS = _all_blocks()
_IDS = [f"{rel}:{line}" for rel, line, _ in _BLOCKS]

_DOCUMENT_CLASSES = {
    DocumentClass.FLAT_AGENT,
    DocumentClass.ENVELOPE_AGENT,
    DocumentClass.ENVELOPE_TEAM,
    DocumentClass.ENVELOPE_FLOW,
}


def test_docs_contain_yaml_examples() -> None:
    """Guard against the extractor silently matching nothing."""
    assert len(_BLOCKS) > 100


@pytest.mark.parametrize(("rel", "line", "text"), _BLOCKS, ids=_IDS)
def test_yaml_block_parses(rel: str, line: int, text: str) -> None:
    """Every fenced yaml block must be parseable YAML."""
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as exc:
        pytest.fail(f"{rel}:{line} is not valid YAML: {exc}")


@pytest.mark.parametrize(("rel", "line", "text"), _BLOCKS, ids=_IDS)
def test_yaml_block_validates(rel: str, line: int, text: str) -> None:
    """Blocks that are complete agent documents must validate against the schema."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        pytest.skip("covered by test_yaml_block_parses")
    if not isinstance(data, dict):
        pytest.skip("not a mapping")
    if _is_non_agent_block(rel, text):
        pytest.skip("documents a non-InitRunner format")
    if classify_mapping(data).document_class not in _DOCUMENT_CLASSES:
        pytest.skip("not a complete agent document")
    try:
        normalize_mapping(data)
    except Exception as exc:
        pytest.fail(f"{rel}:{line} does not validate: {exc}")


@pytest.mark.parametrize(("rel", "line", "text"), _BLOCKS, ids=_IDS)
def test_no_leftover_envelope(rel: str, line: int, text: str) -> None:
    """Public agent YAML is flat: no ``spec:`` wrapper, no ``kind: Agent|Team|Flow``."""
    if rel in ENVELOPE_ALLOWLIST:
        return
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        pytest.skip("covered by test_yaml_block_parses")
    if not isinstance(data, dict):
        pytest.skip("not a mapping")

    document_class = classify_mapping(data).document_class
    assert document_class not in {
        DocumentClass.ENVELOPE_AGENT,
        DocumentClass.ENVELOPE_TEAM,
        DocumentClass.ENVELOPE_FLOW,
    }, f"{rel}:{line} uses the removed envelope; public YAML is flat"

    # A bare ``spec:`` whose children are all AgentDocument fields is an
    # unconverted envelope body, not some unrelated config block.
    spec = data.get("spec")
    if isinstance(spec, dict) and spec:
        unknown = set(spec) - set(AgentDocument.model_fields) - {"role"}
        assert unknown, (
            f"{rel}:{line} still wraps agent config in 'spec:'; "
            f"hoist {sorted(spec)} to the top level (spec.role becomes prompt)"
        )
