"""DaemonScreen — start/stop daemon and monitor trigger events."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.widgets import DataTable, RichLog, Rule, Static

from initrunner.audit.logger import AuditLogger
from initrunner.tui.screens.base import RoleScreen
from initrunner.tui.theme import COLOR_PRIMARY, COLOR_SECONDARY, COLOR_SUCCESS

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from textual.app import ComposeResult

    from initrunner.agent.schema.role import RoleDefinition

_MAX_EVENT_LOG_LINES = 5000


class DaemonScreen(RoleScreen):
    """Start/stop a trigger daemon and monitor events live."""

    BINDINGS = [
        Binding("s", "toggle_daemon", "Start/Stop", show=True),
        Binding("c", "clear_log", "Clear Log", show=True),
        Binding("f", "toggle_follow", "Follow", show=True),
        Binding("escape", "go_back", "Back", show=True),
    ]

    def __init__(self, *, role_path: Path, role: RoleDefinition) -> None:
        super().__init__(role_path=role_path, role=role)
        self._agent: Agent | None = None
        self._dispatcher = None
        self._audit_logger: AuditLogger | None = None
        self._running = False
        self._follow = True
        self._fire_counts: dict[str, int] = {}

    def compose_content(self) -> ComposeResult:
        yield Static(
            f" Daemon: {self._role.metadata.name} [dim]|[/dim] [bold red on #2e1a1a] STOPPED [/]",
            id="daemon-status",
        )
        table = DataTable(id="trigger-table")
        table.cursor_type = "row"
        table.add_columns("Type", "Config", "Last Fired", "Count")
        yield table
        yield Rule(id="event-separator")
        yield RichLog(
            id="event-log",
            highlight=True,
            markup=True,
            auto_scroll=True,
            max_lines=_MAX_EVENT_LOG_LINES,
        )

    def on_mount(self) -> None:
        self.sub_title = f"Daemon: {self._role.metadata.name}"
        self._populate_triggers()

    def _populate_triggers(self) -> None:
        table = self.query_one("#trigger-table", DataTable)
        table.clear()

        for trigger_cfg in self._role.spec.triggers:
            ttype = trigger_cfg.type
            summary = trigger_cfg.summary()
            self._fire_counts[ttype] = 0
            table.add_row(ttype, summary, "-", "0")

    def action_toggle_daemon(self) -> None:
        if self._running:
            self._stop_daemon()
        else:
            self.run_worker(self._start_daemon())

    async def _start_daemon(self) -> None:
        from initrunner.tui.services import ServiceBridge

        log = self.query_one("#event-log", RichLog)
        status_bar = self.query_one("#daemon-status", Static)

        try:
            _, self._agent = await ServiceBridge.build_agent(self._role_path)
        except Exception as e:
            log.write(f"[red]Failed to build agent: {e}[/red]")
            return

        self._audit_logger = AuditLogger()

        def on_trigger(event) -> None:
            self._fire_counts[event.trigger_type] = self._fire_counts.get(event.trigger_type, 0) + 1

            def _log_event():
                if not self.is_mounted:
                    return
                badge_colors = {
                    "cron": COLOR_PRIMARY,
                    "file_watch": COLOR_SECONDARY,
                    "webhook": COLOR_SUCCESS,
                    "telegram": "#0088cc",
                    "discord": "#5865F2",
                }
                badge_bg = badge_colors.get(event.trigger_type, COLOR_SECONDARY)
                log.write(
                    f"[dim]{event.timestamp[:19]}[/dim] "
                    f"[bold on {badge_bg}] {event.trigger_type.upper()} [/] "
                    f"{event.prompt[:100]}"
                )
                self._update_trigger_table()

            self.app.call_from_thread(_log_event)

            from initrunner.agent.executor import execute_run

            assert self._agent is not None
            result, _ = execute_run(
                self._agent,
                self._role,
                event.prompt,
                audit_logger=self._audit_logger,
                trigger_type=event.trigger_type,
                trigger_metadata=event.metadata or {},
            )

            def _log_result():
                if not self.is_mounted:
                    return
                if result.success:
                    out = result.output
                    preview = out[:200] + "..." if len(out) > 200 else out
                    log.write(f"  [green]OK[/green] ({result.duration_ms}ms): {preview}")
                else:
                    log.write(f"  [red]FAIL[/red]: {result.error}")

            self.app.call_from_thread(_log_result)

        self._dispatcher = await ServiceBridge.start_triggers(self._role, on_trigger)
        self._running = True

        status_bar.update(
            f" Daemon: {self._role.metadata.name} [dim]|[/dim] "
            f"[bold green on #1a2e1a] RUNNING [/] [dim]|[/dim] "
            f"{self._dispatcher.count} trigger(s)"
        )
        log.write("[green]Daemon started[/green]")

    def _stop_daemon(self) -> None:
        if self._dispatcher is not None:
            self._dispatcher.stop_all()
            self._dispatcher = None

        if self._audit_logger is not None:
            self._audit_logger.close()
            self._audit_logger = None

        self._running = False
        status_bar = self.query_one("#daemon-status", Static)
        status_bar.update(
            f" Daemon: {self._role.metadata.name} [dim]|[/dim] [bold red on #2e1a1a] STOPPED [/]"
        )
        log = self.query_one("#event-log", RichLog)
        log.write("[yellow]Daemon stopped[/yellow]")

    def _update_trigger_table(self) -> None:
        table = self.query_one("#trigger-table", DataTable)
        table.clear()

        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()[:19]

        for trigger_cfg in self._role.spec.triggers:
            ttype = trigger_cfg.type
            summary = trigger_cfg.summary()
            count = self._fire_counts.get(ttype, 0)
            last = now if count > 0 else "-"
            table.add_row(ttype, summary, last, str(count))

    def action_clear_log(self) -> None:
        log = self.query_one("#event-log", RichLog)
        log.clear()

    def action_toggle_follow(self) -> None:
        self._follow = not self._follow
        log = self.query_one("#event-log", RichLog)
        log.auto_scroll = self._follow
        mode = "on" if self._follow else "off"
        self.notify(f"Follow: {mode}")

    def action_go_back(self) -> None:
        if self._running:
            self._stop_daemon()
        self.app.pop_screen()

    def on_unmount(self) -> None:
        if self._running:
            self._stop_daemon()
