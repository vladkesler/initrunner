"""Scrollable chat message display widget."""

from __future__ import annotations

from textual.containers import ScrollableContainer
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Markdown, Static

from initrunner.tui.theme import COLOR_PRIMARY, COLOR_SUCCESS

_TOKEN_FLUSH_INTERVAL = 0.05  # 50ms
_TOKEN_FLUSH_COUNT = 10

_MAX_CHAT_MESSAGES = 200
_PRUNE_KEEP_COUNT = 150
_MAX_STREAM_BUFFER = 500_000  # ~500 KB cap on streaming buffer

KAOMOJI = [
    "(￣▽￣)",
    "(^_^)",
    "(≥ᴗ≤)",
    "(≧▽≦)",
    "(◕‿◕)",
    "(╥﹏╥)",  # noqa: RUF001
    "(ง •̀_•́)ง",
    "¯\\_(ツ)_/¯",
    "( ͡° ͜ʖ ͡°)",
    "(⚆_⚆)",
    "(❤‿❤)",
    "(¬‿¬)",
    "(ಠ_ಠ)",
    "(ᵔ⩊ᵔ)",
]


def _avatar_for_role(name: str) -> str:
    return KAOMOJI[hash(name) % len(KAOMOJI)]


class ChatMessage(Widget):
    """A single chat message (user or agent)."""

    DEFAULT_CSS = """
    ChatMessage {
        height: auto;
        margin: 1 0 0 0;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        content: str,
        role: str = "agent",
        *,
        is_error: bool = False,
        role_name: str | None = None,
    ) -> None:
        super().__init__()
        self.content = content
        self.role = role
        self.is_error = is_error
        self.role_name = role_name
        if role == "user":
            self.add_class("user-message")
        elif is_error:
            self.add_class("error-message")
        else:
            self.add_class("agent-message")

    def compose(self):
        if self.role == "user":
            yield Static(f"[bold {COLOR_PRIMARY}]you:[/]", classes="msg-role")
        elif self.role_name:
            avatar = _avatar_for_role(self.role_name)
            yield Static(f"[bold {COLOR_SUCCESS}]{avatar} agent:[/]", classes="msg-role")
        else:
            yield Static(f"[bold {COLOR_SUCCESS}]agent:[/]", classes="msg-role")
        if self.role == "user" or self.is_error:
            yield Static(self.content)
        else:
            yield Markdown(self.content)


class StreamingMessage(Widget):
    """Agent message that accumulates streamed tokens."""

    DEFAULT_CSS = """
    StreamingMessage {
        height: auto;
        margin: 1 0 0 0;
        padding: 0 1;
    }
    """

    text = reactive("", layout=True)

    def __init__(self, *, role_name: str | None = None) -> None:
        super().__init__()
        self._buffer = ""
        self._pending_tokens = 0
        self._flush_timer = None
        self.role_name = role_name
        self.add_class("agent-message")

    def compose(self):
        if self.role_name:
            avatar = _avatar_for_role(self.role_name)
            yield Static(f"[bold {COLOR_SUCCESS}]{avatar} agent:[/]", classes="msg-role")
        else:
            yield Static(f"[bold {COLOR_SUCCESS}]agent:[/]", classes="msg-role")
        yield Markdown("", id="stream-content")

    def append_token(self, token: str) -> None:
        self._buffer += token  # amortized O(1) when refcount == 1
        if len(self._buffer) > _MAX_STREAM_BUFFER:
            self._buffer = "[Content truncated]\n\n" + self._buffer[-_MAX_STREAM_BUFFER:]
        self._pending_tokens += 1
        if self._pending_tokens >= _TOKEN_FLUSH_COUNT:
            self._flush()
        elif self._flush_timer is None:
            self._flush_timer = self.set_timer(_TOKEN_FLUSH_INTERVAL, self._flush)

    def _flush(self) -> None:
        if self._flush_timer is not None:
            self._flush_timer.stop()
            self._flush_timer = None
        self._pending_tokens = 0
        self.text = self._buffer

    def watch_text(self, value: str) -> None:
        try:
            md = self.query_one("#stream-content", Markdown)
            md.update(value or " ")
        except Exception:
            # Race during mount/removal — safe to ignore
            pass

    def get_text(self) -> str:
        self._flush()
        return self._buffer


class ThinkingIndicator(Static):
    """Shown while the agent is processing."""

    DEFAULT_CSS = """
    ThinkingIndicator {
        height: auto;
        margin: 1 0 0 0;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__("Thinking...")
        self.add_class("thinking-indicator")


class ChatView(ScrollableContainer):
    """Container that holds chat messages and auto-scrolls."""

    DEFAULT_CSS = """
    ChatView {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }
    """

    def _prune_old_messages(self) -> None:
        """Remove oldest ChatMessage widgets when count exceeds threshold."""
        messages = list(self.query(ChatMessage))
        if len(messages) > _MAX_CHAT_MESSAGES:
            for msg in messages[: len(messages) - _PRUNE_KEEP_COUNT]:
                msg.remove()

    def add_user_message(self, text: str) -> None:
        msg = ChatMessage(text, role="user")
        self.mount(msg)
        self.scroll_end(animate=False)
        self._prune_old_messages()

    def add_agent_message(self, text: str, *, role_name: str | None = None) -> None:
        msg = ChatMessage(text, role="agent", role_name=role_name)
        self.mount(msg)
        self.scroll_end(animate=False)
        self._prune_old_messages()

    def add_error_message(self, text: str, *, role_name: str | None = None) -> None:
        msg = ChatMessage(text, role="agent", is_error=True, role_name=role_name)
        self.mount(msg)
        self.scroll_end(animate=False)
        self._prune_old_messages()

    def add_thinking(self) -> ThinkingIndicator:
        indicator = ThinkingIndicator()
        self.mount(indicator)
        self.scroll_end(animate=False)
        return indicator

    def start_streaming(self, *, role_name: str | None = None) -> StreamingMessage:
        msg = StreamingMessage(role_name=role_name)
        self.mount(msg)
        self.scroll_end(animate=False)
        return msg

    def finalize_streaming(
        self, streaming_msg: StreamingMessage, *, role_name: str | None = None
    ) -> None:
        """Replace a StreamingMessage with a static ChatMessage."""
        final = ChatMessage(streaming_msg.get_text(), role="agent", role_name=role_name)
        streaming_msg.replace_with(final)  # type: ignore[unresolved-attribute]
        self.scroll_end(animate=False)
        self._prune_old_messages()

    def get_last_agent_content(self) -> str | None:
        """Return the content of the last agent message, or None."""
        messages = [m for m in self.query(ChatMessage) if m.role == "agent"]
        return messages[-1].content if messages else None

    def clear_messages(self) -> None:
        """Remove all chat messages, streaming messages, and thinking indicators."""
        for child in list(self.query(ChatMessage)):
            child.remove()
        for child in list(self.query(StreamingMessage)):
            child.remove()
        for child in list(self.query(ThinkingIndicator)):
            child.remove()

    def replay_messages(self, messages: list, role_name: str | None = None) -> None:
        """Replay a list of ModelMessage objects as chat bubbles."""
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            TextPart,
            UserPromptPart,
        )

        from initrunner.agent.prompt import render_content_as_text

        for msg in messages:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart):
                        if isinstance(part.content, str):
                            self.add_user_message(part.content)
                        elif isinstance(part.content, list):
                            text_parts = [render_content_as_text(item) for item in part.content]
                            self.add_user_message(" ".join(text_parts))
                        else:
                            self.add_user_message(str(part.content))
            elif isinstance(msg, ModelResponse):
                for part in msg.parts:
                    if isinstance(part, TextPart):
                        self.add_agent_message(part.content, role_name=role_name)
