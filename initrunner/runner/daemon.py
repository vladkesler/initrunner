"""Daemon mode runner: triggers fire → agent responds → result logged."""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict

from pydantic_ai import Agent

from initrunner.agent.executor import RunResult, execute_run
from initrunner.agent.schema.role import RoleDefinition
from initrunner.audit.logger import AuditLogger
from initrunner.runner.autonomous import run_autonomous
from initrunner.runner.budget import DaemonTokenTracker
from initrunner.runner.display import _display_daemon_header, _display_result, console
from initrunner.sinks.dispatcher import SinkDispatcher
from initrunner.stores.base import MemoryStoreBase
from initrunner.triggers.base import CONVERSATIONAL_TRIGGER_TYPES, TriggerEvent

_logger = logging.getLogger(__name__)


class _ConversationStore:
    """Thread-safe, LRU-bounded store for per-conversation message histories."""

    def __init__(self, *, max_conversations: int = 200, ttl_seconds: float = 3600) -> None:
        self._max = max_conversations
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._data: OrderedDict[str, tuple[float, list]] = OrderedDict()

    def get(self, key: str | None) -> list | None:
        """Return stored history if not expired, or None."""
        if key is None:
            return None
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            ts, messages = entry
            if time.monotonic() - ts > self._ttl:
                del self._data[key]
                return None
            # Mark as recently used
            self._data.move_to_end(key)
            return messages

    def put(self, key: str | None, messages: list) -> None:
        """Store history with current timestamp, evicting oldest if at capacity."""
        if key is None:
            return
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (time.monotonic(), messages)
            while len(self._data) > self._max:
                self._data.popitem(last=False)


class DaemonRunner:
    """Encapsulates daemon mode state and trigger handling."""

    _MAX_CONCURRENT = 4

    def __init__(
        self,
        agent: Agent,
        role: RoleDefinition,
        *,
        audit_logger: AuditLogger | None = None,
        sink_dispatcher: SinkDispatcher | None = None,
        memory_store: MemoryStoreBase | None = None,
    ) -> None:
        self._agent = agent
        self._role = role
        self._audit_logger = audit_logger
        self._sink_dispatcher = sink_dispatcher
        self._memory_store = memory_store

        self._stop = threading.Event()
        self._in_flight_count = 0
        self._in_flight_cond = threading.Condition()
        self._concurrency_semaphore = threading.Semaphore(self._MAX_CONCURRENT)

        guardrails = role.spec.guardrails
        self._tracker = DaemonTokenTracker(
            lifetime_budget=guardrails.daemon_token_budget,
            daily_budget=guardrails.daemon_daily_token_budget,
        )

        self._schedule_queue = None
        self._scheduling_toolset = None
        self._autonomous_trigger_types: set[str] = set()
        self._conversations = _ConversationStore()

    def run(self) -> None:
        """Start the daemon: set up triggers, handle events, block until stopped."""
        from initrunner.triggers.dispatcher import TriggerDispatcher

        if not self._role.spec.triggers:
            console.print("[red]Error:[/red] No triggers configured in role definition.")
            return

        self._setup_scheduling()

        # Check which triggers want autonomous mode
        for tc in self._role.spec.triggers:
            if getattr(tc, "autonomous", False):
                self._autonomous_trigger_types.add(tc.type)

        dispatcher = TriggerDispatcher(self._role.spec.triggers, self._on_trigger)

        _display_daemon_header(
            self._role,
            self._role.spec.guardrails,
            self._autonomous_trigger_types,
            dispatcher,
        )

        with dispatcher:
            from initrunner._signal import install_shutdown_handler

            install_shutdown_handler(self._stop, on_first_signal=self._on_first_signal)
            # Use a loop with timeout as a safety net: if the signal handler somehow
            # fails to set the stop event, we still get periodic wakeups to check.
            while not self._stop.wait(timeout=30):
                pass

        console.print("Daemon stopped.")

    def _setup_scheduling(self) -> None:
        """Initialize scheduling tools if autonomy is configured."""
        if self._role.spec.autonomy is None:
            return

        from initrunner.triggers.schedule_queue import ScheduleQueue

        autonomy_config = self._role.spec.autonomy

        self._schedule_queue = ScheduleQueue(
            self._on_trigger,
            max_total=autonomy_config.max_scheduled_total,
        )

        from initrunner.agent.tools.scheduling import build_scheduling_toolset

        self._scheduling_toolset = build_scheduling_toolset(autonomy_config, self._schedule_queue)
        console.print("[dim]  Scheduling enabled (in-memory, lost on restart).[/dim]")

    def _on_trigger(self, event: TriggerEvent) -> None:
        """Handle a trigger event with concurrency limiting."""
        if not self._concurrency_semaphore.acquire(blocking=False):
            console.print(
                f"\n[yellow]Max concurrent triggers ({self._MAX_CONCURRENT}) reached — "
                f"skipping trigger ({event.trigger_type})[/yellow]"
            )
            return

        try:
            self._on_trigger_inner(event)
        finally:
            self._concurrency_semaphore.release()

    def _on_trigger_inner(self, event: TriggerEvent) -> None:
        """Process a single trigger event."""
        from initrunner.agent.history import trim_message_history
        from initrunner.agent.schema.autonomy import AutonomyConfig

        allowed, reason = self._tracker.check_before_run()
        if not allowed:
            console.print(f"\n[yellow]Budget exceeded — skipping trigger: {reason}[/yellow]")
            return

        console.print(f"\n[dim]Trigger ({event.trigger_type}):[/dim] {event.prompt[:80]}")

        # Build extra toolsets for this trigger
        extra_ts: list = []
        if self._scheduling_toolset is not None:
            extra_ts.append(self._scheduling_toolset)

        use_autonomous = (
            event.trigger_type in self._autonomous_trigger_types
            or event.trigger_type == "scheduled"
        ) and self._role.spec.autonomy is not None

        if event.trigger_type in CONVERSATIONAL_TRIGGER_TYPES:
            use_autonomous = False

        # Retrieve prior conversation history for messaging triggers
        conv_key = event.conversation_key
        prior_history = self._conversations.get(conv_key) if conv_key else None

        autonomy_config = self._role.spec.autonomy or AutonomyConfig()

        with self._in_flight_cond:
            self._in_flight_count += 1
        try:
            if use_autonomous:
                auto_result = run_autonomous(
                    self._agent,
                    self._role,
                    event.prompt,
                    audit_logger=self._audit_logger,
                    sink_dispatcher=self._sink_dispatcher,
                    memory_store=self._memory_store,
                    extra_toolsets=extra_ts if extra_ts else None,
                    trigger_type=event.trigger_type,
                    trigger_metadata=event.metadata or {},
                    message_history=prior_history,
                )
                self._tracker.record_usage(auto_result.total_tokens)

                # Store updated conversation history
                if conv_key and auto_result.final_messages:
                    trimmed = trim_message_history(
                        auto_result.final_messages,
                        autonomy_config.max_history_messages,
                    )
                    self._conversations.put(conv_key, trimmed)

                # Reply to originating channel (messaging triggers)
                if event.reply_fn is not None:
                    if conv_key is not None:
                        # Conversational: send only the final output
                        reply_text = auto_result.final_output
                    else:
                        # Non-conversational (scheduled, etc.): join all outputs
                        reply_text = "\n\n".join(
                            r.output for r in auto_result.iterations if r.output
                        )
                    if reply_text:
                        try:
                            event.reply_fn(reply_text)
                        except Exception:
                            _logger.warning(
                                "Failed to deliver reply for trigger %s",
                                event.trigger_type,
                                exc_info=True,
                            )
            else:
                result, new_messages = execute_run(
                    self._agent,
                    self._role,
                    event.prompt,
                    audit_logger=self._audit_logger,
                    message_history=prior_history,
                    trigger_type=event.trigger_type,
                    trigger_metadata=event.metadata or {},
                    extra_toolsets=extra_ts if extra_ts else None,
                )
                self._tracker.record_usage(result.total_tokens)

                # Reply first, post-process after
                if event.reply_fn is not None and result.output:
                    try:
                        event.reply_fn(result.output)
                    except Exception:
                        _logger.warning(
                            "Failed to deliver reply for trigger %s",
                            event.trigger_type,
                            exc_info=True,
                        )

                _display_result(result)
                self._dispatch_sink(result, event)
                self._capture_episode(result, event)

                # Store updated conversation history
                if conv_key and new_messages:
                    trimmed = trim_message_history(
                        new_messages,
                        autonomy_config.max_history_messages,
                    )
                    self._conversations.put(conv_key, trimmed)

            self._maybe_prune_sessions()
        finally:
            with self._in_flight_cond:
                self._in_flight_count -= 1
                self._in_flight_cond.notify_all()

    def _capture_episode(self, result: RunResult, event: TriggerEvent) -> None:
        """Capture a daemon run result as an episodic memory."""
        if self._memory_store is None or self._role.spec.memory is None:
            return
        from initrunner.agent.memory_capture import capture_episode

        summary = f"Daemon trigger ({event.trigger_type}): {result.output[:500]}"
        capture_episode(
            self._memory_store,
            self._role,
            summary,
            category="daemon_run",
            trigger_type=event.trigger_type,
        )

    def _dispatch_sink(self, result: RunResult, event: TriggerEvent) -> None:
        """Dispatch a run result to configured sinks."""
        if self._sink_dispatcher is not None:
            self._sink_dispatcher.dispatch(
                result,
                event.prompt,
                trigger_type=event.trigger_type,
                trigger_metadata=event.metadata,
            )

    def _maybe_prune_sessions(self) -> None:
        """Prune old memory sessions if memory is configured."""
        from initrunner.runner import maybe_prune_sessions

        maybe_prune_sessions(self._role, self._memory_store)

    def _on_first_signal(self) -> None:
        """Handle the first shutdown signal."""
        console.print("\n[yellow]Shutting down...[/yellow]")
        with self._in_flight_cond:
            if self._in_flight_count > 0:
                console.print("[dim]  Waiting for in-flight execution to complete...[/dim]")
        try:
            if self._schedule_queue is not None:
                cancelled = self._schedule_queue.cancel_all()
                if cancelled:
                    console.print(f"[dim]  Cancelled {cancelled} pending scheduled task(s).[/dim]")
        except Exception:
            _logger.warning("Error during signal handler cleanup", exc_info=True)


def run_daemon(
    agent: Agent,
    role: RoleDefinition,
    *,
    audit_logger: AuditLogger | None = None,
    sink_dispatcher: SinkDispatcher | None = None,
    memory_store: MemoryStoreBase | None = None,
) -> None:
    """Run in daemon mode: triggers fire → agent responds → result logged."""
    runner = DaemonRunner(
        agent,
        role,
        audit_logger=audit_logger,
        sink_dispatcher=sink_dispatcher,
        memory_store=memory_store,
    )
    runner.run()
