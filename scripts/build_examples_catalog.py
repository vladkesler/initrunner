#!/usr/bin/env python3
"""Build the examples catalog JSON from the examples/ directory.

Run after adding or modifying examples:

    python scripts/build_examples_catalog.py

Output is committed to the repo as initrunner/_examples_catalog.json so that
pip-installed users can browse examples without network access.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional: try to parse YAML for richer metadata.  Falls back to regex
# extraction if PyYAML isn't available (unlikely in dev, but defensive).
# ---------------------------------------------------------------------------
try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"
OUTPUT_FILE = REPO_ROOT / "initrunner" / "_examples_catalog.json"

SKIP_NAMES = {"__pycache__", ".pyc", ".env.example"}

# Categories map top-level dirs to catalog category names
CATEGORIES = {
    "roles": "role",
    "compose": "compose",
    "skills": "skill",
}

# Features detected from YAML keys
FEATURE_KEYS = {
    "ingest": "ingestion",
    "memory": "memory",
    "skills": "skills",
    "triggers": "triggers",
    "sinks": "sinks",
}


def _parse_yaml(text: str) -> dict:
    """Parse YAML content, with fallback to empty dict."""
    if yaml is not None:
        try:
            return yaml.safe_load(text) or {}
        except yaml.YAMLError:
            return {}
    return {}


def _parse_skill_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from a SKILL.md file."""
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    fm_text = text[3:end].strip()
    return _parse_yaml(fm_text)


def _extract_tools(spec: dict) -> list[str]:
    """Extract tool type names from a role spec."""
    tools = spec.get("tools", [])
    if not isinstance(tools, list):
        return []
    return [t["type"] for t in tools if isinstance(t, dict) and "type" in t]


def _detect_features(spec: dict) -> list[str]:
    """Detect high-level features from spec keys."""
    features = []
    for key, feature_name in FEATURE_KEYS.items():
        if spec.get(key):
            features.append(feature_name)
    return features


def _classify_difficulty(data: dict, multi_file: bool) -> str:
    """Heuristic difficulty classification."""
    spec = data.get("spec", {})
    tools = _extract_tools(spec)
    features = _detect_features(spec)

    if multi_file or len(features) >= 2 or len(tools) >= 3:
        return "advanced"
    if features or len(tools) >= 2:
        return "intermediate"
    return "beginner"


def _collect_files(entry_path: Path, category_dir: Path) -> list[str]:
    """Collect all files relative to category_dir for a given entry."""
    if entry_path.is_file():
        return [entry_path.relative_to(category_dir).as_posix()]

    files = []
    for f in sorted(entry_path.rglob("*")):
        if f.is_dir():
            continue
        if f.name in SKIP_NAMES or f.suffix == ".pyc" or "__pycache__" in f.parts:
            continue
        files.append(f.relative_to(category_dir).as_posix())
    return files


def _build_role_entry(path: Path, category_dir: Path) -> dict | None:
    """Build a catalog entry for a role example."""
    if path.is_file() and path.suffix in (".yaml", ".yml"):
        # Single-file role
        content = path.read_text(encoding="utf-8")
        data = _parse_yaml(content)
        metadata = data.get("metadata", {})
        spec = data.get("spec", {})

        return {
            "name": metadata.get("name", path.stem),
            "category": "role",
            "description": metadata.get("description", ""),
            "tags": metadata.get("tags", []),
            "files": _collect_files(path, category_dir),
            "primary_file": path.relative_to(category_dir).as_posix(),
            "primary_content": content,
            "multi_file": False,
            "difficulty": _classify_difficulty(data, multi_file=False),
            "features": _detect_features(spec),
            "tools": _extract_tools(spec),
        }

    if path.is_dir():
        # Multi-file role: find the primary YAML
        yamls = list(path.glob("*.yaml")) + list(path.glob("*.yml"))
        primary = None
        for y in yamls:
            if y.stem == path.name:
                primary = y
                break
        if primary is None and yamls:
            primary = yamls[0]
        if primary is None:
            return None

        content = primary.read_text(encoding="utf-8")
        data = _parse_yaml(content)
        metadata = data.get("metadata", {})
        spec = data.get("spec", {})

        return {
            "name": metadata.get("name", path.name),
            "category": "role",
            "description": metadata.get("description", ""),
            "tags": metadata.get("tags", []),
            "files": _collect_files(path, category_dir),
            "primary_file": primary.relative_to(category_dir).as_posix(),
            "primary_content": content,
            "multi_file": True,
            "difficulty": _classify_difficulty(data, multi_file=True),
            "features": _detect_features(spec),
            "tools": _extract_tools(spec),
        }

    return None


def _build_compose_entry(path: Path, category_dir: Path) -> dict | None:
    """Build a catalog entry for a compose example."""
    if path.is_file() and path.name in ("compose.yaml", "compose.yml"):
        # Top-level compose file with roles/ subdir
        content = path.read_text(encoding="utf-8")
        data = _parse_yaml(content)
        metadata = data.get("metadata", {})
        parent = path.parent

        # Collect all files under the parent dir
        files = _collect_files(parent, category_dir)

        return {
            "name": metadata.get("name", parent.name if parent != category_dir else "compose"),
            "category": "compose",
            "description": metadata.get("description", ""),
            "tags": metadata.get("tags", []),
            "files": files,
            "primary_file": path.relative_to(category_dir).as_posix(),
            "primary_content": content,
            "multi_file": len(files) > 1,
            "difficulty": "advanced",
            "features": ["compose"],
            "tools": [],
        }

    if path.is_dir():
        compose_file = path / "compose.yaml"
        if not compose_file.exists():
            compose_file = path / "compose.yml"
        if not compose_file.exists():
            return None

        content = compose_file.read_text(encoding="utf-8")
        data = _parse_yaml(content)
        metadata = data.get("metadata", {})

        return {
            "name": metadata.get("name", path.name),
            "category": "compose",
            "description": metadata.get("description", ""),
            "tags": metadata.get("tags", []),
            "files": _collect_files(path, category_dir),
            "primary_file": compose_file.relative_to(category_dir).as_posix(),
            "primary_content": content,
            "multi_file": True,
            "difficulty": "advanced",
            "features": ["compose"],
            "tools": [],
        }

    return None


def _build_skill_entry(path: Path, category_dir: Path) -> dict | None:
    """Build a catalog entry for a skill example."""
    if path.is_file() and path.suffix == ".md":
        content = path.read_text(encoding="utf-8")
        fm = _parse_skill_frontmatter(content)
        tools = []
        for t in fm.get("tools", []):
            if isinstance(t, dict) and "type" in t:
                tools.append(t["type"])

        return {
            "name": fm.get("name", path.stem),
            "category": "skill",
            "description": fm.get("description", ""),
            "tags": [
                t.strip() for t in fm.get("metadata", {}).get("tags", "").split(",") if t.strip()
            ],
            "files": _collect_files(path, category_dir),
            "primary_file": path.relative_to(category_dir).as_posix(),
            "primary_content": content,
            "multi_file": False,
            "difficulty": "beginner",
            "features": ["skills"],
            "tools": tools,
        }

    if path.is_dir():
        skill_md = path / "SKILL.md"
        if not skill_md.exists():
            return None

        content = skill_md.read_text(encoding="utf-8")
        fm = _parse_skill_frontmatter(content)
        tools = []
        for t in fm.get("tools", []):
            if isinstance(t, dict) and "type" in t:
                tools.append(t["type"])

        files = _collect_files(path, category_dir)

        return {
            "name": fm.get("name", path.name),
            "category": "skill",
            "description": fm.get("description", ""),
            "tags": [
                t.strip() for t in fm.get("metadata", {}).get("tags", "").split(",") if t.strip()
            ],
            "files": files,
            "primary_file": skill_md.relative_to(category_dir).as_posix(),
            "primary_content": content,
            "multi_file": len(files) > 1,
            "difficulty": "intermediate" if len(files) > 1 else "beginner",
            "features": ["skills"],
            "tools": tools,
        }

    return None


def build_catalog() -> list[dict]:
    """Scan examples/ and build the full catalog."""
    catalog: list[dict] = []
    seen_names: set[str] = set()

    for dir_name, category in CATEGORIES.items():
        category_dir = EXAMPLES_DIR / dir_name
        if not category_dir.is_dir():
            continue

        if category == "role":
            # Process single-file roles
            for f in sorted(category_dir.glob("*.yaml")):
                entry = _build_role_entry(f, category_dir)
                if entry and entry["name"] not in seen_names:
                    catalog.append(entry)
                    seen_names.add(entry["name"])

            # Process directory-based roles
            for d in sorted(category_dir.iterdir()):
                if d.is_dir() and d.name not in SKIP_NAMES and "__pycache__" not in d.name:
                    entry = _build_role_entry(d, category_dir)
                    if entry and entry["name"] not in seen_names:
                        catalog.append(entry)
                        seen_names.add(entry["name"])

        elif category == "compose":
            # Top-level compose.yaml
            top_compose = category_dir / "compose.yaml"
            if top_compose.exists():
                entry = _build_compose_entry(top_compose, category_dir)
                if entry and entry["name"] not in seen_names:
                    catalog.append(entry)
                    seen_names.add(entry["name"])

            # Sub-directory compose examples
            for d in sorted(category_dir.iterdir()):
                if d.is_dir() and d.name not in ("roles",) and d.name not in SKIP_NAMES:
                    entry = _build_compose_entry(d, category_dir)
                    if entry and entry["name"] not in seen_names:
                        catalog.append(entry)
                        seen_names.add(entry["name"])

        elif category == "skill":
            # Single-file skills
            for f in sorted(category_dir.glob("*.md")):
                entry = _build_skill_entry(f, category_dir)
                if entry and entry["name"] not in seen_names:
                    catalog.append(entry)
                    seen_names.add(entry["name"])

            # Directory-based skills
            for d in sorted(category_dir.iterdir()):
                if d.is_dir() and d.name not in SKIP_NAMES:
                    entry = _build_skill_entry(d, category_dir)
                    if entry and entry["name"] not in seen_names:
                        catalog.append(entry)
                        seen_names.add(entry["name"])

    # Sort by category, then name
    catalog.sort(key=lambda e: (e["category"], e["name"]))
    return catalog


def main() -> None:
    if not EXAMPLES_DIR.is_dir():
        print(f"Error: {EXAMPLES_DIR} not found", file=sys.stderr)
        sys.exit(1)

    catalog = build_catalog()
    OUTPUT_FILE.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(catalog)} examples to {OUTPUT_FILE}")

    # Summary
    by_cat = {}
    for e in catalog:
        by_cat.setdefault(e["category"], []).append(e["name"])
    for cat in sorted(by_cat):
        print(f"  {cat}: {len(by_cat[cat])} ({', '.join(by_cat[cat])})")


if __name__ == "__main__":
    main()
