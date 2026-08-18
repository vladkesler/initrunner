"""Lossless envelope → flat round-trip over every tracked fixture."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from initrunner.agent.schema.adapt import adapt_mapping
from initrunner.agent.schema.document import DocumentClass, classify_mapping
from initrunner.agent.schema.normalize import normalize_mapping
from initrunner.agent.schema.render import render_document
from initrunner.services.migrate import (
    rewrite_envelope_file,
    runner_models_equivalent,
)

ROOT = Path(__file__).resolve().parents[1]

_ENVELOPE_CLASSES = {
    DocumentClass.ENVELOPE_AGENT,
    DocumentClass.ENVELOPE_TEAM,
    DocumentClass.ENVELOPE_FLOW,
}


def _envelope_fixtures() -> list[Path]:
    paths: list[Path] = []
    for base in (ROOT / "examples", ROOT / "tests"):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.yaml")):
            if "__pycache__" in path.parts:
                continue
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if classify_mapping(data).document_class in _ENVELOPE_CLASSES:
                paths.append(path)
    return paths


_FIXTURES = _envelope_fixtures()


@pytest.mark.parametrize(
    "path",
    _FIXTURES,
    ids=[str(p.relative_to(ROOT)) for p in _FIXTURES],
)
def test_envelope_round_trip_equivalent(path: Path) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    result = normalize_mapping(raw)
    text = render_document(result.document)
    rendered = yaml.safe_load(text)
    assert isinstance(rendered, dict)
    assert "apiVersion" not in rendered
    assert rendered.get("kind") not in {"Agent", "Team", "Flow"}
    _, old_model, _ = adapt_mapping(raw, base_dir=path.parent)
    _, new_model, _ = adapt_mapping(rendered, base_dir=path.parent)
    assert runner_models_equivalent(old_model, new_model), path


def test_rewrite_writes_backup_and_flat(tmp_path: Path) -> None:
    src = tmp_path / "role.yaml"
    src.write_text(
        "apiVersion: initrunner/v1\n"
        "kind: Agent\n"
        "metadata:\n"
        "  name: hello-world\n"
        "spec:\n"
        "  role: You are a greeter.\n"
        "  model:\n"
        "    provider: openai\n"
        "    name: gpt-5-mini\n"
    )
    result = rewrite_envelope_file(src)
    assert result.action == "rewritten"
    assert result.backup is not None and result.backup.exists()
    data = yaml.safe_load(src.read_text())
    assert data["name"] == "hello-world"
    assert data["prompt"] == "You are a greeter."
    assert "apiVersion" not in data


def test_rewrite_preserves_private_file_permissions(tmp_path: Path) -> None:
    src = tmp_path / "role.yaml"
    src.write_text(
        "apiVersion: initrunner/v1\n"
        "kind: Agent\n"
        "metadata:\n"
        "  name: private-agent\n"
        "spec:\n"
        "  role: keep this private\n"
    )
    src.chmod(0o600)

    result = rewrite_envelope_file(src)

    assert result.action == "rewritten"
    assert result.backup is not None
    assert src.stat().st_mode & 0o777 == 0o600
    assert result.backup.stat().st_mode & 0o777 == 0o600


def test_rewrite_refuses_existing_backup(tmp_path: Path) -> None:
    src = tmp_path / "role.yaml"
    src.write_text(
        "apiVersion: initrunner/v1\n"
        "kind: Agent\n"
        "metadata:\n"
        "  name: hello-world\n"
        "spec:\n"
        "  role: hi\n"
    )
    src.with_suffix(".yaml.bak").write_text("old")
    result = rewrite_envelope_file(src)
    assert result.action == "failed"
    assert "backup exists" in result.message


def test_envelope_still_loads_via_dual_read(tmp_path: Path) -> None:
    from initrunner.agent.loader import load_role

    path = tmp_path / "role.yaml"
    path.write_text(
        "apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: dual-read\nspec:\n  role: hi\n"
    )
    role = load_role(path)
    assert role.metadata.name == "dual-read"
    assert role.spec.role == "hi"


def test_rewrite_skips_flat(tmp_path: Path) -> None:
    src = tmp_path / "agent.yaml"
    src.write_text("name: hello-world\nprompt: hi\n")
    result = rewrite_envelope_file(src)
    assert result.action == "skipped"
