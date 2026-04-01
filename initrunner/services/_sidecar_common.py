"""Shared utilities for import sidecar module generation.

Used by both ``langchain_import`` and ``pydanticai_import`` to validate
generated sidecar tool modules against the default sandbox blocked list.
"""

from __future__ import annotations

import ast

# Default blocked imports for custom tool sandbox
DEFAULT_BLOCKED_MODULES: frozenset[str] = frozenset(
    {
        "os",
        "subprocess",
        "shutil",
        "sys",
        "importlib",
        "ctypes",
        "socket",
        "http.server",
        "pickle",
        "shelve",
        "marshal",
        "code",
        "codeop",
        "threading",
        "_thread",
    }
)


def validate_sidecar_imports(sidecar_source: str) -> list[str]:
    """Check sidecar source against the default sandbox blocked module list.

    Returns a list of warning strings for any blocked imports found.
    Does NOT raise -- the caller decides severity.
    """
    warnings: list[str] = []
    try:
        tree = ast.parse(sidecar_source)
    except SyntaxError:
        warnings.append("Generated sidecar module has syntax errors -- review manually.")
        return warnings

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                base = (alias.name or "").split(".")[0]
                if isinstance(node, ast.ImportFrom) and node.module:
                    base = node.module.split(".")[0]
                if base in DEFAULT_BLOCKED_MODULES:
                    warnings.append(
                        f"Sidecar tool module imports '{base}' which is blocked by"
                        " default sandbox policy."
                        " Review security.sandbox.blocked_custom_modules."
                    )

    return warnings
