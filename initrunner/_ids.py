"""Shared short-ID generator."""

from __future__ import annotations

import uuid


def generate_id(length: int = 12) -> str:
    """Return a random hex string of *length* characters."""
    return uuid.uuid4().hex[:length]
