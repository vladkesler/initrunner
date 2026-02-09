"""MemoryScreen — browse and manage agent memories."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.widgets import DataTable, Input, Static, TabbedContent, TabPane

from initrunner.tui.screens.base import BaseScreen

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from initrunner.agent.schema import RoleDefinition


class MemoryScreen(BaseScreen):
    """Browse memories and sessions for a role."""

    BINDINGS = [
        *BaseScreen.BINDINGS,
        Binding("x", "clear_memory", "Clear", show=True),
        Binding("e", "export_memories", "Export", show=True),
        Binding("slash", "search", "Search", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def __init__(self, *, role: RoleDefinition) -> None:
        super().__init__()
        self._role = role

    def compose_content(self) -> ComposeResult:
        with TabbedContent():
            with TabPane("Memories", id="tab-memories"):
                table = DataTable(id="memories-table")
                table.cursor_type = "row"
                table.add_columns("ID", "Content", "Category", "Created")
                yield table
            with TabPane("Sessions", id="tab-sessions"):
                yield Static("Session management requires role memory config.", id="sessions-info")
        yield Input(placeholder="Search memories...", id="filter-bar")

    def on_mount(self) -> None:
        self.sub_title = f"Memory: {self._role.metadata.name}"
        self._load_memories()

    def _load_memories(self) -> None:
        self.run_worker(self._load_worker(), exclusive=True, group="memory-load")

    def _populate_memory_table(self, memories: list) -> None:
        """Clear and repopulate the memories table."""
        table = self.query_one("#memories-table", DataTable)
        table.clear()
        for mem in memories:
            preview = mem.content[:80] + "..." if len(mem.content) > 80 else mem.content
            ts = mem.created_at[:19] if len(mem.created_at) > 19 else mem.created_at
            table.add_row(str(mem.id), preview, mem.category, ts)

    async def _load_worker(self) -> None:
        from initrunner.tui.services import ServiceBridge

        memories = await ServiceBridge.list_memories(self._role, limit=200)
        self._populate_memory_table(memories)

    def action_clear_memory(self) -> None:
        self.app.push_screen(  # type: ignore[no-matching-overload]
            ConfirmClearModal(self._role),
            callback=self._on_clear_result,
        )

    def _on_clear_result(self, cleared: bool) -> None:
        if cleared:
            self.notify("Memory cleared")
            self._load_memories()

    def action_export_memories(self) -> None:
        self.run_worker(self._export_worker())

    async def _export_worker(self) -> None:
        import asyncio
        import json
        from pathlib import Path

        from initrunner.tui.services import ServiceBridge

        data = await ServiceBridge.export_memories(self._role)
        output = Path.cwd() / f"{self._role.metadata.name}-memories.json"
        text = json.dumps(data, indent=2)
        await asyncio.to_thread(output.write_text, text)
        self.notify(f"Exported {len(data)} memories to {output}")

    def action_search(self) -> None:
        filter_bar = self.query_one("#filter-bar", Input)
        filter_bar.toggle_class("visible")
        if filter_bar.has_class("visible"):
            filter_bar.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter-bar":
            # Filter is applied via category search
            val = event.value.strip()
            self.run_worker(self._search_worker(val if val else None))

    async def _search_worker(self, category: str | None) -> None:
        from initrunner.tui.services import ServiceBridge

        memories = await ServiceBridge.list_memories(self._role, category=category, limit=200)
        self._populate_memory_table(memories)

    def action_refresh(self) -> None:
        self._load_memories()


class ConfirmClearModal(BaseScreen):
    """Type-to-confirm modal for clearing memory."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, role: RoleDefinition) -> None:
        super().__init__()
        self._role = role

    def compose_content(self) -> ComposeResult:
        from textual.containers import Vertical
        from textual.widgets import Button, Label

        with Vertical(id="confirm-modal"):
            yield Label(
                f"[bold red]Clear all memory for {self._role.metadata.name}?[/bold red]\n\n"
                'Type "delete" to confirm:'
            )
            yield Input(placeholder='Type "delete" to confirm', id="confirm-input")
            yield Button("Cancel", id="cancel-btn")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "confirm-input" and event.value.strip().lower() == "delete":
            self.run_worker(self._clear_worker())

    async def _clear_worker(self) -> None:
        from initrunner.tui.services import ServiceBridge

        await ServiceBridge.clear_memories(self._role)
        self.dismiss(True)

    def on_button_pressed(self, event) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)
