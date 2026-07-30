"""Shipped always-on service catalog (collector, …)."""

from __future__ import annotations

from pathlib import Path

CATALOG_ROOT = Path(__file__).resolve().parent


def catalog_root() -> Path:
    """Return the directory that contains shipped service templates."""
    return CATALOG_ROOT
