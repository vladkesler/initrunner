"""Starter agent discovery, prerequisite checking, and resolution."""

from __future__ import annotations

import importlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STARTERS_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "_starters"

STARTER_ORDER = [
    "helpdesk",
    "code-review-team",
    "web-researcher",
    "telegram-assistant",
    "discord-assistant",
    "rag-agent",
    "memory-assistant",
    "email-agent",
    "ci-pipeline",
    "support-desk",
]

FEATURE_MAP: list[tuple[str, str]] = [
    ("ingest", "RAG"),
    ("memory", "Memory"),
    ("triggers", "Triggers"),
]

# Maps spec sections / tool types to the pip extra required.
_EXTRA_MARKERS: dict[str, tuple[str, str]] = {
    # key -> (extra name, marker module to try importing)
    "ingest": ("ingest", "pymupdf4llm"),
    "search": ("search", "ddgs"),
    "web_reader": ("search", "ddgs"),
    "telegram": ("telegram", "telegram"),
    "discord": ("discord", "discord"),
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


def derive_features(spec: dict) -> list[str]:
    """Derive user-facing feature labels from a role spec dict."""
    features: list[str] = []
    for key, label in FEATURE_MAP:
        if spec.get(key):
            features.append(label)
    tools = spec.get("tools") or []
    tool_types = {t.get("type", "") for t in tools if isinstance(t, dict)}
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


def _detect_requires_env(raw_yaml: str, data: dict) -> list[str]:
    """Detect required environment variables from triggers and ${VAR} patterns."""
    env_vars: set[str] = set()

    # Trigger token_env fields
    for trigger in data.get("spec", {}).get("triggers") or []:
        if isinstance(trigger, dict) and trigger.get("token_env"):
            env_vars.add(trigger["token_env"])

    # ${VAR} interpolation patterns
    env_vars.update(_ENV_VAR_RE.findall(raw_yaml))

    return sorted(env_vars)


def _detect_requires_extras(data: dict) -> list[str]:
    """Detect required pip extras from spec sections and tool types."""
    extras: set[str] = set()
    spec = data.get("spec") or {}

    if spec.get("ingest"):
        extras.add("ingest")

    tools = spec.get("tools") or []
    tool_types = {t.get("type", "") for t in tools if isinstance(t, dict)}

    for trigger in spec.get("triggers") or []:
        if isinstance(trigger, dict) and trigger.get("type"):
            tool_types.add(trigger["type"])

    for tool_type in tool_types:
        if tool_type in _EXTRA_MARKERS:
            extras.add(_EXTRA_MARKERS[tool_type][0])

    return sorted(extras)


def _detect_requires_user_data(data: dict) -> list[str]:
    """Detect local content paths from ingest.sources."""
    paths: list[str] = []
    ingest = (data.get("spec") or {}).get("ingest")
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
    meta = data.get("metadata") or {}
    spec = data.get("spec") or {}
    kind = data.get("kind", "Agent")

    return StarterEntry(
        slug=slug,
        name=meta.get("name", slug),
        description=(meta.get("description") or "").strip(),
        tags=meta.get("tags") or [],
        features=derive_features(spec),
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

    # Composite starters (subdirectories with compose.yaml or role.yaml)
    for child in STARTERS_DIR.iterdir():
        if not child.is_dir():
            continue
        slug = child.name
        for candidate_name in ("compose.yaml", "role.yaml"):
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


def resolve_starter_path(name: str) -> Path | None:
    """Resolve a starter name to its YAML path, or None if not found."""
    # Single-file starters
    for ext in (".yaml", ".yml"):
        candidate = STARTERS_DIR / f"{name}{ext}"
        if candidate.is_file():
            return candidate

    # Composite starters
    composite = STARTERS_DIR / name
    if composite.is_dir():
        for candidate_name in ("compose.yaml", "role.yaml"):
            candidate = composite / candidate_name
            if candidate.is_file():
                return candidate

    return None


# ---------------------------------------------------------------------------
# Prerequisite checking
# ---------------------------------------------------------------------------


def _is_extra_installed(extra: str) -> bool:
    """Check if a pip extra's marker package is importable."""
    marker = _EXTRA_MARKERS.get(extra)
    if marker is None:
        return True
    _, module_name = marker
    try:
        importlib.import_module(module_name)
    except ImportError:
        return False
    return True


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

    # Missing user data
    for data_path in entry.requires_user_data:
        if not Path(data_path).exists():
            warnings.append(
                f"Starter expects content in {data_path}/ -- add your files there for best results."
            )

    return errors, warnings
