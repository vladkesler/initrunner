"""Multi-service compose orchestrator."""

from __future__ import annotations

import queue
import threading
from pathlib import Path

from pydantic_ai import Agent
from rich.console import Console
from rich.table import Table

from initrunner.agent.executor import execute_run
from initrunner.agent.loader import _load_dotenv, build_agent, load_and_build, load_role
from initrunner.agent.schema.memory import MemoryConfig
from initrunner.agent.schema.role import RoleDefinition
from initrunner.audit.logger import AuditLogger
from initrunner.compose.delegate_sink import DelegateEvent, DelegateSink
from initrunner.compose.schema import ComposeDefinition, ComposeServiceConfig
from initrunner.sinks.base import SinkBase
from initrunner.sinks.dispatcher import SinkDispatcher, build_sink
from initrunner.triggers.base import TriggerEvent
from initrunner.triggers.dispatcher import TriggerDispatcher

console = Console()


def apply_shared_memory(role: RoleDefinition, store_path: str, max_memories: int = 1000) -> None:
    """Patch a role's memory config to point at a shared store.

    If the role already has memory configured, override ``store_path`` and
    ``max_memories``.  Otherwise inject a new ``MemoryConfig``.
    """
    if role.spec.memory is not None:
        role.spec.memory = role.spec.memory.model_copy(
            update={"store_path": store_path, "max_memories": max_memories}
        )
    else:
        role.spec.memory = MemoryConfig(store_path=store_path, max_memories=max_memories)


class ComposeService:
    """Wraps a single service within a compose orchestration."""

    def __init__(
        self,
        name: str,
        role: RoleDefinition,
        agent: Agent,
        config: ComposeServiceConfig,
        inbox: queue.Queue[DelegateEvent],
        *,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.name = name
        self.role = role
        self.agent = agent
        self.config = config
        self.inbox = inbox
        self.audit_logger = audit_logger

        self._sink_dispatcher = SinkDispatcher([], role)
        self._trigger_dispatcher: TriggerDispatcher | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._counter_lock = threading.Lock()
        self._execution_lock = threading.Lock()
        self._run_count = 0
        self._error_count = 0

    def add_sink(self, sink: SinkBase) -> None:
        self._sink_dispatcher.add_sink(sink)

    def set_trigger_dispatcher(self, dispatcher: TriggerDispatcher) -> None:
        self._trigger_dispatcher = dispatcher

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def run_count(self) -> int:
        with self._counter_lock:
            return self._run_count

    @property
    def error_count(self) -> int:
        with self._counter_lock:
            return self._error_count

    def _prune_memory_sessions(self) -> None:
        """Prune stale memory sessions, matching run_daemon behaviour."""
        from initrunner.stores.factory import open_memory_store

        mem_cfg = self.role.spec.memory
        if mem_cfg is None:
            return
        with open_memory_store(mem_cfg, self.role.metadata.name, require_exists=False) as store:
            if store is not None:
                store.prune_sessions(self.role.metadata.name, mem_cfg.max_sessions)

    def _handle_prompt(
        self,
        prompt: str,
        *,
        trigger_type: str | None = None,
        trigger_metadata: dict[str, str] | None = None,
    ) -> None:
        """Execute a prompt and dispatch results to sinks."""
        with self._execution_lock:
            with self._counter_lock:
                self._run_count += 1

            from initrunner.observability import extract_trace_context

            parent_ctx = extract_trace_context(trigger_metadata or {})
            ctx_token = None
            if parent_ctx is not None:
                from opentelemetry import context

                ctx_token = context.attach(parent_ctx)

            try:
                result, _ = execute_run(
                    self.agent,
                    self.role,
                    prompt,
                    audit_logger=self.audit_logger,
                    trigger_type=trigger_type,
                    trigger_metadata=trigger_metadata or {},
                )
            finally:
                if ctx_token is not None:
                    from opentelemetry import context

                    context.detach(ctx_token)

            if not result.success:
                with self._counter_lock:
                    self._error_count += 1

            # Prune stale sessions (same as run_daemon)
            if self.role.spec.memory is not None:
                self._prune_memory_sessions()

            self._sink_dispatcher.dispatch(
                result,
                prompt,
                trigger_type=trigger_type or "delegate",
                trigger_metadata=trigger_metadata,
            )

    def _on_trigger(self, event: TriggerEvent) -> None:
        """Callback for trigger-driven execution."""
        console.print(
            f"[dim][{self.name}] Trigger ({event.trigger_type}):[/dim] {event.prompt[:80]}"
        )
        self._handle_prompt(
            event.prompt,
            trigger_type=event.trigger_type,
            trigger_metadata=event.metadata or {},
        )

    def _service_run(self) -> None:
        """Main service loop: start triggers, poll inbox."""
        if self._trigger_dispatcher is not None:
            self._trigger_dispatcher.start_all()

        try:
            while not self._stop_event.is_set():
                try:
                    event = self.inbox.get(timeout=0.5)
                except queue.Empty:
                    continue

                console.print(
                    f"[dim][{self.name}] Delegate from {event.source_service}:[/dim] "
                    f"{event.prompt[:80]}"
                )
                self._handle_prompt(
                    event.prompt,
                    trigger_type="delegate",
                    trigger_metadata=event.metadata,
                )
        finally:
            if self._trigger_dispatcher is not None:
                self._trigger_dispatcher.stop_all()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._service_run, daemon=True, name=f"compose-{self.name}"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


class ComposeOrchestrator:
    """Manages the lifecycle of all compose services."""

    def __init__(
        self,
        compose: ComposeDefinition,
        base_dir: Path,
        *,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self._compose = compose
        self._base_dir = base_dir
        self._audit_logger = audit_logger
        self._services: dict[str, ComposeService] = {}
        self._failed_services: dict[str, str] = {}
        self._delegate_sinks: list[DelegateSink] = []
        self._health_monitor = None

    @property
    def services(self) -> dict[str, ComposeService]:
        return dict(self._services)

    def _build_services(self) -> None:
        """Load roles and create ComposeService instances."""
        shared_mem = self._compose.spec.shared_memory
        shared_path: str | None = None
        if shared_mem.enabled:
            from initrunner.stores.base import DEFAULT_MEMORY_DIR

            shared_path = shared_mem.store_path or str(
                DEFAULT_MEMORY_DIR / f"{self._compose.metadata.name}-shared.db"
            )

        for name, config in self._compose.spec.services.items():
            try:
                role_path = self._base_dir / config.role

                if shared_path:
                    _load_dotenv(role_path.parent)
                    role = load_role(role_path)
                    apply_shared_memory(role, shared_path, shared_mem.max_memories)
                    agent = build_agent(role, role_dir=role_path.parent)
                else:
                    role, agent = load_and_build(role_path)

                inbox: queue.Queue[DelegateEvent] = queue.Queue(
                    maxsize=config.sink.queue_size if config.sink else 100
                )

                service = ComposeService(
                    name=name,
                    role=role,
                    agent=agent,
                    config=config,
                    inbox=inbox,
                    audit_logger=self._audit_logger,
                )

                # Build triggers from role definition
                if role.spec.triggers:
                    dispatcher = TriggerDispatcher(role.spec.triggers, service._on_trigger)
                    service.set_trigger_dispatcher(dispatcher)

                # Build role sinks: always when no compose sink (daemon parity),
                # or when delegate sink explicitly keeps existing sinks.
                should_build_role_sinks = (config.sink is None) or (
                    config.sink is not None and config.sink.keep_existing_sinks
                )
                if should_build_role_sinks and role.spec.sinks:
                    role_dir = role_path.parent
                    for sink_config in role.spec.sinks:
                        sink = build_sink(sink_config, role_dir)
                        if sink:
                            service.add_sink(sink)

                self._services[name] = service
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                self._failed_services[name] = error_msg
                console.print(f"[red]Failed to build service '{name}': {error_msg}[/red]")

        if not self._services:
            failed = ", ".join(self._failed_services.keys())
            raise RuntimeError(f"All services failed to build: {failed}")

    def _wire_delegates(self) -> None:
        """Create DelegateSink instances and inject into services."""
        for name, config in self._compose.spec.services.items():
            if config.sink is None:
                continue
            if name not in self._services:
                continue

            targets = (
                config.sink.target if isinstance(config.sink.target, list) else [config.sink.target]
            )

            for target_name in targets:
                if target_name not in self._services:
                    console.print(
                        f"[yellow]Skipping delegate {name} → {target_name}: "
                        f"target service not available[/yellow]"
                    )
                    continue
                target_service = self._services[target_name]
                delegate = DelegateSink(
                    source_service=name,
                    target_service=target_name,
                    target_queue=target_service.inbox,
                    timeout_seconds=config.sink.timeout_seconds,
                    audit_logger=self._audit_logger,
                    circuit_breaker_threshold=config.sink.circuit_breaker_threshold,
                    circuit_breaker_reset_seconds=config.sink.circuit_breaker_reset_seconds,
                )
                self._services[name].add_sink(delegate)
                self._delegate_sinks.append(delegate)

    def _topological_order(self) -> list[list[str]]:
        """Return services in topological tiers based on depends_on."""
        from initrunner._graph import topological_tiers

        nodes = set(self._services.keys())
        edges = {
            name: [dep for dep in config.depends_on if dep in nodes]
            for name, config in self._compose.spec.services.items()
            if name in nodes
        }
        return topological_tiers(nodes, edges)

    def start(self) -> None:
        """Build, wire, and start all services in topological order."""
        self._build_services()
        self._wire_delegates()

        # Start health monitor if any service has a non-default restart policy
        has_restarts = any(
            svc.config.restart.condition != "none" for svc in self._services.values()
        )
        if has_restarts:
            from initrunner.compose.health import HealthMonitor

            self._health_monitor = HealthMonitor(self._services)
            self._health_monitor.start()

        for tier in self._topological_order():
            for name in tier:
                self._services[name].start()

    def stop(self) -> None:
        """Stop all services in reverse topological order."""
        if self._health_monitor is not None:
            self._health_monitor.stop()

        for tier in reversed(self._topological_order()):
            for name in tier:
                self._services[name].stop()

        # Flush remaining audit events from delegate sinks
        for sink in self._delegate_sinks:
            sink.close()

    def delegate_health(self) -> list[dict]:
        """Return per-sink delegate routing health info."""
        return [
            {
                "source": sink.source_service,
                "target": sink.target_service,
                "dropped_count": sink.dropped_count,
                "filtered_count": sink.filtered_count,
                "circuit_state": sink.circuit_state,
                "consecutive_failures": sink.consecutive_failures,
            }
            for sink in self._delegate_sinks
        ]

    def __enter__(self) -> ComposeOrchestrator:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()


def _print_shutdown_summary(orchestrator: ComposeOrchestrator) -> None:
    """Print a summary table after compose shutdown."""
    svc_table = Table(title="Service Summary")
    svc_table.add_column("Service", style="cyan")
    svc_table.add_column("Status")
    svc_table.add_column("Runs", justify="right")
    svc_table.add_column("Errors", justify="right")

    for name, svc in orchestrator.services.items():
        error_style = "red" if svc.error_count > 0 else ""
        error_cell = (
            f"[{error_style}]{svc.error_count}[/{error_style}]"
            if error_style
            else str(svc.error_count)
        )
        svc_table.add_row(name, "[green]ok[/green]", str(svc.run_count), error_cell)

    for name, reason in orchestrator._failed_services.items():
        svc_table.add_row(name, "[red]failed[/red]", "-", reason)

    console.print(svc_table)

    health = orchestrator.delegate_health()
    if health:
        del_table = Table(title="Delegate Summary")
        del_table.add_column("Source", style="cyan")
        del_table.add_column("Target", style="cyan")
        del_table.add_column("Dropped", justify="right")
        del_table.add_column("Filtered", justify="right")
        del_table.add_column("Circuit", justify="right")

        for info in health:
            dropped_style = "red" if info["dropped_count"] > 0 else ""
            filtered_style = "yellow" if info["filtered_count"] > 0 else ""
            circuit = info["circuit_state"]
            circuit_style = "red" if circuit == "open" else ""
            del_table.add_row(
                info["source"],
                info["target"],
                f"[{dropped_style}]{info['dropped_count']}[/{dropped_style}]"
                if dropped_style
                else str(info["dropped_count"]),
                f"[{filtered_style}]{info['filtered_count']}[/{filtered_style}]"
                if filtered_style
                else str(info["filtered_count"]),
                f"[{circuit_style}]{circuit}[/{circuit_style}]" if circuit_style else circuit,
            )

        console.print(del_table)


def run_compose(
    compose: ComposeDefinition,
    base_dir: Path,
    *,
    audit_logger: AuditLogger | None = None,
) -> None:
    """Run a compose orchestration (foreground, Ctrl+C to stop)."""
    stop = threading.Event()

    orchestrator = ComposeOrchestrator(compose, base_dir, audit_logger=audit_logger)

    console.print(
        f"[bold]Compose[/bold] — {compose.metadata.name} ({len(compose.spec.services)} services)"
    )

    table = Table(title="Services")
    table.add_column("Service", style="cyan")
    table.add_column("Role")
    table.add_column("Sink")
    table.add_column("Depends On")

    for name, config in compose.spec.services.items():
        sink_str = config.sink.summary() if config.sink else "(none)"
        deps_str = ", ".join(config.depends_on) if config.depends_on else "(none)"
        table.add_row(name, config.role, sink_str, deps_str)

    console.print(table)
    console.print("Press Ctrl+C to stop.\n")

    with orchestrator:
        from initrunner._signal import install_shutdown_handler

        def _on_first_signal() -> None:
            console.print("\n[yellow]Shutting down compose...[/yellow]")

        install_shutdown_handler(stop, on_first_signal=_on_first_signal)
        stop.wait(timeout=None)

    _print_shutdown_summary(orchestrator)
