"""RolesScreen — home screen listing discovered roles."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static

from initrunner.agent.schema.role import RoleDefinition
from initrunner.tui.screens.base import BaseScreen, FilterableScreen
from initrunner.tui.services import DiscoveredRole

if TYPE_CHECKING:
    from textual.app import ComposeResult


class RolesScreen(FilterableScreen):
    """Home screen: discover and list initrunner role files."""

    SUB_TITLE = "Roles"

    BINDINGS = [
        *FilterableScreen.BINDINGS,
        Binding("enter", "open_role", "Open", show=True, priority=True),
        Binding("ctrl+r", "fast_run", "Fast Run", show=True),
        Binding("n", "new_role", "New Role", show=True),
        Binding("c", "quick_chat", "Quick Chat", show=True),
        Binding("s", "sense", "Sense", show=True),
    ]

    def __init__(self, *, role_dir: Path | None = None) -> None:
        super().__init__()
        self._role_dir = role_dir
        self._roles: dict[str, DiscoveredRole] = {}  # row_key -> DiscoveredRole
        self._filter_text = ""

    def compose_content(self) -> ComposeResult:
        table = DataTable(id="roles-table")
        table.cursor_type = "row"
        table.add_columns("Status", "Name", "Description", "Model", "Features")
        yield table
        yield Static(self._empty_state_message(), id="empty-state")
        yield Input(placeholder="Filter roles...", id="filter-bar")

    @staticmethod
    def _empty_state_message() -> str:
        from initrunner.cli.setup_cmd import needs_setup

        if needs_setup():
            return (
                "No roles found and InitRunner is not configured.\n"
                "Exit and run [bold]initrunner setup[/bold] to get started, "
                "or press [bold]n[/bold] to create a role manually."
            )
        return (
            "No roles found.\nPress [bold]n[/bold] to create one, "
            "or use [bold]--role-dir[/bold] to specify a directory."
        )

    def on_mount(self) -> None:
        super().on_mount()
        self._load_roles()

    def _scan_dirs(self) -> list[Path]:
        from initrunner.services.discovery import get_default_role_dirs

        return get_default_role_dirs(self._role_dir)

    def _load_roles(self) -> None:
        self.run_worker(self._discover_roles_worker(), exclusive=True, group="discover")

    @staticmethod
    def _display_name(path: Path, role_name: str) -> str:
        """Extract display name, handling namespaced filenames (owner__repo__name.yaml)."""
        stem = path.stem
        parts = stem.split("__")
        if len(parts) == 3:
            return role_name
        return role_name

    @staticmethod
    def _disambiguate_names(
        roles_list: list[tuple[str, str, DiscoveredRole | None]],
    ) -> dict[int, str]:
        """Return index->display_name map, disambiguating collisions.

        roles_list items: (display_name, path_stem, discovered_role)
        """
        from collections import Counter

        name_counts = Counter(name for name, _, _ in roles_list)
        result: dict[int, str] = {}
        for i, (name, stem, _) in enumerate(roles_list):
            if name_counts[name] > 1:
                # Disambiguate: extract owner from namespaced filename
                parts = stem.split("__")
                if len(parts) == 3:
                    result[i] = f"{name} ({parts[0]})"
                else:
                    result[i] = f"{name} ({stem})"
            else:
                result[i] = name
        return result

    async def _discover_roles_worker(self) -> None:
        from initrunner.tui.services import ServiceBridge

        table = self.query_one("#roles-table", DataTable)
        empty_state = self.query_one("#empty-state", Static)
        table.clear()
        self._roles.clear()

        self.notify("Scanning...", severity="information")

        dirs = self._scan_dirs()
        results = await ServiceBridge.discover_roles(dirs)

        # Build list for disambiguation
        roles_info: list[tuple[str, str, DiscoveredRole | None]] = []
        for dr in results:
            if self._filter_text and self._filter_text.lower() not in str(dr.path).lower():
                if dr.role and self._filter_text.lower() not in dr.role.metadata.name.lower():
                    continue
            if dr.role is not None:
                display = self._display_name(dr.path, dr.role.metadata.name)
            else:
                display = dr.path.stem
            roles_info.append((display, dr.path.stem, dr))

        display_names = self._disambiguate_names(roles_info)

        for i, (_, _, dr) in enumerate(roles_info):
            assert dr is not None
            name = display_names[i]

            if dr.role is not None:
                role = dr.role
                status = "[bold green]VALID[/]"
                desc = role.metadata.description or ""
                model = role.spec.model.to_model_string()
                features = self._build_features(role)
            else:
                status = "[bold red]ERROR[/]"
                desc = dr.error or "Invalid"
                model = "-"
                features = "-"

            row_key = table.add_row(status, name, desc, model, features)
            self._roles[str(row_key)] = dr

        # Toggle empty state visibility
        if table.row_count == 0:
            table.display = False
            empty_state.display = True
        else:
            table.display = True
            empty_state.display = False

    @staticmethod
    def _build_features(role: RoleDefinition) -> str:
        """Build compact features string like '2T 1G I M'."""
        parts: list[str] = []
        if role.spec.tools:
            parts.append(f"{len(role.spec.tools)}T")
        if role.spec.triggers:
            parts.append(f"{len(role.spec.triggers)}G")
        if role.spec.ingest:
            parts.append("I")
        if role.spec.memory:
            parts.append("M")
        return " ".join(parts) if parts else "-"

    def _get_selected_role(self):
        table = self.query_one("#roles-table", DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return self._roles.get(str(row_key))

    def action_open_role(self) -> None:
        dr = self._get_selected_role()
        if dr is None:
            return
        if dr.role is None:
            self.notify(f"Cannot open invalid role: {dr.error}", severity="error", markup=False)
            return
        from initrunner.tui.screens.detail import RoleDetailScreen

        self.app.push_screen(RoleDetailScreen(role_path=dr.path, role=dr.role))

    def action_fast_run(self) -> None:
        dr = self._get_selected_role()
        if dr is None:
            return
        if dr.role is None:
            self.notify(f"Cannot run invalid role: {dr.error}", severity="error", markup=False)
            return
        from initrunner.tui.screens.run import RunScreen

        self.app.push_screen(RunScreen(role_path=dr.path, role=dr.role))

    def action_new_role(self) -> None:
        from initrunner.tui.screens.roles import TemplatePickerModal

        self.app.push_screen(TemplatePickerModal(), callback=self._on_template_created)

    def _on_template_created(self, result: str | None) -> None:
        if result:
            self.notify(f"Created: {result}")
            self._load_roles()

    def _apply_filter(self, value: str) -> None:
        self._filter_text = value
        self._load_roles()

    def _clear_filter(self) -> None:
        self._filter_text = ""
        self._load_roles()

    def action_quick_chat(self) -> None:
        self.app.action_quick_chat()  # type: ignore[possibly-missing-attribute]

    def action_sense(self) -> None:
        self.app.push_screen(SenseModal(role_dir=self._role_dir), callback=self._on_sense_result)

    def _on_sense_result(self, result: tuple[Path, RoleDefinition] | None) -> None:
        if result is not None:
            path, role = result
            from initrunner.tui.screens.run import RunScreen

            self.app.push_screen(RunScreen(role_path=path, role=role))

    def action_refresh(self) -> None:
        self._load_roles()


class SenseModal(ModalScreen[tuple[Path, RoleDefinition] | None]):
    """Enter a prompt to auto-select the best role."""

    BINDINGS = [Binding("escape", "cancel", "Close", show=True)]

    DEFAULT_CSS = """
    SenseModal {
        align: center middle;
    }
    SenseModal > #sense-container {
        width: 80;
        height: 20;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    SenseModal > #sense-container > #sense-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    """

    def __init__(self, *, role_dir: Path | None = None) -> None:
        super().__init__()
        self._role_dir = role_dir

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical
        from textual.widgets import Button

        with Vertical(id="sense-container"):
            yield Static("Sense — Find Best Role", id="sense-title")
            yield Input(placeholder="Describe your task...", id="sense-input")
            yield Button("Find Role", variant="primary", id="sense-submit")
            yield Static("", id="sense-result")

    def on_button_pressed(self, event) -> None:
        if event.button.id == "sense-submit":
            prompt = self.query_one("#sense-input", Input).value.strip()
            if not prompt:
                self.notify("Enter a task description", severity="warning")
                return
            self.run_worker(self._run_sense(prompt))
        elif event.button.id == "sense-use":
            if hasattr(self, "_sense_path") and hasattr(self, "_sense_role"):
                self.dismiss((self._sense_path, self._sense_role))

    def on_input_submitted(self, event) -> None:
        if isinstance(event, Input.Submitted) and event.input.id == "sense-input":
            prompt = event.value.strip()
            if prompt:
                self.run_worker(self._run_sense(prompt))

    async def _run_sense(self, prompt: str) -> None:
        from textual.widgets import Button

        result_area = self.query_one("#sense-result", Static)
        result_area.update("Sensing...")

        from initrunner.tui.services import ServiceBridge

        try:
            sr = await ServiceBridge.sense_role(prompt, self._role_dir)
        except Exception as e:
            result_area.update(f"Error: {e}")
            return

        # Load the full role
        from initrunner.tui.services import ServiceBridge as SB

        try:
            dr = await SB.validate_role(sr.candidate.path)
        except Exception:
            result_area.update("Failed to load matched role")
            return

        if dr.role is None:
            result_area.update(f"Matched role is invalid: {dr.error}")
            return

        self._sense_path = sr.candidate.path
        self._sense_role = dr.role

        result_area.update(
            f"[bold]{sr.candidate.name}[/bold] "
            f"({sr.method}, score: {sr.top_score:.2f})\n"
            f"{sr.candidate.description[:120]}"
        )

        # Add "Use" button
        container = self.query_one("#sense-container")
        existing_use = container.query("#sense-use")
        if not existing_use:
            container.mount(Button("Use this role", variant="success", id="sense-use"))

    def action_cancel(self) -> None:
        self.dismiss(None)


class YamlViewerModal(BaseScreen):
    """Read-only modal showing role YAML content."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=True),
    ]

    def __init__(self, content: str, *, title: str = "YAML") -> None:
        super().__init__()
        self._content = content
        self._title = title

    def compose_content(self) -> ComposeResult:
        from textual.containers import VerticalScroll

        with VerticalScroll(id="yaml-modal"):
            yield Static(self._content, markup=False)

    def on_mount(self) -> None:
        self.sub_title = self._title


class TemplatePickerModal(BaseScreen):
    """Modal to scaffold a new role from a template."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def compose_content(self) -> ComposeResult:
        from textual.containers import Vertical
        from textual.widgets import Button, Label, Select

        with Vertical(id="confirm-modal"):
            yield Label("Create New Role")
            yield Input(placeholder="Agent name", id="role-name", value="my-agent")
            yield Select(
                [
                    ("basic", "basic"),
                    ("rag", "rag"),
                    ("daemon", "daemon"),
                    ("memory", "memory"),
                    ("ollama", "ollama"),
                ],
                id="template-select",
                value="basic",
            )
            yield Static("")
            yield Button("Create", variant="primary", id="create-btn")

    def on_button_pressed(self, event) -> None:
        if event.button.id == "create-btn":
            from textual.widgets import Select

            name_input = self.query_one("#role-name", Input)
            template_select = self.query_one("#template-select", Select)
            name = name_input.value.strip() or "my-agent"
            template = str(template_select.value)
            self.run_worker(self._create_role(name, template))

    async def _create_role(self, name: str, template: str) -> None:
        import asyncio

        output_path = Path.cwd() / f"{name}.yaml"
        if output_path.exists():
            self.notify(f"{output_path} already exists", severity="error")
            return

        from initrunner.templates import TEMPLATES, template_basic

        builder = TEMPLATES.get(template, template_basic)
        provider = "ollama" if template == "ollama" else "openai"
        content = builder(name, provider)

        await asyncio.to_thread(output_path.write_text, content)
        self.dismiss(str(output_path))

    def action_cancel(self) -> None:
        self.dismiss(None)
