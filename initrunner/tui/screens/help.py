"""HelpScreen — keyboard shortcut reference."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.widgets import DataTable

from initrunner.tui.screens.base import BaseScreen
from initrunner.tui.theme import COLOR_SECONDARY

if TYPE_CHECKING:
    from textual.app import ComposeResult

_SECTIONS = [
    (
        "Global",
        [
            ("?", "Show this help screen"),
            ("a", "Open audit log"),
            ("q", "Quit application"),
            ("Escape", "Go back / close modal"),
        ],
    ),
    (
        "Roles",
        [
            ("Enter", "Open role detail screen"),
            ("Ctrl+R", "Fast run (bypass detail)"),
            ("n", "Scaffold new role from template"),
            ("/", "Filter roles by name"),
            ("r", "Refresh role list"),
        ],
    ),
    (
        "Role Detail",
        [
            ("Enter", "Edit section"),
            ("r", "Run interactive chat"),
            ("v", "Validate role"),
            ("i", "Open ingestion screen"),
            ("d", "Open daemon screen"),
            ("m", "Open memory screen"),
            ("e", "View role YAML"),
        ],
    ),
    (
        "Run",
        [
            ("Ctrl+Enter", "Send message"),
            ("Ctrl+Y", "Copy last agent response"),
            ("Ctrl+D", "Exit chat"),
            ("Ctrl+R", "Resume previous session"),
        ],
    ),
    (
        "Audit",
        [
            ("Enter", "View audit record detail"),
            ("/", "Filter by agent name"),
            ("r", "Refresh audit records"),
        ],
    ),
    (
        "Audit Detail",
        [
            ("y", "Copy agent output"),
        ],
    ),
    (
        "Ingest",
        [
            ("i", "Run ingestion"),
            ("f", "Force re-ingest"),
            ("r", "Refresh sources"),
        ],
    ),
    (
        "Memory",
        [
            ("x", "Clear memory (with confirmation)"),
            ("e", "Export memories to JSON"),
            ("/", "Search memories"),
        ],
    ),
    (
        "Daemon",
        [
            ("s", "Start / stop daemon"),
            ("c", "Clear event log"),
            ("f", "Toggle follow / scroll-lock"),
        ],
    ),
]


class HelpScreen(BaseScreen):
    """Static help screen with keyboard shortcuts."""

    SUB_TITLE = "Keyboard Shortcuts"

    BINDINGS = [
        *BaseScreen.BINDINGS,
        Binding("q", "app.pop_screen", "Close", show=True),
    ]

    def compose_content(self) -> ComposeResult:
        table = DataTable(id="help-table")
        table.cursor_type = "row"
        table.add_columns("Screen", "Key", "Action")
        for section_name, shortcuts in _SECTIONS:
            table.add_row(f"[bold {COLOR_SECONDARY}]── {section_name} ──[/]", "", "")
            for key, action in shortcuts:
                table.add_row("", f"[bold]{key}[/bold]", action)
        yield table
