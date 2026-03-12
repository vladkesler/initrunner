"""Compose orchestration service layer."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.audit.logger import AuditLogger
    from initrunner.compose.schema import ComposeDefinition


def load_compose_sync(path: Path) -> ComposeDefinition:
    """Load and validate a compose definition file (sync)."""
    from initrunner.compose.loader import load_compose

    return load_compose(path)


def run_compose_sync(
    compose: ComposeDefinition,
    base_dir: Path,
    *,
    audit_logger: AuditLogger | None = None,
) -> None:
    """Run a compose orchestration (sync, blocking)."""
    from initrunner.compose.orchestrator import run_compose

    run_compose(compose, base_dir, audit_logger=audit_logger)
