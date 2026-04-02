"""Multi-service compose orchestrator.

Uses pydantic-graph beta for parallel execution of service delegation
chains.  Each compose service becomes a graph step; fan-out becomes
Fork/Join, routing becomes Decision nodes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai import Agent
from rich.console import Console
from rich.table import Table

from initrunner._log import get_logger
from initrunner.agent.executor import RunResult
from initrunner.agent.loader import (
    _load_dotenv,
    build_agent,
    load_and_build,
    load_role,
    resolve_role_model,
)
from initrunner.agent.schema.memory import MemoryConfig, SemanticMemoryConfig
from initrunner.agent.schema.role import RoleDefinition
from initrunner.audit.logger import AuditLogger
from initrunner.compose.schema import ComposeDefinition, ComposeServiceConfig, SharedDocumentsConfig
from initrunner.sinks.dispatcher import SinkDispatcher, build_sink

console = Console()
logger = get_logger("compose.orchestrator")


def apply_shared_memory(role: RoleDefinition, store_path: str, max_memories: int = 1000) -> None:
    """Patch a role's memory config to point at a shared store.

    If the role already has memory configured, override ``store_path`` and
    ``semantic.max_memories``.  Otherwise inject a new ``MemoryConfig``.
    """
    if role.spec.memory is not None:
        updated_semantic = role.spec.memory.semantic.model_copy(
            update={"max_memories": max_memories}
        )
        role.spec.memory = role.spec.memory.model_copy(
            update={"store_path": store_path, "semantic": updated_semantic}
        )
    else:
        role.spec.memory = MemoryConfig(
            store_path=store_path,
            semantic=SemanticMemoryConfig(max_memories=max_memories),
        )


def apply_shared_documents(
    role: RoleDefinition, cfg: SharedDocumentsConfig, store_path: str
) -> None:
    """Inject a shared document store into *role* so a ``retrieval``
    retrieval tool is registered.
    """
    from initrunner.agent.schema.ingestion import IngestConfig

    if role.spec.ingest is not None:
        role.spec.ingest = role.spec.ingest.model_copy(
            update={
                "store_path": store_path,
                "store_backend": cfg.store_backend,
                "embeddings": cfg.embeddings,
            }
        )
    else:
        role.spec.ingest = IngestConfig(
            sources=[],
            store_path=store_path,
            store_backend=cfg.store_backend,
            embeddings=cfg.embeddings,
        )


@dataclass
class ServiceStepResult:
    """Per-service result from a ``run_once`` execution."""

    service_name: str
    output: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    tool_calls: int = 0
    tool_call_names: list[str] = field(default_factory=list)
    success: bool = True
    error: str | None = None


@dataclass
class ComposeRunResult:
    """Aggregate result from a ``run_once`` execution."""

    output: str
    output_mode: str  # "single" | "multiple" | "none"
    final_service_name: str | None
    compose_run_id: str = ""
    steps: list[ServiceStepResult] = field(default_factory=list)
    entry_messages: list | None = None
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_duration_ms: int = 0
    success: bool = True
    error: str | None = None


class ComposeService:
    """Wraps a single service within a compose orchestration.

    Holds the role definition, PydanticAI agent, and result tracking.
    Graph steps read and write ``_last_result`` / ``_last_messages``.
    """

    def __init__(
        self,
        name: str,
        role: RoleDefinition,
        agent: Agent,
        config: ComposeServiceConfig,
        *,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.name = name
        self.role = role
        self.agent = agent
        self.config = config
        self.audit_logger = audit_logger

        self._sink_dispatcher = SinkDispatcher([], role)
        self._counter_lock = threading.Lock()
        self._run_count = 0
        self._error_count = 0

        # Result tracking (set by graph steps, read by _collect_results)
        self._last_result: RunResult | None = None
        self._last_messages: list | None = None

    @property
    def is_alive(self) -> bool:
        return True

    @property
    def run_count(self) -> int:
        with self._counter_lock:
            return self._run_count

    @property
    def error_count(self) -> int:
        with self._counter_lock:
            return self._error_count

    def add_sink(self, sink) -> None:
        self._sink_dispatcher.add_sink(sink)

    def _prune_memory_sessions(self) -> None:
        """Prune stale memory sessions."""
        from initrunner.stores.factory import open_memory_store

        mem_cfg = self.role.spec.memory
        if mem_cfg is None:
            return
        with open_memory_store(mem_cfg, self.role.metadata.name, require_exists=False) as store:
            if store is not None:
                store.prune_sessions(self.role.metadata.name, mem_cfg.max_sessions)


class ComposeOrchestrator:
    """Manages compose service lifecycle and graph execution.

    One-shot: ``run_once()`` builds a pydantic-graph and runs it
    synchronously.  Daemon: ``start()`` spawns a background thread
    that runs the graph per trigger event.
    """

    def __init__(
        self,
        compose: ComposeDefinition,
        base_dir: Path,
        *,
        audit_logger: AuditLogger | None = None,
        max_agent_workers: int | None = None,
    ) -> None:
        self._compose = compose
        self._base_dir = base_dir
        self._audit_logger = audit_logger
        self._services: dict[str, ComposeService] = {}
        self._failed_services: dict[str, str] = {}

        # Daemon state
        self._shutdown: threading.Event | None = None
        self._daemon_thread: threading.Thread | None = None

    @property
    def services(self) -> dict[str, ComposeService]:
        return dict(self._services)

    # ------------------------------------------------------------------
    # Service building
    # ------------------------------------------------------------------

    def _build_services(self, *, one_shot: bool = False) -> None:
        """Load roles and create ComposeService instances.

        When *one_shot* is True, triggers and non-delegate role sinks are
        suppressed to prevent dashboard runs from firing real webhooks
        or file-write sinks.
        """
        shared_mem = self._compose.spec.shared_memory
        shared_doc = self._compose.spec.shared_documents
        shared_mem_path: str | None = None
        shared_doc_path: str | None = None

        if shared_mem.enabled:
            from initrunner.stores.base import DEFAULT_MEMORY_DIR

            shared_mem_path = shared_mem.store_path or str(
                DEFAULT_MEMORY_DIR / f"{self._compose.metadata.name}-shared.db"
            )

        if shared_doc.enabled:
            from initrunner.stores.base import DEFAULT_STORES_DIR

            shared_doc_path = shared_doc.store_path or str(
                DEFAULT_STORES_DIR / f"{self._compose.metadata.name}-shared.lance"
            )

        for name, config in self._compose.spec.services.items():
            try:
                role_path = self._base_dir / config.role

                if shared_mem_path or shared_doc_path:
                    _load_dotenv(role_path.parent)
                    role = load_role(role_path)
                    role = resolve_role_model(role, role_path)
                    if shared_mem_path:
                        apply_shared_memory(role, shared_mem_path, shared_mem.max_memories)
                    if shared_doc_path:
                        apply_shared_documents(role, shared_doc, shared_doc_path)
                    agent = build_agent(role, role_dir=role_path.parent)
                else:
                    role, agent = load_and_build(role_path)

                service = ComposeService(
                    name=name,
                    role=role,
                    agent=agent,
                    config=config,
                    audit_logger=self._audit_logger,
                )

                # Build role sinks (daemon mode only)
                should_build_role_sinks = not one_shot and (
                    (config.sink is None)
                    or (config.sink is not None and config.sink.keep_existing_sinks)
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

    # ------------------------------------------------------------------
    # Topology helpers
    # ------------------------------------------------------------------

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

    def _find_entry(self, entry_service: str | None = None) -> ComposeService:
        """Identify the entry service (first with no incoming sink targets)."""
        if entry_service is not None:
            if entry_service not in self._services:
                raise ValueError(f"Entry service '{entry_service}' not found")
            return self._services[entry_service]

        targeted: set[str] = set()
        for config in self._compose.spec.services.values():
            if config.sink is not None:
                raw = config.sink.target
                targets = raw if isinstance(raw, list) else [raw]
                targeted.update(targets)

        for tier in self._topological_order():
            for name in tier:
                if name not in targeted and name in self._services:
                    return self._services[name]

        for tier in self._topological_order():
            for name in tier:
                if name in self._services:
                    return self._services[name]

        raise RuntimeError("No services available")

    # ------------------------------------------------------------------
    # One-shot execution
    # ------------------------------------------------------------------

    def run_once(
        self,
        prompt: str,
        *,
        entry_service: str | None = None,
        message_history: list | None = None,
        timeout_seconds: float = 300,
        on_service_start: Callable[[str], None] | None = None,
        on_service_complete: Callable[[str, RunResult], None] | None = None,
    ) -> ComposeRunResult:
        """Run a single prompt through the compose graph synchronously."""
        from initrunner._ids import generate_id
        from initrunner.compose.graph import run_compose_graph_sync

        compose_run_id = generate_id()
        self._build_services(one_shot=True)
        entry = self._find_entry(entry_service)

        _refs, _entry_name, total_ms, timed_out = run_compose_graph_sync(
            self._compose,
            self._services,
            prompt,
            entry_service=entry.name,
            message_history=message_history,
            timeout_seconds=timeout_seconds,
            audit_logger=self._audit_logger,
            on_service_start=on_service_start,
            on_service_complete=on_service_complete,
            one_shot=True,
            compose_run_id=compose_run_id,
        )

        result = self._collect_results(entry, total_ms, timed_out=timed_out)
        result.compose_run_id = compose_run_id
        self._log_aggregate(compose_run_id, prompt, result)
        return result

    async def run_once_async(
        self,
        prompt: str,
        *,
        entry_service: str | None = None,
        message_history: list | None = None,
        timeout_seconds: float = 300,
        on_service_start: Callable[[str], None] | None = None,
        on_service_complete: Callable[[str, RunResult], None] | None = None,
    ) -> ComposeRunResult:
        """Run a single prompt through the compose graph asynchronously."""
        from initrunner._ids import generate_id
        from initrunner.compose.graph import run_compose_graph_async

        compose_run_id = generate_id()
        self._build_services(one_shot=True)
        entry = self._find_entry(entry_service)

        _refs, _entry_name, total_ms, timed_out = await run_compose_graph_async(
            self._compose,
            self._services,
            prompt,
            entry_service=entry.name,
            message_history=message_history,
            timeout_seconds=timeout_seconds,
            audit_logger=self._audit_logger,
            on_service_start=on_service_start,
            on_service_complete=on_service_complete,
            one_shot=True,
            compose_run_id=compose_run_id,
        )

        result = self._collect_results(entry, total_ms, timed_out=timed_out)
        result.compose_run_id = compose_run_id
        self._log_aggregate(compose_run_id, prompt, result)
        return result

    # ------------------------------------------------------------------
    # Daemon execution
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Build services and start daemon in a background thread."""
        from initrunner.compose.graph import start_daemon

        self._build_services()
        self._shutdown, self._daemon_thread = start_daemon(
            self._compose, self._services, self._audit_logger
        )

    def stop(self) -> None:
        """Signal daemon shutdown and wait for thread to finish."""
        if self._shutdown is not None:
            self._shutdown.set()
        if self._daemon_thread is not None:
            self._daemon_thread.join(timeout=30)
            self._daemon_thread = None

    # ------------------------------------------------------------------
    # Health reporting
    # ------------------------------------------------------------------

    def service_health(self) -> list[dict]:
        """Return per-service run/error stats."""
        return [
            {
                "service": name,
                "runs": svc.run_count,
                "errors": svc.error_count,
            }
            for name, svc in self._services.items()
        ]

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def _collect_results(
        self,
        entry: ComposeService,
        total_duration_ms: int,
        *,
        timed_out: bool = False,
    ) -> ComposeRunResult:
        """Collect per-service results into a ComposeRunResult."""
        steps: list[ServiceStepResult] = []
        total_in = 0
        total_out = 0

        terminal_names: set[str] = set()
        for name, config in self._compose.spec.services.items():
            svc = self._services.get(name)
            if svc is None or svc._last_result is None:
                continue
            has_delegate_targets = config.sink is not None and config.sink.target
            if not has_delegate_targets:
                terminal_names.add(name)

        for name, svc in self._services.items():
            r = svc._last_result
            if r is None:
                continue
            steps.append(
                ServiceStepResult(
                    service_name=name,
                    output=r.output,
                    tokens_in=r.tokens_in,
                    tokens_out=r.tokens_out,
                    duration_ms=r.duration_ms,
                    tool_calls=r.tool_calls,
                    tool_call_names=list(r.tool_call_names),
                    success=r.success,
                    error=r.error,
                )
            )
            total_in += r.tokens_in
            total_out += r.tokens_out

        terminal_steps = [s for s in steps if s.service_name in terminal_names]
        if len(terminal_steps) == 1:
            output_mode = "single"
            final_name = terminal_steps[0].service_name
            output = terminal_steps[0].output
        elif len(terminal_steps) > 1:
            output_mode = "multiple"
            final_name = None
            output = "\n\n".join(
                f"**{s.service_name}**\n{s.output}" for s in terminal_steps if s.output
            )
        else:
            output_mode = "none"
            final_name = None
            output = ""

        error = None
        if timed_out:
            error = f"Pipeline timed out after {total_duration_ms}ms"
        elif any(not s.success for s in steps):
            error = next((s.error for s in steps if s.error), None)

        return ComposeRunResult(
            output=output,
            output_mode=output_mode,
            final_service_name=final_name,
            steps=steps,
            entry_messages=entry._last_messages,
            total_tokens_in=total_in,
            total_tokens_out=total_out,
            total_duration_ms=total_duration_ms,
            success=not timed_out and all(s.success for s in steps),
            error=error,
        )

    def _log_aggregate(
        self,
        compose_run_id: str,
        prompt: str,
        result: ComposeRunResult,
    ) -> None:
        """Log a top-level aggregate audit row for the compose run."""
        if not self._audit_logger:
            return
        import json
        from datetime import UTC, datetime

        from initrunner.audit.logger import AuditRecord

        self._audit_logger.log(
            AuditRecord(
                run_id=compose_run_id,
                agent_name=self._compose.metadata.name,
                timestamp=datetime.now(UTC).isoformat(),
                user_prompt=prompt,
                model="multi",
                provider="multi",
                output=result.output,
                tokens_in=result.total_tokens_in,
                tokens_out=result.total_tokens_out,
                total_tokens=result.total_tokens_in + result.total_tokens_out,
                tool_calls=sum(s.tool_calls for s in result.steps),
                duration_ms=result.total_duration_ms,
                success=result.success,
                error=result.error,
                trigger_type="compose_run",
                trigger_metadata=json.dumps({
                    "compose_name": self._compose.metadata.name,
                    "compose_run_id": compose_run_id,
                    "scope": "aggregate",
                    "final_service_name": result.final_service_name,
                    "output_mode": result.output_mode,
                }),
            )
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

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

    health = orchestrator.service_health()
    if health:
        health_table = Table(title="Service Health")
        health_table.add_column("Service", style="cyan")
        health_table.add_column("Runs", justify="right")
        health_table.add_column("Errors", justify="right")

        for info in health:
            error_style = "red" if info["errors"] > 0 else ""
            health_table.add_row(
                info["service"],
                str(info["runs"]),
                f"[{error_style}]{info['errors']}[/{error_style}]"
                if error_style
                else str(info["errors"]),
            )

        console.print(health_table)


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
        f"[bold]Compose[/bold] -- {compose.metadata.name} ({len(compose.spec.services)} services)"
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
