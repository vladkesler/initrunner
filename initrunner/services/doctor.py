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
class SecurityDiagnosis:
    """Security posture summary for a role."""

    preset: str | None
    effective_label: str
    has_external_triggers: bool
    policy_dir_set: bool
    warning: str | None


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
    fixable_deprecations: list  # list[DeprecationHit] (lazy import avoids cycle)


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
    from initrunner.services.providers import PROVIDER_KEY_ENVS_DICT as _PROVIDER_API_KEY_ENVS

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
    fixable = [h for h in hits if h.auto_fixed]
    unfixed_errors = [h for h in hits if h.severity == "error" and not h.auto_fixed]

    # Spec version bump is safe when the only errors are auto-fixable.
    can_bump = sv < CURRENT_ROLE_SPEC_VERSION and len(unfixed_errors) == 0
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
        fixable_deprecations=fixable,
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


def patch_deprecation_text(text: str, hit: object) -> str:
    """Surgically patch a single deprecation hit in raw YAML text.

    *hit* is a ``DeprecationHit`` (typed as ``object`` to avoid import cycle).
    Preserves comments, indentation, and other formatting.
    Raises ``ValueError`` if the pattern cannot be located.
    """
    hit_id: str = hit.id  # type: ignore[attr-defined]
    field_path: str = hit.field_path  # type: ignore[attr-defined]
    if hit_id in ("DEP002", "DEP003", "DEP004", "DEP005"):
        return _patch_store_backend_zvec(text, field_path)
    if hit_id == "DEP001":
        return _patch_max_memories_to_semantic(text)
    raise ValueError(f"No text patch available for {hit_id}")


def _patch_store_backend_zvec(text: str, field_path: str) -> str:
    """Replace ``store_backend: zvec`` with ``store_backend: lancedb`` in the
    correct YAML section identified by *field_path*.
    """
    import re

    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)

    parts = field_path.split(".")
    section_key = parts[-2]  # e.g. "memory", "ingest", "shared_memory"

    section_pattern = re.compile(rf"^(\s*){re.escape(section_key)}:\s*(?:#.*)?$")
    for i, line in enumerate(lines):
        m = section_pattern.match(line)
        if not m:
            continue
        section_indent_len = len(m.group(1))
        for j in range(i + 1, len(lines)):
            stripped = lines[j].lstrip()
            if not stripped or stripped.startswith("#"):
                continue
            line_indent_len = len(lines[j]) - len(stripped)
            if line_indent_len <= section_indent_len:
                break  # left the section
            if re.match(r"\s*store_backend:\s*zvec\b", lines[j]):
                lines[j] = lines[j].replace("zvec", "lancedb", 1)
                return nl.join(lines)

    raise ValueError(f"Cannot locate store_backend: zvec in {section_key} section")


def _patch_max_memories_to_semantic(text: str) -> str:
    """Move ``max_memories: <N>`` under a ``semantic:`` block within ``memory:``.

    Handles three cases:
    1. No existing ``semantic:`` -- replace the line with a new block.
    2. ``semantic:`` exists without ``max_memories`` -- insert into it.
    3. ``semantic:`` exists with ``max_memories`` -- just remove the top-level line.
    """
    import re

    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)

    # Find the ``memory:`` section
    memory_pattern = re.compile(r"^(\s*)memory:\s*(?:#.*)?$")
    for i, line in enumerate(lines):
        m = memory_pattern.match(line)
        if not m:
            continue
        parent_indent = m.group(1)

        # Detect child indentation from the first non-blank, non-comment child
        child_indent: str | None = None
        for ci in range(i + 1, len(lines)):
            s = lines[ci].lstrip()
            if s and not s.startswith("#"):
                child_indent = lines[ci][: len(lines[ci]) - len(s)]
                break
        if child_indent is None:
            break

        # Find max_memories and semantic lines within the memory block
        mm_line_idx: int | None = None
        mm_value: str = ""
        mm_trailing: str = ""
        semantic_line_idx: int | None = None
        semantic_has_max_memories = False

        for j in range(i + 1, len(lines)):
            stripped = lines[j].lstrip()
            if not stripped or stripped.startswith("#"):
                continue
            line_indent_len = len(lines[j]) - len(stripped)
            if line_indent_len <= len(parent_indent):
                break  # left the memory section

            # Direct child: max_memories
            mm_match = re.match(
                rf"^{re.escape(child_indent)}max_memories:\s*(\d+)(.*?)$",
                lines[j],
            )
            if mm_match:
                mm_line_idx = j
                mm_value = mm_match.group(1)
                mm_trailing = mm_match.group(2)
                continue

            # Direct child: semantic
            sem_match = re.match(
                rf"^{re.escape(child_indent)}semantic:\s*(?:#.*)?$",
                lines[j],
            )
            if sem_match:
                semantic_line_idx = j
                # Check if semantic already has max_memories
                grandchild_indent = child_indent + child_indent[len(parent_indent) :]
                for k in range(j + 1, len(lines)):
                    gs = lines[k].lstrip()
                    if not gs or gs.startswith("#"):
                        continue
                    gk_indent_len = len(lines[k]) - len(gs)
                    if gk_indent_len <= len(child_indent):
                        break
                    if re.match(
                        rf"^{re.escape(grandchild_indent)}max_memories:\s*\d+",
                        lines[k],
                    ):
                        semantic_has_max_memories = True
                        break

        if mm_line_idx is None:
            raise ValueError("Cannot locate max_memories in memory section")

        grandchild_indent = child_indent + child_indent[len(parent_indent) :]

        if semantic_line_idx is not None:
            # Case 2 or 3: semantic block exists
            del lines[mm_line_idx]
            if not semantic_has_max_memories:
                # Insert max_memories as first child of semantic
                insert_idx = (
                    semantic_line_idx + 1 if semantic_line_idx < mm_line_idx else semantic_line_idx
                )
                new_line = f"{grandchild_indent}max_memories: {mm_value}{mm_trailing}"
                lines.insert(insert_idx, new_line)
        else:
            # Case 1: no semantic block -- replace in place
            lines[mm_line_idx : mm_line_idx + 1] = [
                f"{child_indent}semantic:",
                f"{grandchild_indent}max_memories: {mm_value}{mm_trailing}",
            ]

        return nl.join(lines)

    raise ValueError("Cannot locate memory section in YAML")


def derive_role_provider(raw_data: dict) -> tuple[str, str] | None:
    """Extract ``(provider, env_var)`` from a role's model config.

    Honors ``spec.model.api_key_env`` when set.  Returns ``None`` when the
    provider cannot be determined.
    """
    from initrunner.services.providers import PROVIDER_KEY_ENVS_DICT as _PROVIDER_API_KEY_ENVS

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
# Security diagnosis
# ---------------------------------------------------------------------------

_EXTERNAL_INPUT_TRIGGERS = frozenset({"webhook", "telegram", "discord"})


def diagnose_security(role: object) -> SecurityDiagnosis:
    """Diagnose the security posture of a validated role.

    Accepts a ``RoleDefinition`` (imported lazily to avoid circular imports).
    """
    spec = role.spec  # type: ignore[attr-defined]
    security = spec.security
    preset = security.preset
    label = security.effective_label

    has_external = any(
        t.type in _EXTERNAL_INPUT_TRIGGERS
        for t in spec.triggers  # type: ignore[attr-defined]
    )

    policy_dir_set = bool(os.environ.get("INITRUNNER_POLICY_DIR", "").strip())

    warning: str | None = None
    if label == "default" and has_external:
        warning = (
            "Security policy is at defaults. "
            "Consider adding security: {preset: public} for agents with external triggers."
        )
    elif label == "development" and has_external:
        warning = (
            "Development preset relaxes rate limits and content filtering. "
            "Review if this agent handles untrusted input."
        )

    return SecurityDiagnosis(
        preset=preset,
        effective_label=label,
        has_external_triggers=has_external,
        policy_dir_set=policy_dir_set,
        warning=warning,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_module_available(module_name: str) -> bool:
    from initrunner._compat import is_extra_available

    return is_extra_available(module_name)
