"""Modal dialogs for role detail editing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Rule, Static, Switch, TextArea
from textual.widgets.option_list import Option

from initrunner.tui.screens.detail_fields import FieldKind, FieldSpec, convert_values

if TYPE_CHECKING:
    from textual.app import ComposeResult


class SectionPickerModal(ModalScreen[str | None]):
    """Pick which section to edit."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, sections: list[tuple[str, str]], *, title: str = "Edit Section") -> None:
        super().__init__()
        self._sections = sections
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(classes="section-picker"):
            yield Static(f"[bold]{self._title}[/]")
            ol = OptionList(id="section-list")
            for key, label in self._sections:
                ol.add_option(Option(label, id=key))
            yield ol

    def on_mount(self) -> None:
        self.query_one("#section-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class FieldEditModal(ModalScreen[dict[str, str] | None]):
    """Generic field editor modal — renders Input/Switch per FieldSpec."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("ctrl+s", "save", "Save", show=True),
    ]

    def __init__(self, title: str, fields: list[FieldSpec]) -> None:
        super().__init__()
        self._title = title
        self._fields = fields

    def compose(self) -> ComposeResult:
        with Vertical(classes="edit-modal"):
            yield Static(f"[bold]{self._title}[/]")
            yield Rule(classes="edit-modal-rule")
            with VerticalScroll(classes="edit-modal-fields"):
                for spec in self._fields:
                    is_bool = spec.kind == FieldKind.BOOL
                    row_classes = "field-row field-row-bool" if is_bool else "field-row"
                    with Horizontal(classes=row_classes):
                        yield Label(spec.label, classes="field-label")
                        if is_bool:
                            yield Switch(
                                value=spec.value.lower() in ("true", "1", "yes"),
                                id=f"field-{spec.key.replace('.', '-')}",
                            )
                        else:
                            yield Input(
                                value=spec.value,
                                id=f"field-{spec.key.replace('.', '-')}",
                                placeholder=spec.placeholder,
                            )
            with Horizontal(classes="edit-modal-buttons"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Save", variant="primary", id="save-btn")

    def on_mount(self) -> None:
        for spec in self._fields:
            widget = self.query_one(f"#field-{spec.key.replace('.', '-')}")
            if widget.focusable:
                widget.focus()
                break

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._save()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def action_save(self) -> None:
        self._save()

    def _save(self) -> None:
        values: dict[str, str] = {}
        for spec in self._fields:
            widget = self.query_one(f"#field-{spec.key.replace('.', '-')}")
            if spec.kind == FieldKind.BOOL:
                assert isinstance(widget, Switch)
                values[spec.key] = str(widget.value).lower()
            else:
                assert isinstance(widget, Input)
                values[spec.key] = widget.value.strip()
        # Validate types before dismissing
        try:
            convert_values(values, self._fields)
        except ValueError as exc:
            self.notify(f"Invalid value: {exc}", severity="error")
            return
        self.dismiss(values)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TextEditModal(ModalScreen[str | None]):
    """Multi-line text editor modal for system prompt etc."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("ctrl+s", "save", "Save", show=True),
    ]

    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        self._title = title
        self._text = text

    def compose(self) -> ComposeResult:
        with Vertical(classes="edit-modal text-edit-modal"):
            yield Static(f"[bold]{self._title}[/]")
            yield Rule(classes="edit-modal-rule")
            yield TextArea(self._text, id="text-editor", show_line_numbers=False)
            with Horizontal(classes="edit-modal-buttons"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Save", variant="primary", id="save-btn")

    def on_mount(self) -> None:
        self.query_one("#text-editor", TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._save_text()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def action_save(self) -> None:
        self._save_text()

    def _save_text(self) -> None:
        text = self.query_one("#text-editor", TextArea).text
        self.dismiss(text)

    def action_cancel(self) -> None:
        self.dismiss(None)
