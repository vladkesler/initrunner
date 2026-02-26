"""Base screen classes for InitRunner TUI."""

from __future__ import annotations

import abc
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from initrunner.agent.schema.role import RoleDefinition


class BaseScreen(Screen):
    """Base with shared Header/Footer, sub_title, and escape binding."""

    SUB_TITLE: ClassVar[str] = ""
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield from self.compose_content()
        yield Footer()

    @abc.abstractmethod
    def compose_content(self) -> ComposeResult: ...

    def on_mount(self) -> None:
        if self.SUB_TITLE:
            self.sub_title = self.SUB_TITLE


class RoleScreen(BaseScreen):
    """Base for screens that operate on a specific role."""

    def __init__(self, *, role_path: Path | None = None, role: RoleDefinition) -> None:
        super().__init__()
        self._role_path = role_path
        self._role = role


class DataTableScreen(BaseScreen):
    """Base for screens with filterable data tables and refresh."""

    BINDINGS = [
        *BaseScreen.BINDINGS,
        Binding("r", "refresh", "Refresh", show=True),
    ]


class FilterableScreen(DataTableScreen):
    """DataTableScreen with a toggle-able filter bar (``#filter-bar``).

    Subclasses must:
    - Yield an ``Input(id="filter-bar")`` in ``compose_content()``.
    - Implement ``_apply_filter(value)`` to act on the filter text.
    - Implement ``_clear_filter()`` to reset filter state and reload.
    """

    BINDINGS = [
        *DataTableScreen.BINDINGS,
        Binding("slash", "filter", "Filter", show=True),
    ]

    def action_filter(self) -> None:
        from textual.widgets import Input

        filter_bar = self.query_one("#filter-bar", Input)
        filter_bar.toggle_class("visible")
        if filter_bar.has_class("visible"):
            filter_bar.focus()
        else:
            self._clear_filter()

    def on_input_submitted(self, event) -> None:
        from textual.widgets import Input

        if isinstance(event, Input.Submitted) and event.input.id == "filter-bar":
            self._apply_filter(event.value)

    @abc.abstractmethod
    def _apply_filter(self, value: str) -> None:
        """Called when the user submits text in the filter bar."""
        ...

    @abc.abstractmethod
    def _clear_filter(self) -> None:
        """Called when the filter bar is dismissed. Reset state and reload."""
        ...
