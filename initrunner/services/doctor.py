"""Doctor service: diagnose provider and role configuration issues."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path

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
# Extended diagnostic data structures
# ---------------------------------------------------------------------------


@dataclass
class McpDiagnosis:
    """Health status for a single MCP server tool."""

    server_label: str  # from config.summary()
    status: str  # "healthy" | "degraded" | "unhealthy" | "skipped"
    latency_ms: int
    tool_count: int
    error: str | None


@dataclass
class SkillDiagnosis:
    """Resolution and requirement status for a single skill reference."""

    ref: str
    resolved: bool
    source_path: str | None
    unmet_requirements: list[str]
    error: str | None


@dataclass
class CustomToolDiagnosis:
    """Import status for a custom tool definition."""

    module: str
    function: str | None
    locatable: bool
    importable: bool | None  # None when not attempted (static mode)
    callable_found: bool | None
    sandbox_violation: str | None
    error: str | None


@dataclass
class MemoryStoreDiagnosis:
    """Health of a memory store path."""

    store_path: str
    parent_exists: bool
    parent_writable: bool
    db_opens: bool | None  # None when not attempted (static mode)
    error: str | None


@dataclass
class TriggerDiagnosis:
    """Validation status for a single trigger."""

    trigger_type: str
    label: str  # from trigger.summary()
    issues: list[str]


@dataclass
class RoleDiagnostics:
    """Aggregated deep diagnostics for a role file."""

    mcp_servers: list[McpDiagnosis]
    skills: list[SkillDiagnosis]
    custom_tools: list[CustomToolDiagnosis]
    memory_store: MemoryStoreDiagnosis | None
    triggers: list[TriggerDiagnosis]


@dataclass
class FlowDiagnostics:
    """Aggregated diagnostics for a flow definition."""

    flow_valid: bool
    flow_error: str | None
    validation_issues: list  # list[ValidationIssue]
    agent_diagnostics: dict[str, RoleDiagnostics | None]
    missing_roles: list[str]
    role_errors: dict[str, str]


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
# Extended role diagnostics
# ---------------------------------------------------------------------------


def diagnose_mcp_servers(
    role: object,
    role_dir: Path | None,
    *,
    deep: bool = False,
) -> list[McpDiagnosis]:
    """Check health of all MCP tool servers configured in a role."""
    from initrunner.agent.schema.tools import McpToolConfig

    spec = role.spec  # type: ignore[attr-defined]
    results: list[McpDiagnosis] = []

    for tool in spec.tools:
        if not isinstance(tool, McpToolConfig):
            continue

        label = tool.summary()

        if not deep:
            results.append(
                McpDiagnosis(
                    server_label=label, status="skipped", latency_ms=0, tool_count=0, error=None
                )
            )
            continue

        if tool.defer:
            results.append(
                McpDiagnosis(
                    server_label=label, status="skipped", latency_ms=0, tool_count=0, error=None
                )
            )
            continue

        try:
            from initrunner.mcp.health import check_health_sync

            health = check_health_sync(tool, role_dir, sandbox=spec.security.tools, server_id=label)
            results.append(
                McpDiagnosis(
                    server_label=label,
                    status=health.status,
                    latency_ms=health.latency_ms,
                    tool_count=health.tool_count,
                    error=health.error,
                )
            )
        except Exception as exc:
            results.append(
                McpDiagnosis(
                    server_label=label,
                    status="unhealthy",
                    latency_ms=0,
                    tool_count=0,
                    error=str(exc),
                )
            )

    return results


def diagnose_skills(
    refs: list[str],
    role_dir: Path | None,
    extra_dirs: list[Path] | None,
) -> list[SkillDiagnosis]:
    """Check skill resolution and requirements for a role.

    Resolves each ref individually so failures are isolated and partial
    results are reported.
    """
    from initrunner.agent.skills import SkillLoadError, resolve_skills

    results: list[SkillDiagnosis] = []

    for ref in refs:
        try:
            resolved = resolve_skills([ref], role_dir, extra_dirs)
            if not resolved:
                results.append(
                    SkillDiagnosis(
                        ref=ref, resolved=False, source_path=None, unmet_requirements=[], error=None
                    )
                )
                continue

            rs = resolved[0]
            unmet = [s.detail for s in rs.requirement_statuses if not s.met]
            results.append(
                SkillDiagnosis(
                    ref=ref,
                    resolved=True,
                    source_path=str(rs.source_path),
                    unmet_requirements=unmet,
                    error=None,
                )
            )
        except SkillLoadError as exc:
            results.append(
                SkillDiagnosis(
                    ref=ref, resolved=False, source_path=None, unmet_requirements=[], error=str(exc)
                )
            )
        except Exception as exc:
            results.append(
                SkillDiagnosis(
                    ref=ref, resolved=False, source_path=None, unmet_requirements=[], error=str(exc)
                )
            )

    return results


def diagnose_custom_tools(
    role: object,
    role_dir: Path | None,
    *,
    deep: bool = False,
) -> list[CustomToolDiagnosis]:
    """Check importability of custom tool modules.

    Mirrors the loading path in ``initrunner/agent/tools/custom.py``:
    adds role_dir to sys.path, runs find_spec (static), optionally imports
    and validates (deep).
    """
    import importlib
    import importlib.util
    import sys

    from initrunner.agent.schema.tools import CustomToolConfig

    spec = role.spec  # type: ignore[attr-defined]
    sandbox = spec.security.tools
    results: list[CustomToolDiagnosis] = []

    for tool in spec.tools:
        if not isinstance(tool, CustomToolConfig):
            continue

        role_dir_str: str | None = None
        if role_dir is not None:
            role_dir_str = str(role_dir)
            if role_dir_str not in sys.path:
                sys.path.insert(0, role_dir_str)

        try:
            # Static: can we find the module?
            found_spec = importlib.util.find_spec(tool.module)
            locatable = found_spec is not None

            # AST validation against sandbox policy
            sandbox_violation: str | None = None
            if found_spec is not None and found_spec.origin:
                origin = Path(found_spec.origin)
                if origin.is_file():
                    try:
                        from initrunner.agent.tools.custom import _validate_source_imports

                        source_text = origin.read_text()
                        _validate_source_imports(source_text, sandbox)
                    except ValueError as ve:
                        sandbox_violation = str(ve)
                    except Exception:
                        pass  # non-critical

            importable: bool | None = None
            callable_found: bool | None = None
            error: str | None = None

            if not locatable:
                error = f"Module '{tool.module}' not found"
            elif deep:
                try:
                    mod = importlib.import_module(tool.module)
                    importable = True

                    if tool.function is not None:
                        func = getattr(mod, tool.function, None)
                        callable_found = func is not None
                        if not callable_found:
                            error = f"Function '{tool.function}' not found in '{tool.module}'"
                    else:
                        from initrunner.agent.tools.custom import _discover_module_tools

                        funcs = _discover_module_tools(mod)
                        callable_found = len(funcs) > 0
                        if not callable_found:
                            error = f"No public callable functions in '{tool.module}'"
                except ImportError as ie:
                    importable = False
                    missing = ie.name or tool.module
                    error = f"Import failed: missing dependency '{missing}'"

            results.append(
                CustomToolDiagnosis(
                    module=tool.module,
                    function=tool.function,
                    locatable=locatable,
                    importable=importable,
                    callable_found=callable_found,
                    sandbox_violation=sandbox_violation,
                    error=error,
                )
            )
        except Exception as exc:
            results.append(
                CustomToolDiagnosis(
                    module=tool.module,
                    function=tool.function,
                    locatable=False,
                    importable=None,
                    callable_found=None,
                    sandbox_violation=None,
                    error=str(exc),
                )
            )
        finally:
            if role_dir_str is not None and role_dir_str in sys.path:
                sys.path.remove(role_dir_str)

    return results


def diagnose_memory_store(
    role: object,
    *,
    deep: bool = False,
) -> MemoryStoreDiagnosis | None:
    """Check memory store accessibility. Returns None if no memory configured."""
    spec = role.spec  # type: ignore[attr-defined]
    metadata = role.metadata  # type: ignore[attr-defined]

    if spec.memory is None:
        return None

    from initrunner.stores.base import resolve_memory_path

    mem_path = resolve_memory_path(spec.memory.store_path, metadata.name)
    store_path_str = str(mem_path)
    parent_exists = mem_path.parent.exists()
    parent_writable = parent_exists and os.access(mem_path.parent, os.W_OK)
    db_opens: bool | None = None
    error: str | None = None

    if deep and mem_path.exists():
        try:
            from initrunner.stores.factory import create_memory_store

            store = create_memory_store(spec.memory.store_backend, mem_path)
            try:
                db_opens = True
            finally:
                store.close()
        except Exception as exc:
            db_opens = False
            error = str(exc)

    return MemoryStoreDiagnosis(
        store_path=store_path_str,
        parent_exists=parent_exists,
        parent_writable=parent_writable,
        db_opens=db_opens,
        error=error,
    )


def diagnose_triggers(role: object) -> list[TriggerDiagnosis]:
    """Validate triggers beyond schema-level checks.

    Paths for file_watch and heartbeat are resolved relative to CWD
    (matching runtime semantics).
    """
    from initrunner.agent.schema.triggers import (
        CronTriggerConfig,
        DiscordTriggerConfig,
        FileWatchTriggerConfig,
        HeartbeatTriggerConfig,
        TelegramTriggerConfig,
        WebhookTriggerConfig,
    )

    spec = role.spec  # type: ignore[attr-defined]
    results: list[TriggerDiagnosis] = []

    for trigger in spec.triggers:
        issues: list[str] = []
        trigger_type = trigger.type
        label = trigger.summary() if hasattr(trigger, "summary") else trigger_type

        try:
            if isinstance(trigger, CronTriggerConfig):
                try:
                    from croniter import croniter  # type: ignore[import-not-found]

                    if not croniter.is_valid(trigger.schedule):
                        issues.append(f"Invalid cron expression: {trigger.schedule}")
                except ImportError:
                    issues.append("croniter not installed (pip install initrunner[triggers])")

                try:
                    from zoneinfo import ZoneInfo

                    ZoneInfo(trigger.timezone)
                except (KeyError, Exception):
                    issues.append(f"Invalid timezone: {trigger.timezone}")

            elif isinstance(trigger, WebhookTriggerConfig):
                if not (1 <= trigger.port <= 65535):
                    issues.append(f"Port {trigger.port} out of valid range")

            elif isinstance(trigger, FileWatchTriggerConfig):
                for p in trigger.paths:
                    if not Path(p).exists():
                        issues.append(f"Watch path does not exist: {p}")

            elif isinstance(trigger, HeartbeatTriggerConfig):
                if not Path(trigger.file).exists():
                    issues.append(f"Checklist file does not exist: {trigger.file}")
                try:
                    from zoneinfo import ZoneInfo

                    ZoneInfo(trigger.timezone)
                except (KeyError, Exception):
                    issues.append(f"Invalid timezone: {trigger.timezone}")

            elif isinstance(trigger, TelegramTriggerConfig):
                if not os.environ.get(trigger.token_env):
                    issues.append(f"Environment variable {trigger.token_env} not set")

            elif isinstance(trigger, DiscordTriggerConfig):
                if not os.environ.get(trigger.token_env):
                    issues.append(f"Environment variable {trigger.token_env} not set")

        except Exception as exc:
            issues.append(f"Check failed: {exc}")

        results.append(TriggerDiagnosis(trigger_type=trigger_type, label=label, issues=issues))

    return results


def diagnose_role_deep(
    role: object,
    role_dir: Path | None,
    *,
    deep: bool = False,
    extra_skill_dirs: list[Path] | None = None,
) -> RoleDiagnostics:
    """Run all extended diagnostics for a validated role."""
    spec = role.spec  # type: ignore[attr-defined]

    return RoleDiagnostics(
        mcp_servers=diagnose_mcp_servers(role, role_dir, deep=deep),
        skills=diagnose_skills(spec.skills, role_dir, extra_skill_dirs),
        custom_tools=diagnose_custom_tools(role, role_dir, deep=deep),
        memory_store=diagnose_memory_store(role, deep=deep),
        triggers=diagnose_triggers(role),
    )


def diagnose_flow(
    flow_path: Path,
    *,
    deep: bool = False,
    extra_skill_dirs: list[Path] | None = None,
) -> FlowDiagnostics:
    """Validate a flow and all its agent roles."""
    from initrunner.services.yaml_validation import validate_yaml_file

    # Structural validation (topology, cycles, role references)
    defn, _kind, issues = validate_yaml_file(flow_path)

    if defn is None:
        error_msgs = [i.message for i in issues if i.severity == "error"]
        return FlowDiagnostics(
            flow_valid=False,
            flow_error="; ".join(error_msgs) if error_msgs else "Flow validation failed",
            validation_issues=issues,
            agent_diagnostics={},
            missing_roles=[],
            role_errors={},
        )

    # Runtime dependency diagnostics per agent
    agent_diagnostics: dict[str, RoleDiagnostics | None] = {}
    missing_roles: list[str] = []
    role_errors: dict[str, str] = {}
    base_dir = flow_path.parent

    for agent_name, cfg in defn.spec.agents.items():
        role_path = base_dir / cfg.role
        if not role_path.exists():
            missing_roles.append(agent_name)
            agent_diagnostics[agent_name] = None
            continue

        try:
            from initrunner._yaml import load_raw_yaml
            from initrunner.deprecations import inspect_role_data

            raw = load_raw_yaml(role_path, ValueError)
            inspection = inspect_role_data(raw)

            if inspection.role is None:
                role_errors[agent_name] = inspection.schema_error or "Failed to validate role"
                agent_diagnostics[agent_name] = None
                continue

            agent_diagnostics[agent_name] = diagnose_role_deep(
                inspection.role,
                role_path.parent,
                deep=deep,
                extra_skill_dirs=extra_skill_dirs,
            )
        except Exception as exc:
            role_errors[agent_name] = str(exc)
            agent_diagnostics[agent_name] = None

    has_errors = (
        bool(missing_roles) or bool(role_errors) or any(i.severity == "error" for i in issues)
    )

    return FlowDiagnostics(
        flow_valid=not has_errors,
        flow_error=None,
        validation_issues=issues,
        agent_diagnostics=agent_diagnostics,
        missing_roles=missing_roles,
        role_errors=role_errors,
    )


def role_diagnostics_to_checks(diag: RoleDiagnostics) -> list:
    """Convert RoleDiagnostics to flat list of DoctorCheck-compatible dicts.

    Returns dicts with ``name``, ``status``, ``message`` keys matching the
    ``DoctorCheck`` schema used by the dashboard API.
    """
    checks: list[dict[str, str]] = []

    for mcp in diag.mcp_servers:
        if mcp.status == "healthy":
            status, msg = "ok", f"Healthy ({mcp.latency_ms}ms, {mcp.tool_count} tools)"
        elif mcp.status == "degraded":
            status, msg = "warn", f"Degraded ({mcp.latency_ms}ms, {mcp.tool_count} tools)"
        elif mcp.status == "skipped":
            status, msg = "ok", "Skipped (use --deep to check)"
        else:
            status, msg = "fail", f"Unhealthy: {mcp.error}"
        checks.append({"name": f"mcp: {mcp.server_label}", "status": status, "message": msg})

    for skill in diag.skills:
        if skill.resolved and not skill.unmet_requirements:
            status, msg = "ok", f"Resolved: {skill.source_path}"
        elif skill.resolved:
            status = "warn"
            msg = f"Resolved but {len(skill.unmet_requirements)} unmet requirement(s)"
        else:
            status, msg = "fail", f"Not found: {skill.error}"
        checks.append({"name": f"skill: {skill.ref}", "status": status, "message": msg})

    for ct in diag.custom_tools:
        label = f"custom: {ct.module}"
        if ct.sandbox_violation:
            status, msg = "fail", f"Sandbox violation: {ct.sandbox_violation}"
        elif not ct.locatable:
            status, msg = "fail", ct.error or "Module not found"
        elif ct.importable is False:
            status, msg = "fail", ct.error or "Import failed"
        elif ct.callable_found is False:
            status, msg = "fail", ct.error or "Function not found"
        elif ct.importable is True:
            status, msg = "ok", "Importable and callable"
        else:
            status, msg = "ok", "Module locatable"
        checks.append({"name": label, "status": status, "message": msg})

    if diag.memory_store is not None:
        ms = diag.memory_store
        if not ms.parent_exists:
            status, msg = "warn", f"Parent directory missing: {ms.store_path}"
        elif not ms.parent_writable:
            status, msg = "fail", f"Parent directory not writable: {ms.store_path}"
        elif ms.db_opens is False:
            status, msg = "fail", f"DB open failed: {ms.error}"
        elif ms.db_opens is True:
            status, msg = "ok", f"Accessible: {ms.store_path}"
        else:
            status, msg = "ok", f"Path writable: {ms.store_path}"
        checks.append({"name": "memory", "status": status, "message": msg})

    for trig in diag.triggers:
        if trig.issues:
            status, msg = "warn", "; ".join(trig.issues)
        else:
            status, msg = "ok", trig.label
        checks.append({"name": f"trigger: {trig.trigger_type}", "status": status, "message": msg})

    return checks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_module_available(module_name: str) -> bool:
    from initrunner._compat import is_extra_available

    return is_extra_available(module_name)
