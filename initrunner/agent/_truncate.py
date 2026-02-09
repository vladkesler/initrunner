"""Shared output truncation for tool results."""

from __future__ import annotations

_DEFAULT_SUFFIX = "\n[truncated]"


def truncate_output(text: str, max_chars: int, suffix: str = _DEFAULT_SUFFIX) -> str:
    """Truncate *text* to at most *max_chars* characters, appending *suffix* if truncated."""
    if len(text) <= max_chars:
        return text
    if max_chars <= len(suffix):
        return text[:max_chars]
    return text[: max_chars - len(suffix)] + suffix
