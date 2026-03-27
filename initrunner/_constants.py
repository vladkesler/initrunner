"""Shared constants used across ingestion, discovery, and skill scanning."""

from __future__ import annotations

SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".git",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".eggs",
        ".hg",
        ".svn",
    }
)
