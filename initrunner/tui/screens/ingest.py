"""IngestScreen — manage document ingestion for a role."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.widgets import DataTable, ProgressBar, Static

from initrunner.tui.screens.base import RoleScreen

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from initrunner.agent.schema import RoleDefinition


class IngestScreen(RoleScreen):
    """View ingestion sources and run ingestion pipeline."""

    BINDINGS = [
        *RoleScreen.BINDINGS,
        Binding("i", "run_ingest", "Ingest", show=True),
        Binding("f", "force_ingest", "Force Re-ingest", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def __init__(self, *, role_path: Path, role: RoleDefinition) -> None:
        super().__init__(role_path=role_path, role=role)
        self._ingesting = False

    def compose_content(self) -> ComposeResult:
        table = DataTable(id="sources-table")
        table.cursor_type = "row"
        table.add_columns("File", "Status", "Chunks")
        yield table
        yield Static("", id="ingest-status")
        yield ProgressBar(id="progress-bar", total=100, show_eta=False)

    def on_mount(self) -> None:
        self.sub_title = f"Ingest: {self._role.metadata.name}"
        self.query_one("#progress-bar", ProgressBar).styles.display = "none"  # type: ignore[invalid-assignment]
        self._load_sources()

    def _load_sources(self) -> None:
        self.run_worker(self._load_sources_worker(), exclusive=True, group="sources")

    async def _load_sources_worker(self) -> None:
        import asyncio

        from initrunner.ingestion.pipeline import resolve_sources

        ingest_cfg = self._role.spec.ingest
        if ingest_cfg is None:
            return

        files, urls = await asyncio.to_thread(
            resolve_sources, ingest_cfg.sources, self._role_path.parent
        )

        table = self.query_one("#sources-table", DataTable)
        table.clear()

        for f in files:
            table.add_row(str(f.relative_to(self._role_path.parent)), "pending", "-")
        for url in urls:
            table.add_row(url, "pending", "-")

        status = self.query_one("#ingest-status", Static)
        total = len(files) + len(urls)
        status.update(f" {total} source(s) matched")

    def action_run_ingest(self) -> None:
        self._start_ingest(force=False)

    def action_force_ingest(self) -> None:
        self._start_ingest(force=True)

    def _start_ingest(self, *, force: bool) -> None:
        if self._ingesting:
            self.notify("Ingestion already in progress", severity="warning")
            return
        self._ingesting = True
        self.run_worker(self._ingest_worker(force=force), exclusive=True, group="ingest")

    async def _ingest_worker(self, *, force: bool) -> None:
        import asyncio

        from initrunner.ingestion.pipeline import FileStatus, resolve_sources

        ingest_cfg = self._role.spec.ingest
        if ingest_cfg is None:
            self._ingesting = False
            return

        files, urls = await asyncio.to_thread(
            resolve_sources, ingest_cfg.sources, self._role_path.parent
        )
        total = len(files) + len(urls)
        if total == 0:
            self.notify("No sources matched patterns", severity="warning")
            self._ingesting = False
            return

        progress_bar = self.query_one("#progress-bar", ProgressBar)
        progress_bar.styles.display = "block"
        progress_bar.update(total=total, progress=0)

        status = self.query_one("#ingest-status", Static)
        status.update(f" Ingesting {total} file(s)...")

        processed = 0

        def on_progress(path: Path, file_status: FileStatus) -> None:
            nonlocal processed
            processed += 1

            def _update():
                progress_bar.update(progress=processed)
                status.update(f" [{processed}/{total}] {path.name}")

            self.app.call_from_thread(_update)

        try:
            from initrunner.tui.services import ServiceBridge

            stats = await ServiceBridge.run_ingest(
                self._role,
                self._role_path,
                force=force,
                progress_callback=on_progress,
            )

            parts = []
            if stats and stats.new:
                parts.append(f"New: {stats.new}")
            if stats and stats.updated:
                parts.append(f"Updated: {stats.updated}")
            if stats and stats.skipped:
                parts.append(f"Skipped: {stats.skipped}")
            if stats and stats.errored:
                parts.append(f"Errors: {stats.errored}")
            chunks = stats.total_chunks if stats else 0

            status.update(f" Done. {chunks} chunks stored. {' | '.join(parts)}")
            self.notify("Ingestion complete")
        except Exception as e:
            status.update(f" Error: {e}")
            self.notify(f"Ingestion failed: {e}", severity="error")
        finally:
            self._ingesting = False
            progress_bar.styles.display = "none"  # type: ignore[invalid-assignment]

    def action_refresh(self) -> None:
        self._load_sources()
