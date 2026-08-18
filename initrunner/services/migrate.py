"""Rewrite envelope Agent/Team/Flow YAML into flat documents."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from initrunner.agent.schema.document import DocumentClass, classify_mapping
from initrunner.agent.schema.normalize import NormalizeError, normalize_mapping
from initrunner.agent.schema.render import render_document

_ENVELOPE_CLASSES = {
    DocumentClass.ENVELOPE_AGENT,
    DocumentClass.ENVELOPE_TEAM,
    DocumentClass.ENVELOPE_FLOW,
}

_INERT_FLOW_AGENT_KEYS = ("restart", "health_check", "environment", "trigger")

RewriteAction = Literal["rewritten", "skipped", "failed"]

ENVELOPE_WARNING = "This file uses the removed envelope. Run: initrunner doctor --fix {path}"


def is_envelope_mapping(data: object) -> bool:
    """True when *data* is a public Agent/Team/Flow envelope."""
    if not isinstance(data, dict):
        return False
    return classify_mapping(data).document_class in _ENVELOPE_CLASSES


def envelope_warning_for(path: Path) -> str | None:
    """Return a one-line warning if *path* is still an envelope file."""
    from initrunner._yaml import load_raw_yaml

    try:
        raw = load_raw_yaml(path, ValueError)
    except Exception:
        return None
    if is_envelope_mapping(raw):
        return ENVELOPE_WARNING.format(path=path)
    return None


@dataclass(frozen=True)
class RewriteResult:
    path: Path
    action: RewriteAction
    message: str
    backup: Path | None = None


class RewriteError(ValueError):
    """Raised when a single file cannot be rewritten."""


def rewrite_envelopes(
    path: Path,
    *,
    backup: bool = True,
    force: bool = False,
) -> list[RewriteResult]:
    """Rewrite envelope YAML at *path* (file or directory)."""
    if path.is_dir():
        results: list[RewriteResult] = []
        for candidate in sorted(path.rglob("*")):
            if candidate.suffix not in {".yaml", ".yml"} or not candidate.is_file():
                continue
            results.append(rewrite_envelope_file(candidate, backup=backup, force=force))
        return results
    return [rewrite_envelope_file(path, backup=backup, force=force)]


def rewrite_envelope_file(
    path: Path,
    *,
    backup: bool = True,
    force: bool = False,
) -> RewriteResult:
    """Rewrite one file. Already-flat and non-agent documents are skipped."""
    from initrunner._yaml import load_raw_yaml

    try:
        raw = load_raw_yaml(path, ValueError)
    except Exception as exc:
        return RewriteResult(path, "failed", f"cannot read: {exc}")

    if not isinstance(raw, dict):
        return RewriteResult(path, "skipped", "not a YAML mapping")

    classification = classify_mapping(raw)
    if classification.document_class in {
        DocumentClass.SERVICE,
        DocumentClass.TEST_SUITE,
    }:
        return RewriteResult(path, "skipped", classification.reason)
    if classification.document_class is DocumentClass.FLAT_AGENT:
        return RewriteResult(path, "skipped", "already flat")
    if classification.document_class not in _ENVELOPE_CLASSES:
        return RewriteResult(path, "skipped", classification.reason)

    try:
        text = render_envelope_mapping(raw)
    except (RewriteError, NormalizeError, ValueError) as exc:
        return RewriteResult(path, "failed", str(exc))

    bak: Path | None = None
    if backup:
        bak = path.with_suffix(path.suffix + ".bak")
        if bak.exists() and not force:
            return RewriteResult(path, "failed", f"backup exists: {bak} (pass --force)")
        shutil.copy2(path, bak)

    _atomic_write(path, text)
    return RewriteResult(path, "rewritten", "rewrote envelope to flat YAML", backup=bak)


def render_envelope_mapping(raw: dict[str, Any]) -> str:
    """Normalize an envelope mapping, render flat YAML, and check equivalence."""
    from initrunner.agent.schema.adapt import adapt_mapping

    result = normalize_mapping(raw)
    text = render_document(result.document)
    import yaml

    rendered = yaml.safe_load(text)
    if not isinstance(rendered, dict):
        raise RewriteError("renderer produced non-mapping YAML")

    _, old_model, _ = adapt_mapping(raw)
    _, new_model, _ = adapt_mapping(rendered)
    if not runner_models_equivalent(old_model, new_model):
        raise RewriteError("rewritten document is not equivalent to the envelope")
    return text if text.endswith("\n") else text + "\n"


def runner_models_equivalent(left: Any, right: Any) -> bool:
    """Compare adapted Role/Team/Flow models, ignoring envelope chrome and inert fields."""
    return _normalize_runner_dump(left) == _normalize_runner_dump(right)


def _normalize_runner_dump(model: Any) -> Any:
    data = model.model_dump(mode="json")
    return _strip_compare(data, flow_agent=False)


def _strip_compare(value: Any, *, flow_agent: bool) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        spec = value.get("spec")
        is_flow = isinstance(spec, dict) and "agents" in spec and "personas" not in spec
        for key, item in value.items():
            if key in {"apiVersion", "kind"}:
                continue
            if key == "spec_version":
                continue
            if flow_agent and key in _INERT_FLOW_AGENT_KEYS:
                continue
            if key == "secret" and value.get("type") == "webhook":
                continue
            if key == "agents" and is_flow and isinstance(item, dict):
                out[key] = {
                    name: _strip_compare(child, flow_agent=True)
                    if isinstance(child, dict)
                    else child
                    for name, child in item.items()
                }
                continue
            out[key] = _strip_compare(item, flow_agent=False)
        if "metadata" in out and isinstance(out["metadata"], dict):
            out["metadata"].pop("spec_version", None)
        return out
    if isinstance(value, list):
        return [_strip_compare(item, flow_agent=False) for item in value]
    return value


def _atomic_write(path: Path, text: str) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        tmp.chmod(mode)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
