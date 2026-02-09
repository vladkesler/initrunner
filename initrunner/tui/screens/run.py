"""RunScreen — streaming chat with an agent."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from initrunner.tui.screens.base import RoleScreen
from initrunner.tui.theme import COLOR_PRIMARY

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from textual.app import ComposeResult

    from initrunner.agent.executor import RunResult
    from initrunner.agent.schema import RoleDefinition
    from initrunner.stores.base import SessionSummary

from initrunner.agent.executor import check_token_budget


class SessionHistoryModal(ModalScreen[str | None]):
    """Modal for browsing and selecting past sessions."""

    BINDINGS = [
        Binding("escape", "cancel", "Close", show=True),
        Binding("enter", "select_session", "Select", show=True),
        Binding("delete", "delete_session", "Delete", show=True),
    ]

    DEFAULT_CSS = """
    SessionHistoryModal {
        align: center middle;
    }
    SessionHistoryModal > #history-container {
        width: 80;
        height: 24;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    SessionHistoryModal > #history-container > #history-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    """

    def __init__(self, summaries: list[SessionSummary], role: RoleDefinition) -> None:
        super().__init__()
        self._summaries = summaries
        self._role = role

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical

        with Vertical(id="history-container"):
            yield Static("Session History", id="history-title")
            table = DataTable(id="history-table")
            table.cursor_type = "row"
            yield table

    def on_mount(self) -> None:
        table = self.query_one("#history-table", DataTable)
        table.add_columns("Preview", "Time", "Msgs")
        for s in self._summaries:
            preview = s.preview[:50] if len(s.preview) > 50 else s.preview
            ts = s.timestamp[:19] if len(s.timestamp) > 19 else s.timestamp
            table.add_row(preview, ts, str(s.message_count), key=s.session_id)
        table.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select_session(self) -> None:
        table = self.query_one("#history-table", DataTable)
        if table.row_count == 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        self.dismiss(str(row_key))

    def action_delete_session(self) -> None:
        table = self.query_one("#history-table", DataTable)
        if table.row_count == 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        session_id = str(row_key)
        self.run_worker(self._delete_session(session_id))

    async def _delete_session(self, session_id: str) -> None:
        from initrunner.tui.services import ServiceBridge

        ok = await ServiceBridge.delete_session(self._role, session_id)
        if ok:
            table = self.query_one("#history-table", DataTable)
            table.remove_row(session_id)
            self.notify("Session deleted")
        else:
            self.notify("Failed to delete session", severity="error")


class RunScreen(RoleScreen):
    """Interactive streaming chat with an agent."""

    BINDINGS = [
        Binding("enter", "send_message", "Send", show=True, priority=True),
        Binding("ctrl+y", "copy_last", "Copy", show=True, priority=True),
        Binding("ctrl+n", "new_conversation", "New", show=True),
        Binding("ctrl+h", "show_history", "History", show=True),
        Binding("ctrl+e", "export_conversation", "Export", show=True),
        Binding("ctrl+d", "exit_chat", "Exit", show=True),
        Binding("ctrl+r", "resume_session", "Resume", show=True),
        Binding("escape", "exit_chat", "Back", show=True),
    ]

    def __init__(self, *, role_path: Path, role: RoleDefinition) -> None:
        super().__init__(role_path=role_path, role=role)
        self._agent: Agent | None = None
        self._message_history: list | None = None
        from initrunner._ids import generate_id

        self._session_id = generate_id()
        self._total_tokens_in = 0
        self._total_tokens_out = 0
        self._cumulative_total_tokens = 0
        self._busy = False

    def compose_content(self) -> ComposeResult:
        from initrunner.tui.widgets.chat_view import ChatView

        yield Static(self._format_status_bar(), id="status-bar")
        yield ChatView(id="chat-container")
        from initrunner.tui.widgets.chat_input import ChatInput

        area = ChatInput(id="input-area")
        area.show_line_numbers = False
        yield area

    def on_mount(self) -> None:
        self.sub_title = f"Run: {self._role.metadata.name}"
        self.run_worker(self._build_agent())
        from initrunner.tui.widgets.chat_input import ChatInput

        self.query_one("#input-area", ChatInput).focus()

    async def _build_agent(self) -> None:
        from initrunner.tui.services import ServiceBridge

        try:
            _, self._agent = await ServiceBridge.build_agent(self._role_path)
            self.notify(f"Agent ready: {self._role.metadata.name}")
        except Exception as e:
            self.notify(f"Failed to build agent: {e}", severity="error")

    def on_text_area_changed(self, event) -> None:
        # Auto-resize text area based on content lines
        area = event.text_area
        lines = area.text.count("\n") + 1
        area.styles.height = min(max(3, lines + 1), 8)

    def action_send_message(self) -> None:
        if self._busy:
            return

        # Check session budget before sending
        session_budget = self._role.spec.guardrails.session_token_budget
        budget_status = check_token_budget(self._cumulative_total_tokens, session_budget)
        if budget_status.exceeded:
            self.notify("Session token budget exhausted", severity="error")
            return

        from initrunner.tui.widgets.chat_input import ChatInput

        area = self.query_one("#input-area", ChatInput)
        text = area.text.strip()
        if not text:
            return
        if self._agent is None:
            self.notify("Agent is still loading — please wait", severity="warning")
            return

        area.clear()
        self._busy = True

        from initrunner.tui.widgets.chat_view import ChatView

        chat = self.query_one("#chat-container", ChatView)
        chat.add_user_message(text)

        # Try streaming first, fall back to non-streaming
        self.run_worker(self._run_streamed(text), exclusive=True, group="agent-run")

    async def _run_streamed(self, prompt: str) -> None:
        from initrunner.tui.services import ServiceBridge
        from initrunner.tui.widgets.chat_view import ChatView

        chat = self.query_one("#chat-container", ChatView)
        streaming_msg = chat.start_streaming(role_name=self._role.metadata.name)

        try:
            # Run streaming in a worker thread
            def _stream_in_thread():
                def on_token(token: str):
                    self.app.call_from_thread(streaming_msg.append_token, token)
                    self.app.call_from_thread(chat.scroll_end, False)

                assert self._agent is not None
                return ServiceBridge.run_agent_streamed(
                    self._agent,
                    self._role,
                    prompt,
                    message_history=self._message_history,
                    on_token=on_token,
                )

            import asyncio

            result, messages = await asyncio.to_thread(_stream_in_thread)

            if result.success:
                chat.finalize_streaming(streaming_msg, role_name=self._role.metadata.name)
                self._after_successful_run(result, messages)
            else:
                # If streaming failed, try non-streamed
                if not streaming_msg.get_text():
                    streaming_msg.remove()
                    await self._run_non_streamed(prompt)
                    return
                # Partial stream succeeded but ended in error
                chat.add_error_message(f"Error: {result.error}", role_name=self._role.metadata.name)

        except Exception:
            # Fall back to non-streamed execution
            streaming_msg.remove()
            await self._run_non_streamed(prompt)
            return
        finally:
            self._busy = False

    async def _run_non_streamed(self, prompt: str) -> None:
        from initrunner.tui.services import ServiceBridge
        from initrunner.tui.widgets.chat_view import ChatView

        chat = self.query_one("#chat-container", ChatView)
        thinking = chat.add_thinking()

        try:
            assert self._agent is not None
            result, messages = await ServiceBridge.run_agent(
                self._agent,
                self._role,
                prompt,
                message_history=self._message_history,
            )

            thinking.remove()

            if result.success:
                chat.add_agent_message(result.output, role_name=self._role.metadata.name)
                self._after_successful_run(result, messages)
            else:
                chat.add_error_message(f"Error: {result.error}", role_name=self._role.metadata.name)
        except Exception as e:
            thinking.remove()
            chat.add_error_message(f"Error: {e}", role_name=self._role.metadata.name)
        finally:
            self._busy = False

    def _format_status_bar(self) -> str:
        bar = (
            f" [bold]{self._role.metadata.name}[/bold]"
            f" [dim]|[/dim] [dim]{self._role.spec.model.to_model_string()}[/dim]"
            f" [dim]|[/dim] [bold {COLOR_PRIMARY}]{self._total_tokens_in}[/bold {COLOR_PRIMARY}] in"
            f" [bold {COLOR_PRIMARY}]{self._total_tokens_out}[/bold {COLOR_PRIMARY}] out"
        )
        session_budget = self._role.spec.guardrails.session_token_budget
        if session_budget is not None:
            pct = int(self._cumulative_total_tokens / session_budget * 100) if session_budget else 0
            if pct >= 100:
                color = "red"
            elif pct >= 80:
                color = "yellow"
            else:
                color = "green"
            bar += (
                f" [dim]|[/dim] [{color}]{self._cumulative_total_tokens:,}"
                f"/{session_budget:,} ({pct}%)[/{color}]"
            )
        return bar

    def _update_status_bar(self) -> None:
        bar = self.query_one("#status-bar", Static)
        bar.update(self._format_status_bar())

    def _save_session(self) -> None:
        if self._role.spec.memory is None or self._message_history is None:
            return
        self.run_worker(self._save_session_worker())

    async def _save_session_worker(self) -> None:
        from initrunner.tui.services import ServiceBridge

        if self._role.spec.memory is None or self._message_history is None:
            return
        ok = await ServiceBridge.save_session(self._role, self._session_id, self._message_history)
        if not ok:
            self.notify(
                "Session save failed — conversation will not be resumable",
                severity="warning",
            )

    def action_resume_session(self) -> None:
        if self._role.spec.memory is None:
            self.notify("No memory config — cannot resume", severity="warning")
            return
        self.run_worker(self._load_session())

    async def _load_session(self) -> None:
        from initrunner.tui.services import ServiceBridge

        if self._role.spec.memory is None:
            return

        max_msgs = self._role.spec.memory.max_resume_messages
        loaded = await ServiceBridge.load_session(self._role, max_messages=max_msgs)
        if loaded:
            self._message_history = loaded
            self.notify(f"Resumed session with {len(loaded)} messages")
        else:
            self.notify("No previous session found", severity="information")

    def _after_successful_run(self, result: RunResult, messages: list) -> None:
        """Update history, token counts, status bar, and save session after a successful run."""
        self._message_history = messages
        self._trim_history()
        self._total_tokens_in += result.tokens_in
        self._total_tokens_out += result.tokens_out
        self._cumulative_total_tokens += result.total_tokens
        self._update_status_bar()
        self._save_session()

        # Warn if approaching budget
        session_budget = self._role.spec.guardrails.session_token_budget
        budget_status = check_token_budget(self._cumulative_total_tokens, session_budget)
        if budget_status.exceeded:
            self.notify("Session token budget exhausted", severity="error")
        elif budget_status.warning:
            assert session_budget is not None
            pct = int(self._cumulative_total_tokens / session_budget * 100)
            self.notify(f"Session budget {pct}% consumed", severity="warning")

    def _trim_history(self) -> None:
        """Apply sliding window to message history."""
        if self._message_history is None:
            return
        from initrunner.agent.history import session_limits, trim_message_history

        _max_resume, max_history = session_limits(self._role)
        self._message_history = trim_message_history(self._message_history, max_history)

    def action_copy_last(self) -> None:
        from initrunner.tui.widgets.chat_view import ChatView

        chat = self.query_one("#chat-container", ChatView)
        text = chat.get_last_agent_content()
        if text:
            self.app.copy_to_clipboard(text)
            self.notify("Copied to clipboard")
        else:
            self.notify("No agent response to copy", severity="warning")

    def action_new_conversation(self) -> None:
        if self._busy:
            return
        from initrunner._ids import generate_id
        from initrunner.tui.widgets.chat_view import ChatView

        self._session_id = generate_id()
        self._message_history = None
        self._total_tokens_in = 0
        self._total_tokens_out = 0
        self._cumulative_total_tokens = 0
        chat = self.query_one("#chat-container", ChatView)
        chat.clear_messages()
        self._update_status_bar()
        self.notify("New conversation started")

    def action_show_history(self) -> None:
        if self._role.spec.memory is None:
            self.notify("No memory config — cannot browse history", severity="warning")
            return
        self.run_worker(self._show_history())

    async def _show_history(self) -> None:
        from initrunner.tui.services import ServiceBridge

        summaries = await ServiceBridge.list_sessions(self._role)
        if not summaries:
            self.notify("No past sessions found", severity="information")
            return
        modal = SessionHistoryModal(summaries, self._role)
        result = await self.app.push_screen_wait(modal)
        if result is not None:
            await self._load_history_session(result)

    async def _load_history_session(self, session_id: str) -> None:
        from initrunner.tui.services import ServiceBridge
        from initrunner.tui.widgets.chat_view import ChatView

        messages = await ServiceBridge.load_session_by_id(self._role, session_id)
        if messages is None:
            self.notify("Session not found or corrupted", severity="error")
            return

        self._session_id = session_id
        self._message_history = messages
        self._total_tokens_in = 0
        self._total_tokens_out = 0
        self._cumulative_total_tokens = 0
        chat = self.query_one("#chat-container", ChatView)
        chat.clear_messages()
        chat.replay_messages(messages, role_name=self._role.metadata.name)
        self._update_status_bar()
        self.notify(f"Loaded session with {len(messages)} messages")

    def action_export_conversation(self) -> None:
        if self._message_history is None or not self._message_history:
            self.notify("No conversation to export", severity="warning")
            return

        from initrunner.services import export_session_markdown_sync

        md = export_session_markdown_sync(self._role, self._message_history)
        filename = f"{self._role.metadata.name}-{self._session_id[:8]}.md"
        path = Path.cwd() / filename
        path.write_text(md, encoding="utf-8")
        self.notify(f"Exported to {filename}")

    def action_exit_chat(self) -> None:
        self.app.pop_screen()
