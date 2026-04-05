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


# ---------------------------------------------------------------------------
# AST extraction helpers
# ---------------------------------------------------------------------------


def _get_string_value(node: ast.expr) -> str | None:
    """Extract a string constant from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _get_number_value(node: ast.expr) -> float | int | None:
    """Extract a numeric constant from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    return None


def _get_keyword_value(call: ast.Call, name: str) -> ast.expr | None:
    """Find a keyword argument by name in a Call node."""
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _get_call_name(node: ast.Call) -> str | None:
    """Get the full dotted name of a Call (e.g. ``Agent``, ``OpenAIModel``)."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        parts: list[str] = []
        current: ast.expr = node.func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _extract_imports(tree: ast.Module) -> list[str]:
    """Collect all import statements as source text."""
    imports: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    imports.append(f"import {alias.name} as {alias.asname}")
                else:
                    imports.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = ", ".join(f"{a.name} as {a.asname}" if a.asname else a.name for a in node.names)
            imports.append(f"from {module} import {names}")
    return imports


def _assemble_sidecar_source(
    *,
    framework_label: str,
    framework_prefixes: tuple[str, ...],
    raw_imports: list[str],
    tool_sources: list[str],
) -> str:
    """Build a standalone sidecar module from extracted tool sources.

    Filters out framework-specific imports and assembles the remaining imports
    together with the tool function sources.
    """
    parts: list[str] = [
        f'"""Custom tools extracted from {framework_label} agent."""',
        "",
    ]

    relevant_imports = [
        imp
        for imp in raw_imports
        if not any(
            imp.lstrip().startswith(f"from {p}") or imp.lstrip().startswith(f"import {p}")
            for p in framework_prefixes
        )
    ]
    if relevant_imports:
        parts.extend(relevant_imports)
        parts.append("")

    for src in tool_sources:
        parts.append("")
        parts.append(src.rstrip())
        parts.append("")

    return "\n".join(parts)
