"""Starter agent discovery, prerequisite checking, and resolution."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STARTERS_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "_starters"

STARTER_ORDER = [
    "helpdesk",
    "reviewer",
    "debate",
    "reader",
    "scout",
    "telegram",
    "discord",
    "librarian",
    "memory",
    "mail",
    "writer",
    "watcher",
    "pipeline",
    "triage",
    "tasks",
    "planner",
]

# Preference order for the first-hour menu. Filtered at display time.
FIRST_HOUR_STARTERS = ["memory", "helpdesk", "reviewer"]

# Ingest source suffixes that need the ingest extra. .md/.txt/.html are core.
_INGEST_EXTRA_SUFFIXES = {".pdf", ".docx", ".xlsx"}

FEATURE_MAP: list[tuple[str, str]] = [
    ("ingest", "RAG"),
    ("memory", "Memory"),
    ("triggers", "Triggers"),
]

# Maps spec sections / tool types to the pip extra required.
_EXTRA_MARKERS: dict[str, tuple[str, str]] = {
    # key -> (extra name, marker module to try importing)
    "ingest": ("ingest", "pymupdf4llm"),
    "vector": ("vector", "lancedb"),
    "memory": ("vector", "lancedb"),
    "web_scraper": ("vector", "lancedb"),
    "mcp": ("mcp", "fastmcp"),
    "search": ("search", "ddgs"),
    "web_reader": ("search", "ddgs"),
    "telegram": ("telegram", "telegram"),
    "discord": ("discord", "discord"),
    "slack": ("slack", "slack_sdk"),
    "audio": ("audio", "youtube_transcript_api"),
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class StarterEntry:
    slug: str
    name: str
    description: str
    tags: list[str]
    features: list[str]
    kind: str  # Agent, Team, Compose
    path: Path
    requires_env: list[str] = field(default_factory=list)
    requires_extras: list[str] = field(default_factory=list)
    requires_user_data: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Feature derivation (moved from dashboard/routers/builder.py)
# ---------------------------------------------------------------------------


def document_identity(data: dict) -> dict:
    """Name/description/tags from an envelope or a flat document."""
    if isinstance(data.get("metadata"), dict):
        meta = data["metadata"]
        return {
            "name": meta.get("name"),
            "description": meta.get("description") or "",
            "tags": meta.get("tags") or [],
        }
    return {
        "name": data.get("name"),
        "description": data.get("description") or "",
        "tags": data.get("tags") or [],
    }


def document_body(data: dict) -> dict:
    """Feature-bearing mapping: envelope ``spec`` or the flat document itself."""
    spec = data.get("spec")
    if isinstance(spec, dict):
        return spec
    return data


def tool_types_from(tools: list) -> set[str]:
    """Type names from envelope ``{type: ...}`` items or flat shorthand."""
    types: set[str] = set()
    for item in tools:
        if isinstance(item, str):
            types.add(item)
        elif isinstance(item, dict):
            if "type" in item:
                types.add(str(item["type"]))
            elif len(item) == 1:
                types.add(str(next(iter(item))))
    return types


def derive_features(spec: dict) -> list[str]:
    """Derive user-facing feature labels from a role spec or flat document."""
    features: list[str] = []
    for key, label in FEATURE_MAP:
        if spec.get(key):
            features.append(label)
    tool_types = tool_types_from(spec.get("tools") or [])
    if "search" in tool_types or "web_reader" in tool_types:
        features.append("Web")
    if "shell" in tool_types:
        features.append("Shell")
    if "git" in tool_types:
        features.append("Git")
    if "filesystem" in tool_types:
        features.append("Files")
    return features


# ---------------------------------------------------------------------------
# Prerequisite detection
# ---------------------------------------------------------------------------

_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


_TRIGGER_TOKEN_ENV_FIELDS = ("token_env", "app_token_env", "bot_token_env")


def _detect_requires_env(raw_yaml: str, data: dict) -> list[str]:
    """Detect required environment variables from triggers and ${VAR} patterns."""
    env_vars: set[str] = set()

    _default_token_env = {
        "telegram": "TELEGRAM_BOT_TOKEN",
        "discord": "DISCORD_BOT_TOKEN",
    }
    # Trigger *_token_env fields (token_env, app_token_env, bot_token_env)
    for trigger in document_body(data).get("triggers") or []:
        if isinstance(trigger, str):
            if trigger in _default_token_env:
                env_vars.add(_default_token_env[trigger])
            continue
        if isinstance(trigger, dict):
            for field in _TRIGGER_TOKEN_ENV_FIELDS:
                if trigger.get(field):
                    env_vars.add(trigger[field])
            ttype = trigger.get("type")
            if ttype in _default_token_env and not any(
                trigger.get(field) for field in _TRIGGER_TOKEN_ENV_FIELDS
            ):
                env_vars.add(_default_token_env[ttype])

    # ${VAR} interpolation patterns
    env_vars.update(_ENV_VAR_RE.findall(raw_yaml))

    return sorted(env_vars)


def _source_suffix(source: str) -> str:
    """Return the file suffix implied by an ingest glob, or ''."""
    last = source.rsplit("/", 1)[-1]
    if "." not in last:
        return ""
    return "." + last.rsplit(".", 1)[-1].lower()


def _detect_requires_extras(data: dict) -> list[str]:
    """Detect required pip extras from tool types and ingest source formats.

    A bare ``ingest:`` block does not require the ingest extra (only sources
    whose suffix needs pymupdf/docx/xlsx do), but it does need the vector
    store, as does any ``memory:`` block.
    """
    extras: set[str] = set()
    spec = document_body(data)

    ingest = spec.get("ingest") or {}
    if ingest or spec.get("memory"):
        extras.add("vector")
    for source in ingest.get("sources") or []:
        if isinstance(source, str) and _source_suffix(source) in _INGEST_EXTRA_SUFFIXES:
            extras.add("ingest")
            break

    tool_types = tool_types_from(spec.get("tools") or [])

    for trigger in spec.get("triggers") or []:
        if isinstance(trigger, str):
            tool_types.add(trigger)
        elif isinstance(trigger, dict) and trigger.get("type"):
            tool_types.add(trigger["type"])

    for tool_type in tool_types:
        if tool_type in _EXTRA_MARKERS:
            extras.add(_EXTRA_MARKERS[tool_type][0])

    return sorted(extras)


def _detect_requires_user_data(data: dict) -> list[str]:
    """Detect local content paths from ingest.sources."""
    paths: list[str] = []
    ingest = document_body(data).get("ingest")
    if not ingest:
        return paths

    for source in ingest.get("sources") or []:
        if isinstance(source, str) and not source.startswith("http"):
            # Extract the base directory (e.g. "./knowledge-base" from "./knowledge-base/**/*.md")
            parts = source.split("/")
            base = "/".join(p for p in parts if not any(c in p for c in "*?["))
            if base and base != ".":
                paths.append(base)

    return sorted(set(paths))


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _load_single_yaml(path: Path) -> tuple[str, dict] | None:
    """Load a YAML file, returning (raw_text, parsed_dict) or None on failure."""
    import yaml

    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except Exception:
        _logger.debug("Failed to parse starter %s", path, exc_info=True)
        return None

    if not isinstance(data, dict):
        return None
    return raw, data


def _build_entry(slug: str, raw: str, data: dict, path: Path) -> StarterEntry:
    """Build a StarterEntry from parsed YAML data."""
    from initrunner.agent.schema.adapt import run_kind_from_mapping

    identity = document_identity(data)
    try:
        kind = run_kind_from_mapping(data)
    except Exception:
        kind = data.get("kind") or "Agent"

    return StarterEntry(
        slug=slug,
        name=identity.get("name") or slug,
        description=(identity.get("description") or "").strip(),
        tags=identity.get("tags") or [],
        features=derive_features(document_body(data)),
        kind=kind,
        path=path,
        requires_env=_detect_requires_env(raw, data),
        requires_extras=_detect_requires_extras(data),
        requires_user_data=_detect_requires_user_data(data),
    )


def list_starters() -> list[StarterEntry]:
    """Discover all bundled starters, returned in curated order."""
    if not STARTERS_DIR.is_dir():
        return []

    starters: dict[str, StarterEntry] = {}

    # Single-file starters
    for path in STARTERS_DIR.glob("*.yaml"):
        result = _load_single_yaml(path)
        if result is None:
            continue
        raw, data = result
        slug = path.stem
        starters[slug] = _build_entry(slug, raw, data, path)

    # Composite starters (subdirectories with flow.yaml or role.yaml)
    for child in STARTERS_DIR.iterdir():
        if not child.is_dir():
            continue
        slug = child.name
        for candidate_name in ("flow.yaml", "role.yaml"):
            candidate = child / candidate_name
            if candidate.is_file():
                result = _load_single_yaml(candidate)
                if result is None:
                    continue
                raw, data = result
                starters[slug] = _build_entry(slug, raw, data, candidate)
                break

    # Return in curated order, then any remaining alphabetically
    ordered: list[StarterEntry] = []
    for slug in STARTER_ORDER:
        if slug in starters:
            ordered.append(starters.pop(slug))
    ordered.extend(sorted(starters.values(), key=lambda s: s.slug))
    return ordered


def get_starter(slug: str) -> StarterEntry | None:
    """Look up a single starter by slug."""
    for entry in list_starters():
        if entry.slug == slug:
            return entry
    return None


def _within_starters(candidate: Path) -> Path | None:
    """Resolve *candidate* and return it only if it stays inside STARTERS_DIR.

    ``resolve()`` collapses ``..`` and follows symlinks; ``is_relative_to`` then
    rejects anything that lands outside the bundled starters directory. This
    confines a request-supplied starter name so it cannot read arbitrary files.
    """
    root = STARTERS_DIR.resolve()
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved if resolved.is_relative_to(root) else None


def resolve_starter_path(name: str) -> Path | None:
    """Resolve a starter name to its YAML path, or None if not found.

    *name* is request-supplied (builder ``starter_slug``); every candidate is
    confined to STARTERS_DIR, so a crafted name (``../``, absolute, or a symlink)
    cannot escape to read arbitrary files.
    """
    # Single-file starters
    for ext in (".yaml", ".yml"):
        candidate = _within_starters(STARTERS_DIR / f"{name}{ext}")
        if candidate is not None and candidate.is_file():
            return candidate

    # Composite starters
    composite = _within_starters(STARTERS_DIR / name)
    if composite is not None and composite.is_dir():
        for candidate_name in ("flow.yaml", "role.yaml"):
            candidate = _within_starters(composite / candidate_name)
            if candidate is not None and candidate.is_file():
                return candidate

    return None


# ---------------------------------------------------------------------------
# Prerequisite checking
# ---------------------------------------------------------------------------


def _is_extra_installed(extra: str) -> bool:
    """Check if a pip extra's marker package is importable."""
    from initrunner._compat import is_extra_available

    marker = _EXTRA_MARKERS.get(extra)
    if marker is None:
        return True
    _, module_name = marker
    return is_extra_available(module_name)


def check_prerequisites(entry: StarterEntry) -> tuple[list[str], list[str]]:
    """Check starter prerequisites.

    Returns (errors, warnings).
    Errors block execution; warnings are informational.
    """
    # Load dotenv files so tokens in ~/.initrunner/.env are visible
    from initrunner.agent.loader import _load_dotenv

    _load_dotenv(entry.path.parent)

    errors: list[str] = []
    warnings: list[str] = []

    # Missing env vars (with setup guidance when available)
    missing_env = [v for v in entry.requires_env if not os.environ.get(v)]
    if missing_env:
        from initrunner.templates import TEMPLATE_SETUP

        for var in missing_env:
            errors.append(f"Environment variable {var} is not set.")

        # Find setup guidance matching any missing env vars
        missing_set = set(missing_env)
        shown: set[str] = set()
        for setup_name, setup in TEMPLATE_SETUP.items():
            if setup_name in shown:
                continue
            if missing_set & set(setup.get("env_vars") or []):
                shown.add(setup_name)
                errors.append("")
                errors.append(f"  Setup {setup_name}:")
                for i, step in enumerate(setup["steps"], 1):
                    errors.append(f"    {i}. {step}")
                env_list = " ".join(f"{v}=..." for v in setup["env_vars"] if v in missing_set)
                if env_list:
                    errors.append(f"  Then: export {env_list}")
                    errors.append("  Or add it to ~/.initrunner/.env")
                if setup.get("docs_url"):
                    errors.append(f"  Docs: {setup['docs_url']}")

    # Missing extras
    missing_extras = [e for e in entry.requires_extras if not _is_extra_installed(e)]
    if missing_extras:
        extras_str = ",".join(missing_extras)
        errors.append(f'Missing dependencies: uv pip install "initrunner\\[{extras_str}]"')
        errors.append(f"  Or: initrunner doctor --fix --role {entry.path}")

    content = starter_content(entry)
    if entry.requires_user_data and content.kind == "missing":
        dest = entry.requires_user_data[0]
        errors.append(f"Needs docs in {dest}/ -- add files or use the bundled samples.")
    elif content.kind == "bundled":
        warnings.append("Using sample docs. Add files to ./knowledge-base/ to use your own.")

    try:
        from initrunner.services.providers import check_role_provider_compatibility

        compat = check_role_provider_compatibility(entry.path)
        if compat.needs_embeddings and not compat.has_embedding_key:
            errors.append("This starter needs embeddings. Set OPENAI_API_KEY or start Ollama.")
    except Exception:
        _logger.debug("embedding compatibility check failed for %s", entry.slug, exc_info=True)

    return errors, warnings


# ---------------------------------------------------------------------------
# Identity, content root, readiness
# ---------------------------------------------------------------------------


@dataclass
class StarterContent:
    """Where a starter's user-data files come from."""

    kind: str  # local | bundled | missing | none
    root: Path | None
    files: list[Path]
    data_rel: str | None


def get_starter_for_path(role_file: Path) -> StarterEntry | None:
    """Resolve a YAML path inside STARTERS_DIR to its catalog entry.

    Directory starters use the parent folder name (``helpdesk/role.yaml`` →
    ``helpdesk``), not ``role_file.stem``.
    """
    try:
        resolved = role_file.resolve()
        root = STARTERS_DIR.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    try:
        if not resolved.is_relative_to(root):
            return None
    except ValueError:
        return None
    rel = resolved.relative_to(root)
    slug = resolved.stem if len(rel.parts) == 1 else rel.parts[0]
    return get_starter(slug)


def _files_under(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.rglob("*") if p.is_file())


def starter_content(entry: StarterEntry, *, cwd: Path | None = None) -> StarterContent:
    """Pick local files, bundled samples, or missing.

    An existing but empty data directory is ``missing``, not Ready.
    """
    if not entry.requires_user_data:
        return StarterContent(kind="none", root=None, files=[], data_rel=None)

    cwd = cwd or Path.cwd()
    data_rel = entry.requires_user_data[0]
    local_dir = cwd / data_rel
    if local_dir.is_dir():
        local_files = _files_under(local_dir)
        if local_files:
            return StarterContent(kind="local", root=cwd, files=local_files, data_rel=data_rel)
        # Empty dir: user claimed the path. Do not fall back to samples.
        return StarterContent(kind="missing", root=None, files=[], data_rel=data_rel)

    bundled_dir = entry.path.parent / data_rel
    bundled_files = _files_under(bundled_dir)
    if bundled_files:
        return StarterContent(
            kind="bundled",
            root=entry.path.parent,
            files=bundled_files,
            data_rel=data_rel,
        )

    return StarterContent(kind="missing", root=None, files=[], data_rel=data_rel)


def apply_starter_content_root(role: RoleDefinition, role_file: Path) -> RoleDefinition:
    """Point filesystem tools at the same content root ingest will use."""
    entry = get_starter_for_path(role_file)
    if entry is None:
        return role
    content = starter_content(entry)
    if content.root is None:
        return role

    tools = list(role.spec.tools or [])
    updated = False
    new_tools = []
    for tool in tools:
        if getattr(tool, "type", None) == "filesystem":
            rel = getattr(tool, "root_path", None) or "."
            # Already rewritten to an absolute path on a previous pass.
            if Path(rel).is_absolute():
                new_tools.append(tool)
                continue
            new_root = str((content.root / rel).resolve())
            new_tools.append(tool.model_copy(update={"root_path": new_root}))
            updated = True
        else:
            new_tools.append(tool)
    if not updated:
        return role
    new_spec = role.spec.model_copy(update={"tools": new_tools})
    return role.model_copy(update={"spec": new_spec})


def copy_starter_samples(entry: StarterEntry, dest_parent: Path) -> list[Path]:
    """Copy bundled sample data next to a saved role. No-op if dest exists."""
    import shutil

    content = starter_content(entry, cwd=dest_parent)
    if content.kind != "bundled" or not content.data_rel:
        return []
    src = entry.path.parent / content.data_rel
    dest = dest_parent / Path(content.data_rel).name
    if dest.exists() or not src.is_dir():
        return []
    shutil.copytree(src, dest)
    return _files_under(dest)


def is_git_checkout(cwd: Path | None = None) -> bool:
    here = cwd or Path.cwd()
    return (here / ".git").exists() or (here / ".git").is_file()
