"""Registry data transfer objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class InstallResult:
    """Result of a successful install."""

    path: Path
    display_name: str


@dataclass
class InstalledRole:
    name: str
    source: str
    repo: str
    ref: str
    local_path: Path
    installed_at: str
    source_type: str = "hub"
    oci_ref: str = ""
    oci_digest: str = ""
    hub_version: str = ""


@dataclass
class UpdateResult:
    name: str
    updated: bool
    old_sha: str
    new_sha: str
    message: str


@dataclass
class InstallPreview:
    """Metadata shown to user before confirming installation."""

    name: str
    description: str
    author: str
    version: str
    source_label: str
    source_type: str  # "oci" or "hub"
    downloads: int = 0
    tools: list[str] = field(default_factory=list)
    model: str = ""
    warnings: list[str] = field(default_factory=list)
