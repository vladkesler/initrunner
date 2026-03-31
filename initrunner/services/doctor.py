"""Doctor service: diagnose provider and role configuration issues."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ProviderDiagnosis:
    """Status of a single LLM provider."""

    provider: str
    env_var: str
    key_set: bool
    sdk_available: bool
    fixable_sdk: bool  # key set + SDK missing + known extra
    fixable_key: bool  # SDK available + no key set
    extras_name: str | None


@dataclass
class RoleExtrasGap:
    """A tool, trigger, or feature that needs an uninstalled pip extra."""

    feature: str
    extras_name: str


@dataclass
class RoleFixPlan:
    """Aggregated fix plan for a role file."""

    missing_extras: list[RoleExtrasGap]
    can_bump_spec_version: bool
    current_spec_version: int
    latest_spec_version: int


# ---------------------------------------------------------------------------
# Feature-to-extras mapping (extends starters._EXTRA_MARKERS)
# ---------------------------------------------------------------------------


def _build_extra_markers() -> dict[str, tuple[str, str]]:
    from initrunner.services.starters import _EXTRA_MARKERS

    markers = dict(_EXTRA_MARKERS)
    markers.setdefault("observability", ("observability", "opentelemetry.sdk"))
    markers.setdefault("pdf_extract", ("ingest", "pymupdf4llm"))
    return markers


# ---------------------------------------------------------------------------
# Provider diagnosis
# ---------------------------------------------------------------------------


def diagnose_providers() -> list[ProviderDiagnosis]:
    """Check each standard provider's API key and SDK status."""
    from initrunner._compat import _PROVIDER_EXTRAS, require_provider
    from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS

    results: list[ProviderDiagnosis] = []
    for provider, env_var in _PROVIDER_API_KEY_ENVS.items():
        key_set = bool(os.environ.get(env_var))
        sdk_available = True
        try:
            require_provider(provider)
        except RuntimeError:
            sdk_available = False

        extras_name = _PROVIDER_EXTRAS.get(provider)
        results.append(
            ProviderDiagnosis(
                provider=provider,
                env_var=env_var,
                key_set=key_set,
                sdk_available=sdk_available,
                fixable_sdk=key_set and not sdk_available and extras_name is not None,
                fixable_key=sdk_available and not key_set,
                extras_name=extras_name,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Role diagnosis
# ---------------------------------------------------------------------------


def diagnose_role_extras(raw_data: dict) -> list[RoleExtrasGap]:
    """Scan a raw role dict for tools/triggers/features needing missing extras."""
    markers = _build_extra_markers()
    spec = raw_data.get("spec", {})
    seen: set[str] = set()
    gaps: list[RoleExtrasGap] = []

    # Collect tool and trigger type names
    feature_names: set[str] = set()
    for tool in spec.get("tools") or []:
        if isinstance(tool, dict) and tool.get("type"):
            feature_names.add(tool["type"])
    for trigger in spec.get("triggers") or []:
        if isinstance(trigger, dict) and trigger.get("type"):
            feature_names.add(trigger["type"])

    # Check spec-level sections
    if spec.get("ingest"):
        feature_names.add("ingest")
    if spec.get("observability"):
        feature_names.add("observability")

    for feature in feature_names:
        if feature not in markers:
            continue
        extras_name, marker_module = markers[feature]
        if extras_name in seen:
            continue
        seen.add(extras_name)
        if not _is_module_available(marker_module):
            gaps.append(RoleExtrasGap(feature=feature, extras_name=extras_name))

    return gaps


def build_role_fix_plan(raw_data: dict) -> RoleFixPlan:
    """Build a fix plan for a role file."""
    from initrunner.deprecations import (
        CURRENT_ROLE_SPEC_VERSION,
        SchemaKind,
        apply_deprecations,
    )

    sv = raw_data.get("metadata", {}).get("spec_version", 1) if isinstance(raw_data, dict) else 1

    missing = diagnose_role_extras(raw_data)

    _, hits = apply_deprecations(raw_data, SchemaKind.ROLE)

    # Spec version bump is only safe when the role validates cleanly
    # and has no deprecation hits at all.
    can_bump = sv < CURRENT_ROLE_SPEC_VERSION and len(hits) == 0
    if can_bump:
        try:
            from initrunner.agent.schema.role import RoleDefinition

            RoleDefinition.model_validate(raw_data)
        except Exception:
            can_bump = False

    return RoleFixPlan(
        missing_extras=missing,
        can_bump_spec_version=can_bump,
        current_spec_version=sv,
        latest_spec_version=CURRENT_ROLE_SPEC_VERSION,
    )


def bump_spec_version(data: dict, target: int) -> dict:
    """Return a deep copy of *data* with ``metadata.spec_version`` set to *target*."""
    out = copy.deepcopy(data)
    out.setdefault("metadata", {})["spec_version"] = target
    return out


def bump_spec_version_text(text: str, target: int) -> str:
    """Surgically patch ``metadata.spec_version`` in raw YAML text.

    Preserves comments, block scalars, flow-style lists, and all other
    formatting.  Raises ``ValueError`` if the metadata block cannot be
    located or patched.
    """
    import re

    # Detect newline style
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)

    # Find `metadata:` top-level key
    meta_idx: int | None = None
    for i, line in enumerate(lines):
        if re.match(r"^metadata:\s*$", line) or re.match(r"^metadata:\s*#", line):
            meta_idx = i
            break

    if meta_idx is None:
        raise ValueError("Cannot patch spec_version: no metadata: block found")

    # Detect child indentation from first indented child line
    indent: str | None = None
    for i in range(meta_idx + 1, len(lines)):
        line = lines[i]
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        leading = line[: len(line) - len(stripped)]
        if leading:
            indent = leading
            break
        else:
            # Hit a top-level key with no children in between
            break

    if indent is None:
        raise ValueError("Cannot patch spec_version: no metadata fields found")

    # Find the end of the metadata block (next top-level key or EOF)
    meta_end = len(lines)
    for i in range(meta_idx + 1, len(lines)):
        line = lines[i]
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        # Top-level key: no leading whitespace and contains ':'
        if line[0] not in (" ", "\t") and ":" in line:
            meta_end = i
            break

    # Case A: spec_version exists in metadata block -- replace it
    sv_pattern = re.compile(r"^(\s+)spec_version:\s*\d+(.*)")
    for i in range(meta_idx + 1, meta_end):
        m = sv_pattern.match(lines[i])
        if m:
            trailing = m.group(2)  # preserve inline comments
            lines[i] = f"{indent}spec_version: {target}{trailing}"
            return nl.join(lines)

    # Case B: spec_version missing -- insert before the next top-level key
    new_line = f"{indent}spec_version: {target}"
    lines.insert(meta_end, new_line)
    return nl.join(lines)


def derive_role_provider(raw_data: dict) -> tuple[str, str] | None:
    """Extract ``(provider, env_var)`` from a role's model config.

    Honors ``spec.model.api_key_env`` when set.  Returns ``None`` when the
    provider cannot be determined.
    """
    from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS

    spec = raw_data.get("spec", {})
    model = spec.get("model", {})
    if not isinstance(model, dict):
        return None

    provider = model.get("provider")
    if not provider:
        return None

    env_var = model.get("api_key_env") or _PROVIDER_API_KEY_ENVS.get(provider)
    if not env_var:
        return None

    return provider, env_var


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_module_available(module_name: str) -> bool:
    from initrunner._compat import is_extra_available

    return is_extra_available(module_name)
