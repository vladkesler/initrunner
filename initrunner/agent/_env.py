"""Shared environment variable resolution for tool builders."""

from __future__ import annotations

import re

_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def resolve_env_vars(value: str) -> str:
    """Replace ``${VAR}`` placeholders with resolved credential values.

    Falls back to the full resolver chain (env vars → vault), preserving the
    existing contract that unresolved placeholders stay literal so tools that
    embed templates keep working.
    """
    from initrunner.credentials import get_resolver

    resolver = get_resolver()
    return _ENV_VAR_RE.sub(
        lambda m: resolver.get(m.group(1)) or m.group(0),
        value,
    )
