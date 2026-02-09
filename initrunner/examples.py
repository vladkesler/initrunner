"""Examples catalog: browse, preview, and copy bundled example roles/compose/skills."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger(__name__)

_CATALOG_FILE = Path(__file__).parent / "_examples_catalog.json"

# GitHub raw content base URL for multi-file downloads
_GITHUB_REPO = "vladkesler/initrunner"
_GITHUB_BRANCH = "main"
_GITHUB_RAW_BASE = f"https://raw.githubusercontent.com/{_GITHUB_REPO}/{_GITHUB_BRANCH}/examples"


class ExampleNotFoundError(Exception):
    """Raised when a named example doesn't exist in the catalog."""


class ExampleDownloadError(Exception):
    """Raised when downloading multi-file example content fails."""


@dataclass
class ExampleEntry:
    """A single example from the catalog."""

    name: str
    category: str
    description: str
    tags: list[str]
    files: list[str]
    primary_file: str
    primary_content: str
    multi_file: bool
    difficulty: str
    features: list[str]
    tools: list[str]


def _load_catalog() -> list[ExampleEntry]:
    """Load the bundled examples catalog."""
    if not _CATALOG_FILE.exists():
        _logger.warning("Examples catalog not found at %s", _CATALOG_FILE)
        return []

    raw = json.loads(_CATALOG_FILE.read_text(encoding="utf-8"))
    entries = []
    for item in raw:
        entries.append(
            ExampleEntry(
                name=item["name"],
                category=item["category"],
                description=item["description"],
                tags=item.get("tags", []),
                files=item.get("files", []),
                primary_file=item["primary_file"],
                primary_content=item["primary_content"],
                multi_file=item.get("multi_file", False),
                difficulty=item.get("difficulty", "beginner"),
                features=item.get("features", []),
                tools=item.get("tools", []),
            )
        )
    return entries


def list_examples(
    category: str | None = None,
    tag: str | None = None,
) -> list[ExampleEntry]:
    """Return filtered list of examples."""
    entries = _load_catalog()

    if category:
        entries = [e for e in entries if e.category == category]
    if tag:
        entries = [e for e in entries if tag in e.tags]

    return entries


def get_example(name: str) -> ExampleEntry:
    """Look up a single example by name."""
    for entry in _load_catalog():
        if entry.name == name:
            return entry
    raise ExampleNotFoundError(f"Example '{name}' not found in catalog.")


def show_example(name: str) -> str:
    """Return the primary file content for an example."""
    entry = get_example(name)
    return entry.primary_content


def _build_request(url: str) -> urllib.request.Request:
    """Build a urllib Request with optional GitHub token."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "initrunner-examples")
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"token {token}")
    return req


def _download_file(url: str) -> bytes:
    """Download a single file from GitHub."""
    try:
        req = _build_request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ExampleDownloadError(f"File not found at {url}") from e
        if e.code == 403:
            raise ExampleDownloadError(
                "GitHub API rate limit reached. Set GITHUB_TOKEN env var for higher limits."
            ) from e
        raise ExampleDownloadError(f"HTTP {e.code} downloading {url}") from e
    except urllib.error.URLError as e:
        raise ExampleDownloadError("Could not reach GitHub. Check your connection.") from e


def copy_example(name: str, output_dir: Path) -> list[Path]:
    """Copy example files to output_dir. Returns list of written paths.

    Single-file examples are served from the catalog (no network).
    Multi-file examples download additional files from GitHub.
    """
    entry = get_example(name)
    written: list[Path] = []

    # Map from category to examples/ subdir
    category_dirs = {"role": "roles", "compose": "compose", "skill": "skills"}
    category_subdir = category_dirs.get(entry.category, entry.category)

    for rel_path in entry.files:
        dest = output_dir / rel_path
        if dest.exists():
            raise FileExistsError(f"File already exists: {dest}")

    for rel_path in entry.files:
        dest = output_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        if rel_path == entry.primary_file:
            # Primary file is embedded in the catalog
            dest.write_text(entry.primary_content, encoding="utf-8")
        else:
            # Download from GitHub
            url = f"{_GITHUB_RAW_BASE}/{category_subdir}/{rel_path}"
            _logger.info("Downloading %s", url)
            data = _download_file(url)
            dest.write_bytes(data)

        written.append(dest)

    return written
