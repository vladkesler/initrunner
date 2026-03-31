"""Base tool configuration classes."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, field_validator


class ToolPermissions(BaseModel):
    """Declarative allow/deny permission rules for tool arguments.

    Pattern format: ``arg_name=glob_pattern`` — *arg_name* matches a tool
    function parameter, *glob_pattern* uses :func:`fnmatch.fnmatch` syntax.
    A bare pattern (no ``=``) matches against all string argument values.

    Evaluation order: deny rules first (deny wins) → allow rules → default.
    """

    default: Literal["allow", "deny"] = "allow"
    allow: list[str] = []
    deny: list[str] = []

    @field_validator("allow", "deny")
    @classmethod
    def _validate_patterns(cls, v: list[str]) -> list[str]:
        for pattern in v:
            if "=" in pattern:
                arg_name, _, glob = pattern.partition("=")
                if not arg_name:
                    raise ValueError(f"empty argument name in pattern: {pattern!r}")
                if not glob:
                    raise ValueError(f"empty glob in pattern: {pattern!r}")
        return v


class ToolConfigBase(BaseModel):
    """Base class for all tool configurations."""

    type: str
    permissions: ToolPermissions | None = None

    def summary(self) -> str:
        return self.type


ToolConfig: TypeAlias = ToolConfigBase
"""Annotation type for lists of tool configs (e.g. ``list[ToolConfig]``)."""
