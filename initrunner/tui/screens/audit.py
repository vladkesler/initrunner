"""AuditScreen — browse audit log records."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.widgets import DataTable, Input

from initrunner.tui.screens.base import DataTableScreen, FilterableScreen
from initrunner.tui.theme import COLOR_ERROR, COLOR_PRIMARY, COLOR_SUCCESS

if TYPE_CHECKING:
    from textual.app import ComposeResult


class AuditScreen(FilterableScreen):
    """Browse and inspect audit trail records."""

    SUB_TITLE = "Audit Log"

    BINDINGS = [
        *FilterableScreen.BINDINGS,
        Binding("enter", "view_detail", "Detail", show=True, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._records: dict[str, object] = {}  # row_key -> AuditRecord
        self._filter_agent: str | None = None

    def compose_content(self) -> ComposeResult:
        table = DataTable(id="audit-table")
        table.cursor_type = "row"
        table.add_columns("Timestamp", "Agent", "Run ID", "Model", "Tokens", "Duration", "Status")
        yield table
        yield Input(placeholder="Filter by agent name...", id="filter-bar")

    def on_mount(self) -> None:
        super().on_mount()
        self._load_records()

    def _load_records(self) -> None:
        self.run_worker(self._load_worker(), exclusive=True, group="audit-load")

    async def _load_worker(self) -> None:
        from initrunner.tui.services import ServiceBridge

        records = await ServiceBridge.query_audit(
            agent_name=self._filter_agent,
            limit=100,
        )

        table = self.query_one("#audit-table", DataTable)
        table.clear()
        self._records.clear()

        for rec in records:
            ts = rec.timestamp[:19] if len(rec.timestamp) > 19 else rec.timestamp
            tokens = f"{rec.tokens_in}/{rec.tokens_out}"
            duration = f"{rec.duration_ms}ms"
            status = "[green]OK[/]" if rec.success else "[red]FAIL[/]"
            row_key = table.add_row(
                ts, rec.agent_name, rec.run_id[:8], rec.model, tokens, duration, status
            )
            self._records[str(row_key)] = rec

    def _get_selected_record(self):
        table = self.query_one("#audit-table", DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return self._records.get(str(row_key))

    def action_view_detail(self) -> None:
        rec = self._get_selected_record()
        if rec is None:
            return
        self.app.push_screen(AuditDetailModal(rec))

    def _apply_filter(self, value: str) -> None:
        val = value.strip()
        self._filter_agent = val if val else None
        self._load_records()

    def _clear_filter(self) -> None:
        self._filter_agent = None
        self._load_records()

    def action_refresh(self) -> None:
        self._load_records()


class AuditDetailModal(DataTableScreen):
    """Modal showing full audit record detail."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Close", show=True),
        Binding("q", "app.pop_screen", "Close", show=False),
        Binding("y", "copy_output", "Copy Output", show=True),
    ]

    def __init__(self, record) -> None:
        super().__init__()
        self._record = record

    def compose_content(self) -> ComposeResult:
        from textual.containers import VerticalScroll
        from textual.widgets import Markdown, Rule, Static

        rec = self._record

        status_label = (
            f"[bold {COLOR_SUCCESS}]OK[/]" if rec.success else f"[bold {COLOR_ERROR}]FAILED[/]"
        )
        ts_display = f"[dim]{rec.timestamp}[/dim]"

        with VerticalScroll(id="detail-modal"):
            yield Static(
                f"[bold]Run ID:[/bold] {rec.run_id}\n"
                f"[bold]Agent:[/bold] {rec.agent_name}\n"
                f"[bold]Timestamp:[/bold] {ts_display}\n"
                f"[bold]Model:[/bold] {rec.model} ({rec.provider})\n"
                f"[bold]Tokens:[/bold] {rec.tokens_in} in / {rec.tokens_out} out "
                f"({rec.total_tokens} total)\n"
                f"[bold]Tool Calls:[/bold] {rec.tool_calls}\n"
                f"[bold]Duration:[/bold] {rec.duration_ms}ms\n"
                f"[bold]Status:[/bold] {status_label}"
                + (f"\n[bold]Error:[/bold] [red]{rec.error}[/red]" if rec.error else "")
                + (f"\n[bold]Trigger:[/bold] {rec.trigger_type}" if rec.trigger_type else ""),
            )
            yield Rule()
            yield Static(f"[bold {COLOR_PRIMARY}]User Prompt[/]")
            yield Static(rec.user_prompt, markup=False)
            yield Rule()
            yield Static(f"[bold {COLOR_SUCCESS}]Agent Output[/]")
            yield Markdown(rec.output if rec.output else "(empty)")

    def action_copy_output(self) -> None:
        text = self._record.output or ""
        if text:
            self.app.copy_to_clipboard(text)
            self.notify("Copied to clipboard")
        else:
            self.notify("No output to copy", severity="warning")

    def on_mount(self) -> None:
        self.sub_title = f"Audit: {self._record.run_id[:8]}"
