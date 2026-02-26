"""Main Textual App for InitRunner TUI."""

from __future__ import annotations

from pathlib import Path

from textual.app import App
from textual.binding import Binding

from initrunner.tui.theme import INITRUNNER_THEME


class InitRunnerApp(App):
    """k9s-style TUI dashboard for InitRunner."""

    TITLE = "InitRunner"
    CSS_PATH = "app.tcss"
    theme = "initrunner"

    BINDINGS = [
        Binding("question_mark", "help", "Help"),
        Binding("c", "quick_chat", "Chat"),
        Binding("a", "audit", "Audit"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, *, role_dir: Path | None = None) -> None:
        super().__init__()
        self.register_theme(INITRUNNER_THEME)
        self.role_dir = role_dir

    def on_mount(self) -> None:
        from initrunner.tui.screens.roles import RolesScreen

        self.push_screen(RolesScreen(role_dir=self.role_dir))

    def action_help(self) -> None:
        from initrunner.tui.screens.help import HelpScreen

        self.push_screen(HelpScreen())

    def action_quick_chat(self) -> None:
        from initrunner.tui.screens.run import QuickChatLoadingScreen

        self.push_screen(QuickChatLoadingScreen())

    def action_audit(self) -> None:
        from initrunner.tui.screens.audit import AuditScreen

        self.push_screen(AuditScreen())
