"""PEP 578 audit hook sandbox for custom tool execution.

Installs a permanent sys.addaudithook that enforces filesystem, network,
subprocess, import, and eval/exec restrictions when a sandbox_scope() is active.
Enforcement is per-thread via threading.local() — only fires inside custom tool
invocations, never during framework operations.
"""

from __future__ import annotations

import ipaddress
import logging
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from initrunner.agent.schema.security import ToolSandboxConfig
    from initrunner.audit.logger import AuditLogger

logger = logging.getLogger(__name__)


class SandboxViolation(RuntimeError):
    """Raised when a sandboxed custom tool violates a security policy."""


# ---------------------------------------------------------------------------
# Per-thread enforcement state
# ---------------------------------------------------------------------------

_sandbox_state = threading.local()

# Modules that are always blocked inside sandbox scope, regardless of config.
# Prevents the threading escape hatch (new threads get fresh threading.local).
_ALWAYS_BLOCKED_MODULES = frozenset({"threading", "_thread"})

# RFC 1918 + loopback + link-local networks
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


@dataclass
class _SandboxState:
    enforcing: bool = False
    depth: int = 0
    config: ToolSandboxConfig | None = None
    agent_name: str = ""
    violations: list[dict[str, str]] = field(default_factory=list)
    bypassed: bool = False


def _get_state() -> _SandboxState:
    if not hasattr(_sandbox_state, "state"):
        _sandbox_state.state = _SandboxState()
    return _sandbox_state.state


# ---------------------------------------------------------------------------
# Module-level audit logger reference (set by install_audit_hook)
# ---------------------------------------------------------------------------

_audit_logger: AuditLogger | None = None


def set_audit_logger(audit_logger: AuditLogger | None) -> None:
    """Set the audit logger for sandbox violation logging."""
    global _audit_logger
    _audit_logger = audit_logger


# ---------------------------------------------------------------------------
# Context managers
# ---------------------------------------------------------------------------


@contextmanager
def sandbox_scope(
    config: ToolSandboxConfig,
    agent_name: str = "",
):
    """Activate sandbox enforcement for the duration of a custom tool call.

    Reentrant via depth counter. Violations are batched and logged on exit.
    """
    state = _get_state()
    state.depth += 1
    was_enforcing = state.enforcing
    prev_config = state.config
    prev_agent = state.agent_name

    state.enforcing = True
    state.config = config
    state.agent_name = agent_name

    try:
        yield
    finally:
        state.depth -= 1
        if state.depth == 0:
            state.enforcing = False
            # Log batched violations on outermost exit
            if state.violations and _audit_logger is not None:
                for v in state.violations:
                    _audit_logger.log_security_event(
                        event_type="sandbox_violation",
                        agent_name=agent_name,
                        details=f"{v['event']}: {v['detail']}",
                    )
            state.violations = []
        else:
            state.enforcing = was_enforcing
        state.config = prev_config
        state.agent_name = prev_agent


@contextmanager
def _framework_bypass():
    """Temporarily disable sandbox enforcement for framework operations."""
    state = _get_state()
    was_bypassed = state.bypassed
    was_enforcing = state.enforcing
    state.bypassed = True
    state.enforcing = False
    try:
        yield
    finally:
        state.bypassed = was_bypassed
        state.enforcing = was_enforcing


# ---------------------------------------------------------------------------
# Violation recording
# ---------------------------------------------------------------------------


def _record_violation(state: _SandboxState, event: str, detail: str) -> None:
    """Record a violation and optionally raise."""
    state.violations.append({"event": event, "detail": detail})
    logger.warning("Sandbox violation [%s] in %s: %s", event, state.agent_name, detail)

    if state.config and state.config.sandbox_violation_action == "raise":
        raise SandboxViolation(f"[{event}] {detail}")


# ---------------------------------------------------------------------------
# Per-event checkers
# ---------------------------------------------------------------------------


def _check_open(state: _SandboxState, args: tuple[Any, ...]) -> None:
    """Check open() calls — block writes outside allowed paths, reads always pass."""
    if len(args) < 2:
        return
    path_arg, mode = args[0], args[1]
    if not isinstance(mode, str):
        return
    # Read-only modes are always allowed
    if set(mode) <= {"r", "b", "t"}:
        return

    # Write mode — check against allowed_write_paths
    config = state.config
    if config is None:
        return

    if not config.allowed_write_paths:
        _record_violation(
            state, "open", f"Write to '{path_arg}' blocked (no write paths configured)"
        )
        return

    try:
        target = Path(str(path_arg)).resolve()
    except (TypeError, ValueError):
        _record_violation(state, "open", f"Write to '{path_arg}' blocked (invalid path)")
        return

    for allowed in config.allowed_write_paths:
        try:
            if target == Path(allowed).resolve() or target.is_relative_to(Path(allowed).resolve()):
                return
        except (TypeError, ValueError):
            continue

    _record_violation(state, "open", f"Write to '{target}' blocked (not in allowed_write_paths)")


def _check_subprocess(state: _SandboxState, event: str) -> None:
    """Block subprocess/os.system unless allowed."""
    config = state.config
    if config is None or config.allow_subprocess:
        return
    _record_violation(state, event, "Subprocess execution blocked")


def _check_network(state: _SandboxState, args: tuple[Any, ...]) -> None:
    """Block connections to private IPs when block_private_ips is True."""
    config = state.config
    if config is None:
        return

    if not config.block_private_ips:
        return

    if len(args) < 2:
        return

    addr = args[1]
    # addr is typically (host, port) or (host, port, flowinfo, scopeid)
    if not isinstance(addr, tuple) or len(addr) < 2:
        return

    host = addr[0]
    if not isinstance(host, str):
        return

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Not a raw IP — hostname-level filtering is done in _check_dns
        return

    if ip.is_loopback or ip.is_private or ip.is_link_local:
        _record_violation(state, "socket.connect", f"Connection to private IP {host} blocked")


def _check_dns(state: _SandboxState, args: tuple[Any, ...]) -> None:
    """Enforce allowed_network_hosts hostname allowlist at DNS resolution."""
    config = state.config
    if config is None or not config.allowed_network_hosts:
        return

    if len(args) < 1:
        return

    host = args[0]
    if not isinstance(host, str):
        return

    if host not in config.allowed_network_hosts:
        _record_violation(
            state, "socket.getaddrinfo", f"DNS resolution for '{host}' blocked (not in allowlist)"
        )


def _check_import(state: _SandboxState, args: tuple[Any, ...]) -> None:
    """Block modules in blocked_custom_modules + always block threading/_thread."""
    if len(args) < 1:
        return

    module_name = args[0]
    if not isinstance(module_name, str):
        return

    base = module_name.split(".")[0]

    # Always block threading modules when sandbox is active
    if base in _ALWAYS_BLOCKED_MODULES:
        _record_violation(
            state, "import", f"Import of '{base}' blocked (threading not allowed in sandbox)"
        )
        return

    config = state.config
    if config is None:
        return

    blocked = set(config.blocked_custom_modules)
    if base in blocked:
        _record_violation(state, "import", f"Import of '{base}' blocked")


def _check_eval_exec(state: _SandboxState, event: str, args: tuple[Any, ...]) -> None:
    """Block exec/eval/compile unless allowed.

    Filters out internal Python operations (module loading, encoding lookups)
    by checking whether the code is a string (user-level exec/compile) or a
    code object (internal machinery).
    """
    config = state.config
    if config is None or config.allow_eval_exec:
        return

    if event == "exec":
        # exec fires for ALL code execution including module loading.
        # Only block when called with a string (user-level exec("code")).
        if args and not isinstance(args[0], str):
            return
    elif event == "compile":
        # compile fires for all compilations.
        # Only block user-level compile (filename starts with "<").
        if len(args) >= 2 and isinstance(args[1], str):
            filename = args[1]
            if not filename.startswith("<"):
                return

    _record_violation(state, event, f"{event} blocked")


def _check_ctypes_dlopen(state: _SandboxState) -> None:
    """Always block ctypes.dlopen inside sandbox."""
    _record_violation(state, "ctypes.dlopen", "Native library loading blocked in sandbox")


# ---------------------------------------------------------------------------
# Main audit hook
# ---------------------------------------------------------------------------

_hook_installed = False


def _audit_hook(event: str, args: tuple[Any, ...]) -> None:
    """PEP 578 audit hook dispatcher."""
    state = _get_state()

    # Fast path: not enforcing
    if not state.enforcing:
        return

    if event == "open":
        _check_open(state, args)
    elif event in ("subprocess.Popen", "os.system"):
        _check_subprocess(state, event)
    elif event == "socket.connect":
        _check_network(state, args)
    elif event == "socket.getaddrinfo":
        _check_dns(state, args)
    elif event == "import":
        _check_import(state, args)
    elif event in ("exec", "compile"):
        _check_eval_exec(state, event, args)
    elif event == "ctypes.dlopen":
        _check_ctypes_dlopen(state)


def install_audit_hook() -> None:
    """Install the sandbox audit hook (idempotent, permanent per PEP 578)."""
    global _hook_installed
    if _hook_installed:
        return
    sys.addaudithook(_audit_hook)
    _hook_installed = True
    logger.info("PEP 578 sandbox audit hook installed")
