"""Shared environment variable resolution for tool builders."""

from __future__ import annotations

import os
import re

_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def resolve_env_vars(value: str) -> str:
    """Replace ``${VAR}`` placeholders with environment variable values.

    Unresolved placeholders are left as-is.
    """
    return _ENV_VAR_RE.sub(
        lambda m: os.environ.get(m.group(1), m.group(0)),
        value,
    )
