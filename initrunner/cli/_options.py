"""Shared CLI option type aliases to eliminate per-command duplication."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

AuditDbOption = Annotated[
    Path | None,
    typer.Option("--audit-db", help="Path to audit database", envvar="INITRUNNER_AUDIT_DB"),
]
NoAuditOption = Annotated[
    bool,
    typer.Option("--no-audit", help="Disable audit logging"),
]
SkillDirOption = Annotated[
    Path | None,
    typer.Option("--skill-dir", help="Extra skill search directory"),
]
ModelOption = Annotated[
    str | None,
    typer.Option(
        "--model",
        help="Model alias or provider:model (overrides role config)",
        envvar="INITRUNNER_MODEL",
    ),
]
