"""Rich panel renderer for ``ValidationIssue`` lists.

Used by both the run pre-flight and the ``validate`` / ``flow validate``
commands so the broken-YAML UX is identical across surfaces.
"""

from __future__ import annotations

from pathlib import Path

from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from initrunner.services._yaml_validation import ValidationIssue

_SEVERITY_LABELS = {
    "error": ("[ERROR]", "red"),
    "warning": ("[WARN] ", "yellow"),
    "info": ("[INFO] ", "cyan"),
}


def render_validation_panel(
    path: Path,
    kind: str,
    issues: list[ValidationIssue],
) -> Panel:
    """Render *issues* into a single Rich panel.

    The caller decides whether to print and/or exit -- this function only
    builds the panel object.  All user-supplied content is escaped so
    Pydantic messages containing ``[type=string_type, ...]`` cannot be
    misinterpreted as Rich markup.
    """
    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")
    info_count = sum(1 for i in issues if i.severity == "info")
    summary = _format_summary(error_count, warning_count, info_count)

    body = Text()
    if summary:
        body.append(summary, style="dim")
        body.append("\n\n")
    for idx, issue in enumerate(issues):
        if idx > 0:
            body.append("\n\n")
        _append_issue(body, issue)

    has_errors = error_count > 0
    title_word = "Invalid" if has_errors else "Validated"
    border_style = "red" if has_errors else "yellow"
    file_label = escape(str(path))
    title = f"[bold]{title_word} {escape(kind.lower())}.yaml[/bold] -- {file_label}"

    return Panel(body, title=title, border_style=border_style, padding=(1, 2))


def _append_issue(body: Text, issue: ValidationIssue) -> None:
    label, color = _SEVERITY_LABELS.get(issue.severity, ("[?]", "white"))
    body.append(label, style=f"bold {color}")
    body.append(" ")
    body.append(_field_with_location(issue), style="bold")
    body.append("\n  ")
    body.append(issue.message)
    if issue.suggestion:
        body.append("\n  ")
        body.append("Fix: ", style="dim")
        body.append(issue.suggestion, style="dim")


def _field_with_location(issue: ValidationIssue) -> str:
    if issue.line is not None and issue.column is not None:
        return f"{issue.field} (line {issue.line}, col {issue.column})"
    if issue.line is not None:
        return f"{issue.field} (line {issue.line})"
    return issue.field


def _format_summary(errors: int, warnings: int, infos: int) -> str:
    parts: list[str] = []
    if errors:
        parts.append(_pluralize(errors, "error"))
    if warnings:
        parts.append(_pluralize(warnings, "warning"))
    if infos:
        parts.append(_pluralize(infos, "note"))
    return ", ".join(parts)


def _pluralize(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def render_sandbox_error(
    err: object,
) -> Panel:
    """Render a SandboxUnavailableError as a Rich panel."""
    from initrunner.agent.runtime_sandbox.base import SandboxUnavailableError

    if not isinstance(err, SandboxUnavailableError):
        raise TypeError(f"Expected SandboxUnavailableError, got {type(err)}")

    body = Text()
    body.append("[ERROR]", style="bold red")
    body.append(f" Sandbox backend '{err.backend}' unavailable\n\n")
    body.append(err.reason)
    body.append("\n\n")
    body.append("Remediation:\n", style="bold")
    body.append(err.remediation)

    return Panel(
        body,
        title="[bold]Sandbox unavailable[/bold]",
        border_style="red",
        padding=(1, 2),
    )
