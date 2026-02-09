"""Chat input widget that sends on Enter, inserts newline on Shift+Enter."""

from __future__ import annotations

from textual import events
from textual.widgets import TextArea


class ChatInput(TextArea):
    """TextArea subclass where Shift+Enter inserts a newline.

    Enter itself is intercepted by RunScreen's priority binding
    before it reaches this widget, so it triggers send_message.
    """

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("placeholder", "Type a message...")
        super().__init__(**kwargs)
        self.border_subtitle = "Enter to send | Shift+Enter for newline"

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        await super()._on_key(event)
