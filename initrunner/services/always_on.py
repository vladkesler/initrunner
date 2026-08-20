"""Always-on service lifecycle: catalog, start, stop, status, run.

Services are declarative bundles (service.yaml + role) with operate-time state
under ``~/.initrunner/services/<slug>/``. Runtime v1 uses one daemon process
per running service via ``python -m initrunner run <instance> --daemon``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from initrunner._paths import ensure_private_dir
from initrunner.agent.schema.service import (
    SERVICE_NAME_RE,
    ProcessIdentity,
    ServiceDefinition,
    ServiceParam,
    ServiceParamType,
    ServiceState,
    ServiceStatus,
)
from initrunner.config import get_services_dir
from initrunner.service_catalog import catalog_root

_logger = logging.getLogger(__name__)

_PARAM_RE = re.compile(r"\{\{\s*params\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_STATE_FILE = "state.json"
_LOG_FILE = "daemon.log"
_LOCK_TIMEOUT_S = 30.0
_CRON_PRESETS = {
    "hourly": "0 * * * *",
    "daily": "0 6 * * *",
    "weekly": "0 8 * * 1",
}
_CRON_RE = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$")

# Injectable for tests: (role_path, log_path, cwd, env) -> pid
DaemonLauncher = Any


class ServiceError(Exception):
    """User-facing service lifecycle error."""


class ProcessObservation(StrEnum):
    VERIFIED_RUNNING = "verified_running"
    VERIFIED_DEAD = "verified_dead"
    UNVERIFIABLE = "unverifiable"


# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------


def require_linux_supervision() -> None:
    if sys.platform != "linux":
        raise ServiceError(
            "Always-on service start/stop/run requires Linux in v1 "
            f"(this platform is {sys.platform!r})."
        )


# ---------------------------------------------------------------------------
# Slug + paths
# ---------------------------------------------------------------------------


def validate_slug(slug: str) -> str:
    if not isinstance(slug, str) or not SERVICE_NAME_RE.fullmatch(slug):
        raise ServiceError(
            f"Invalid service name {slug!r}. "
            "Use lowercase letters, digits, and hyphens "
            "(e.g. collector)."
        )
    return slug


def _services_root() -> Path:
    return get_services_dir().resolve()


def instance_dir(slug: str) -> Path:
    """Return instance directory; rejects path traversal."""
    slug = validate_slug(slug)
    root = _services_root()
    ensure_private_dir(root)
    candidate = (root / slug).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as e:
        raise ServiceError(f"Invalid service path for {slug!r}") from e
    if candidate == root:
        raise ServiceError(f"Invalid service path for {slug!r}")
    return candidate


def locks_dir() -> Path:
    root = _services_root()
    ensure_private_dir(root)
    d = root / ".locks"
    ensure_private_dir(d)
    return d


def lock_path(slug: str) -> Path:
    slug = validate_slug(slug)
    return locks_dir() / f"{slug}.lock"


def runtime_agent_name(slug: str) -> str:
    return f"service-{validate_slug(slug)}"


def _atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(text, encoding="utf-8")
        if sys.platform != "win32":
            try:
                tmp.chmod(mode)
            except OSError:
                pass
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


@contextmanager
def service_lock(slug: str, *, timeout: float = _LOCK_TIMEOUT_S) -> Iterator[None]:
    """Exclusive lifecycle lock (fcntl); lock files live outside instance dirs."""
    require_linux_supervision()
    import fcntl

    path = lock_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Open without truncating so concurrent waiters share the inode name.
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ServiceError(
                        f"Another operation is running on service '{slug}'. Retry in a moment."
                    ) from None
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@dataclass
class CatalogEntry:
    slug: str
    path: Path
    definition: ServiceDefinition
    source: str  # "shipped" | "extra"


@dataclass
class ServiceListItem:
    slug: str
    description: str
    version: str
    source: str
    status: ServiceStatus
    params: dict[str, Any] = field(default_factory=dict)


def _load_service_yaml(path: Path) -> ServiceDefinition:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ServiceError(f"Cannot read {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ServiceError(f"Invalid service manifest (not a mapping): {path}")
    try:
        return ServiceDefinition.model_validate(raw)
    except ValidationError as e:
        raise ServiceError(f"Invalid service manifest {path}: {e}") from e


def discover_catalog(*, extra_dirs: list[Path] | None = None) -> list[CatalogEntry]:
    """Scan shipped catalog (and optional test-only extra dirs)."""
    roots: list[tuple[Path, str]] = [(catalog_root(), "shipped")]
    for d in extra_dirs or []:
        if d.is_dir():
            roots.append((d.resolve(), "extra"))

    by_slug: dict[str, CatalogEntry] = {}
    for root, source in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith(("_", ".")):
                continue
            manifest = child / "service.yaml"
            if not manifest.is_file():
                continue
            try:
                definition = _load_service_yaml(manifest)
            except ServiceError as e:
                _logger.warning("Skipping service at %s: %s", child, e)
                continue
            slug = definition.metadata.name
            by_slug[slug] = CatalogEntry(
                slug=slug, path=child, definition=definition, source=source
            )
    return sorted(by_slug.values(), key=lambda e: e.slug)


def get_catalog_entry(slug: str, *, extra_dirs: list[Path] | None = None) -> CatalogEntry:
    slug = validate_slug(slug)
    for entry in discover_catalog(extra_dirs=extra_dirs):
        if entry.slug == slug:
            return entry
    raise ServiceError(
        f"Unknown service '{slug}'. Run `initrunner service list` to see available services."
    )


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def _state_path(slug: str) -> Path:
    return instance_dir(slug) / _STATE_FILE


def load_state(slug: str) -> ServiceState | None:
    path = _state_path(slug)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ServiceState.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError) as e:
        raise ServiceError(f"Corrupt service state for '{slug}': {e}") from e


def save_state(state: ServiceState) -> None:
    d = instance_dir(state.slug)
    ensure_private_dir(d)
    ensure_private_dir(d / "data")
    _atomic_write_text(
        _state_path(state.slug),
        state.model_dump_json(indent=2) + "\n",
    )


def role_path_for_state(state: ServiceState) -> Path:
    if not state.role_file:
        raise ServiceError(f"Service '{state.slug}' has no materialized role")
    path = instance_dir(state.slug) / state.role_file
    # Containment
    root = instance_dir(state.slug).resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as e:
        raise ServiceError("Invalid role path in state") from e
    return resolved


# ---------------------------------------------------------------------------
# Params + cadence
# ---------------------------------------------------------------------------


def resolve_params(
    definition: ServiceDefinition,
    provided: dict[str, Any],
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    unknown = set(provided) - set(definition.spec.params)
    if unknown:
        raise ServiceError(
            f"Unknown parameter(s): {', '.join(sorted(unknown))}. "
            f"Valid: {', '.join(sorted(definition.spec.params)) or '(none)'}"
        )
    for name, spec in definition.spec.params.items():
        if name in provided:
            value = provided[name]
        elif spec.default is not None:
            value = spec.default
        elif spec.required:
            raise ServiceError(
                f"Missing required parameter '{name}'. "
                f"{spec.description or 'See `initrunner service info`.'}"
            )
        else:
            continue
        resolved[name] = _coerce_param(name, value, spec)
    return resolved


def _coerce_param(name: str, value: Any, spec: ServiceParam) -> Any:
    if spec.type == ServiceParamType.STRING:
        return str(value)
    if spec.type == ServiceParamType.INT:
        try:
            return int(value)
        except (TypeError, ValueError) as e:
            raise ServiceError(f"Parameter '{name}' must be an integer") from e
    if spec.type == ServiceParamType.BOOL:
        if isinstance(value, bool):
            return value
        s = str(value).lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off"):
            return False
        raise ServiceError(f"Parameter '{name}' must be a boolean")
    if spec.type == ServiceParamType.ENUM:
        s = str(value)
        if s not in spec.values:
            raise ServiceError(f"Parameter '{name}' must be one of: {', '.join(spec.values)}")
        return s
    return value


def resolve_every(every: str) -> str:
    """Return validated cron expression from preset or raw cron."""
    raw = every.strip()
    if not raw:
        raise ServiceError("Schedule (--every) must not be empty")
    key = raw.lower()
    if key in _CRON_PRESETS:
        return _CRON_PRESETS[key]
    if not _CRON_RE.match(raw):
        raise ServiceError(
            f"Invalid schedule {every!r}. Use hourly, daily, weekly, or a 5-field cron expression."
        )
    # Basic rejection of empties already handled; accept 5 fields.
    return raw


def parse_sink_specs(sink_args: list[str]) -> list[dict[str, Any]]:
    sinks: list[dict[str, Any]] = []
    for raw in sink_args:
        if raw.startswith("file:"):
            rest = raw[5:]
            if rest.endswith(":json"):
                path, fmt = rest[:-5], "json"
            elif rest.endswith(":text"):
                path, fmt = rest[:-5], "text"
            else:
                path, fmt = rest, "text" if rest.endswith((".md", ".txt")) else "json"
            if not path:
                raise ServiceError(f"Invalid file sink: {raw}")
            sinks.append({"type": "file", "path": path, "format": fmt})
        elif raw.startswith("webhook:"):
            url = raw[len("webhook:") :]
            if not url:
                raise ServiceError(f"Invalid webhook sink: {raw}")
            sinks.append({"type": "webhook", "url": url})
        else:
            raise ServiceError(
                f"Unknown sink format '{raw}'. Use file:/path or webhook:https://..."
            )
    return sinks


def _substitute_params(text: str, params: dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in params:
            raise ServiceError(f"Template references params.{key} but that parameter was not set")
        return str(params[key])

    return _PARAM_RE.sub(repl, text)


def _resolve_file_sink_path(path_str: str, data_dir: Path) -> str:
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    # Relative: must stay under data_dir
    data_dir = data_dir.resolve()
    # Reject path parts that escape
    if ".." in p.parts:
        raise ServiceError(f"Relative sink path must not contain '..': {path_str}")
    resolved = (data_dir / p).resolve()
    try:
        resolved.relative_to(data_dir)
    except ValueError as e:
        raise ServiceError(f"Sink path escapes service data directory: {path_str}") from e
    return str(resolved)


def materialize_instance_role(
    entry: CatalogEntry,
    params: dict[str, Any],
    sinks: list[dict[str, Any]] | None,
    *,
    every: str,
    resolved_cron: str,
    timezone: str,
    dest: Path,
) -> tuple[str, list[dict[str, Any]]]:
    """Render role to dest; return (sha256 digest, resolved sink configs)."""
    del every  # schedule is carried only via resolved_cron
    definition = entry.definition
    if definition.spec.entry.kind != "Agent":
        raise ServiceError("Only Agent entry services are supported in v1")

    role_src = entry.path / definition.spec.entry.path
    if not role_src.is_file():
        raise ServiceError(f"Service entry role not found: {role_src}")

    template = role_src.read_text(encoding="utf-8")
    rendered = _substitute_params(template, params)

    try:
        data = yaml.safe_load(rendered)
    except yaml.YAMLError as e:
        raise ServiceError(f"Rendered role YAML is invalid: {e}") from e
    if not isinstance(data, dict):
        raise ServiceError("Rendered role YAML must be a mapping")

    from initrunner.agent.schema.document import DocumentClass, classify_mapping

    classification = classify_mapping(data)
    flat = classification.document_class is DocumentClass.FLAT_AGENT
    if flat:
        data["name"] = runtime_agent_name(entry.slug)
        spec = data
    else:
        # Force runtime agent name for audit/memory/budget isolation
        meta = data.setdefault("metadata", {})
        if not isinstance(meta, dict):
            raise ServiceError("Rendered role metadata must be a mapping")
        meta["name"] = runtime_agent_name(entry.slug)

        spec = data.setdefault("spec", {})
        if not isinstance(spec, dict):
            raise ServiceError("Rendered role spec must be a mapping")

    prompt = _substitute_params(definition.spec.schedule_prompt, params)
    spec["triggers"] = [
        {
            "type": "cron",
            "schedule": resolved_cron,
            "prompt": prompt,
            "timezone": timezone,
            "autonomous": definition.spec.defaults.autonomy,
        }
    ]

    data_dir = dest.parent / "data"
    ensure_private_dir(data_dir)
    final_sinks: list[dict[str, Any]] = (
        list(definition.spec.defaults.sinks) if sinks is None else list(sinks)
    )
    resolved_sinks: list[dict[str, Any]] = []
    for s in final_sinks:
        s = dict(s)
        if s.get("type") == "file" and "path" in s:
            s["path"] = _resolve_file_sink_path(str(s["path"]), data_dir)
        resolved_sinks.append(s)
    if resolved_sinks:
        spec["sinks"] = resolved_sinks
    else:
        spec.pop("sinks", None)

    if definition.spec.defaults.guardrails:
        existing = spec.get("guardrails") or {}
        if not isinstance(existing, dict):
            existing = {}
        spec["guardrails"] = {**definition.spec.defaults.guardrails, **existing}

    if definition.spec.defaults.autonomy and not spec.get("autonomy"):
        spec["autonomy"] = {}

    text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _atomic_write_text(dest, text)
    return digest, resolved_sinks


# ---------------------------------------------------------------------------
# Requires
# ---------------------------------------------------------------------------


def check_requires(definition: ServiceDefinition) -> list[str]:
    missing: list[str] = []
    for var in definition.spec.requires.env:
        if not os.environ.get(var):
            missing.append(f"env:{var}")
    for extra in definition.spec.requires.extras:
        if not _extra_available(extra):
            missing.append(f'extra:{extra} (pip install "initrunner[{extra}]")')
    return missing


def _extra_available(extra: str) -> bool:
    markers = {
        "search": "ddgs",
        "ingest": "pymupdf4llm",
        "telegram": "telegram",
        "discord": "discord",
        "slack": "slack_sdk",
        "audio": "youtube_transcript_api",
        "dashboard": "fastapi",
    }
    mod = markers.get(extra)
    if mod is None:
        return True
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Process identity (Linux)
# ---------------------------------------------------------------------------


def _read_boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _read_proc_start_ticks(pid: int) -> int | None:
    try:
        # /proc/<pid>/stat: starttime is field 22 (1-based), after comm in parens
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # comm can contain spaces/parens — split after last ')'
    rparen = raw.rfind(")")
    if rparen < 0:
        return None
    fields = raw[rparen + 2 :].split()
    # fields[0] is state (field 3), starttime is field 22 → index 19 in post-comm
    try:
        return int(fields[19])
    except (IndexError, ValueError):
        return None


def _cmdline_contains_role(pid: int, role_path: str) -> bool:
    try:
        data = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    parts = [p.decode("utf-8", errors="replace") for p in data.split(b"\0") if p]
    role = str(Path(role_path).resolve())
    return any(role in p or p == role for p in parts)


def _reap_if_child(pid: int) -> None:
    """Reap pid if it is our child (avoids zombies looking 'alive' to kill(0))."""
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass
    except OSError:
        pass


def _pid_zombie(pid: int) -> bool:
    if sys.platform != "linux":
        return False
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    rparen = raw.rfind(")")
    if rparen < 0:
        return False
    # State char is the next field after ``) ``
    try:
        return raw[rparen + 2] == "Z"
    except IndexError:
        return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    if _pid_zombie(pid):
        _reap_if_child(pid)
        return False
    return True


def collect_process_identity(pid: int, role_path: str) -> ProcessIdentity | None:
    if sys.platform != "linux":
        return None
    if not _pid_alive(pid):
        return None
    boot = _read_boot_id()
    ticks = _read_proc_start_ticks(pid)
    if boot is None or ticks is None:
        return None
    if not _cmdline_contains_role(pid, role_path):
        return None
    return ProcessIdentity(
        pid=pid,
        boot_id=boot,
        proc_start_ticks=ticks,
        role_path=str(Path(role_path).resolve()),
        started_at=datetime.now(UTC).isoformat(),
    )


def observe_process(identity: ProcessIdentity | None) -> ProcessObservation:
    if identity is None:
        return ProcessObservation.VERIFIED_DEAD
    if sys.platform != "linux":
        if _pid_alive(identity.pid):
            return ProcessObservation.UNVERIFIABLE
        return ProcessObservation.VERIFIED_DEAD

    if not _pid_alive(identity.pid):
        return ProcessObservation.VERIFIED_DEAD

    boot = _read_boot_id()
    ticks = _read_proc_start_ticks(identity.pid)
    if boot is None or ticks is None:
        return ProcessObservation.UNVERIFIABLE
    if boot != identity.boot_id or ticks != identity.proc_start_ticks:
        return ProcessObservation.VERIFIED_DEAD
    if not _cmdline_contains_role(identity.pid, identity.role_path):
        return ProcessObservation.VERIFIED_DEAD
    return ProcessObservation.VERIFIED_RUNNING


# ---------------------------------------------------------------------------
# Daemon supervision
# ---------------------------------------------------------------------------


def _log_path(slug: str) -> Path:
    return instance_dir(slug) / _LOG_FILE


def _tail_log(slug: str, *, lines: int = 50) -> str:
    path = _log_path(slug)
    if not path.is_file():
        return "(no log yet)"
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"(cannot read log: {e})"
    parts = content.splitlines()
    return "\n".join(parts[-lines:]) if parts else "(empty log)"


def _default_daemon_launcher(
    role_path: Path, log_path: Path, cwd: Path, env: dict[str, str]
) -> int:
    cmd = [
        sys.executable,
        "-m",
        "initrunner",
        "run",
        str(role_path.resolve()),
        "--daemon",
    ]
    with open(log_path, "ab") as log_f:
        log_f.write(f"\n--- start {datetime.now(UTC).isoformat()} ---\n".encode())
        log_f.flush()
        proc = subprocess.Popen(
            cmd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            cwd=str(cwd),
            env=env,
            start_new_session=True,
        )
    return proc.pid


_daemon_launcher: DaemonLauncher = _default_daemon_launcher


def set_daemon_launcher(launcher: DaemonLauncher | None) -> None:
    """Test hook: replace or restore the daemon process launcher."""
    global _daemon_launcher
    _daemon_launcher = launcher or _default_daemon_launcher


def start_daemon(slug: str, role_path: Path) -> ProcessIdentity:
    """Spawn supervised child; return identity. Does not update state."""
    require_linux_supervision()
    ensure_private_dir(instance_dir(slug))
    log_path = _log_path(slug)
    env = os.environ.copy()
    env.setdefault("INITRUNNER_NO_TELEMETRY_PROMPT", "1")
    # A long-lived agent process bridges sync and async with worker threads, and
    # glibc gives each thread its own malloc arena. Capping arenas keeps RSS near
    # the live heap; `MALLOC_ARENA_MAX=... initrunner service start` still wins.
    env.setdefault("MALLOC_ARENA_MAX", "2")

    pid = _daemon_launcher(role_path, log_path, instance_dir(slug), env)
    time.sleep(0.3)
    if not _pid_alive(pid):
        tail = _tail_log(slug, lines=20)
        raise ServiceError(f"Service daemon for '{slug}' exited immediately.\nLog tail:\n{tail}")
    identity = collect_process_identity(pid, str(role_path))
    if identity is None:
        # Child alive but we cannot prove identity — fail closed: try to stop it
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        raise ServiceError(
            f"Could not verify process identity for service '{slug}' "
            f"(pid {pid}). Not marking as running."
        )
    return identity


def stop_daemon_identity(identity: ProcessIdentity, *, timeout: float = 5.0) -> None:
    """Signal only if still verified_running for this identity."""
    obs = observe_process(identity)
    if obs is ProcessObservation.VERIFIED_DEAD:
        _reap_if_child(identity.pid)
        return
    if obs is ProcessObservation.UNVERIFIABLE:
        raise ServiceError(
            f"Process pid={identity.pid} is alive but identity cannot be verified. "
            "Refusing to signal it. Inspect the process manually."
        )
    try:
        os.kill(identity.pid, signal.SIGTERM)
    except ProcessLookupError:
        _reap_if_child(identity.pid)
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _reap_if_child(identity.pid)
        if observe_process(identity) is ProcessObservation.VERIFIED_DEAD:
            return
        time.sleep(0.05)
    # Last resort only if still verified
    if observe_process(identity) is not ProcessObservation.VERIFIED_RUNNING:
        _reap_if_child(identity.pid)
        return
    try:
        os.kill(identity.pid, signal.SIGKILL)
    except ProcessLookupError:
        _reap_if_child(identity.pid)
        return
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        _reap_if_child(identity.pid)
        if observe_process(identity) is ProcessObservation.VERIFIED_DEAD:
            return
        time.sleep(0.05)
    _reap_if_child(identity.pid)


def _gc_old_roles(slug: str, keep_generation: int, *, keep: int = 2) -> None:
    d = instance_dir(slug)
    if not d.is_dir():
        return
    gens: list[tuple[int, Path]] = []
    for p in d.glob("role.*.yaml"):
        try:
            n = int(p.name.removeprefix("role.").removesuffix(".yaml"))
        except ValueError:
            continue
        gens.append((n, p))
    gens.sort(key=lambda x: x[0], reverse=True)
    to_keep = {keep_generation}
    for n, _ in gens:
        if len(to_keep) >= keep:
            break
        to_keep.add(n)
    for n, p in gens:
        if n not in to_keep:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


def _output_paths_from_sinks(sinks: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for s in sinks:
        if s.get("type") == "file" and s.get("path"):
            out.append(str(s["path"]))
    return out


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def list_services(*, extra_dirs: list[Path] | None = None) -> list[ServiceListItem]:
    items: list[ServiceListItem] = []
    for entry in discover_catalog(extra_dirs=extra_dirs):
        state = load_state(entry.slug)
        status = ServiceStatus.STOPPED
        params: dict[str, Any] = {}
        if state is not None:
            state = _heal_state(state)
            status = state.status
            params = state.params
        items.append(
            ServiceListItem(
                slug=entry.slug,
                description=entry.definition.metadata.description,
                version=entry.definition.metadata.version or "",
                source=entry.source,
                status=status,
                params=params,
            )
        )
    # Orphan instances (catalog removed)
    root = get_services_dir()
    if root.is_dir():
        known = {i.slug for i in items}
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith(".") or child.name in known:
                continue
            try:
                validate_slug(child.name)
            except ServiceError:
                continue
            state = load_state(child.name)
            if state is None:
                continue
            state = _heal_state(state)
            items.append(
                ServiceListItem(
                    slug=state.slug,
                    description="(catalog entry missing)",
                    version=state.service_version,
                    source="orphan",
                    status=state.status,
                    params=state.params,
                )
            )
    return items


def _heal_state(state: ServiceState) -> ServiceState:
    if state.status != ServiceStatus.RUNNING:
        return state
    obs = observe_process(state.process)
    if obs is ProcessObservation.VERIFIED_RUNNING:
        return state
    if obs is ProcessObservation.UNVERIFIABLE:
        # Do not rewrite state
        return state
    # verified_dead
    state.status = ServiceStatus.STOPPED
    state.process = None
    state.last_error = "daemon process not found or identity mismatch (stopped externally?)"
    state.stopped_at = datetime.now(UTC).isoformat()
    save_state(state)
    return state


@dataclass
class StartResult:
    state: ServiceState
    version_from: str = ""
    version_to: str = ""
    idempotent: bool = False


def start_service(
    slug: str,
    *,
    params: dict[str, Any] | None = None,
    sinks: list[str] | None = None,
    every: str | None = None,
    extra_dirs: list[Path] | None = None,
    has_overrides: bool | None = None,
) -> StartResult:
    """Start a service: materialize if needed, start daemon under lock."""
    slug = validate_slug(slug)
    with service_lock(slug):
        return _start_service_unlocked(
            slug,
            params=params,
            sinks=sinks,
            every=every,
            extra_dirs=extra_dirs,
            has_overrides=has_overrides,
        )


def _start_service_unlocked(
    slug: str,
    *,
    params: dict[str, Any] | None = None,
    sinks: list[str] | None = None,
    every: str | None = None,
    extra_dirs: list[Path] | None = None,
    has_overrides: bool | None = None,
) -> StartResult:
    require_linux_supervision()
    entry = get_catalog_entry(slug, extra_dirs=extra_dirs)
    definition = entry.definition

    missing = check_requires(definition)
    if missing:
        raise ServiceError(
            "Missing requirements:\n  - "
            + "\n  - ".join(missing)
            + "\nFix these, then re-run start."
        )

    provided = dict(params or {})
    sink_args = list(sinks) if sinks is not None else None
    if has_overrides is None:
        has_overrides = bool(provided) or sink_args is not None or every is not None

    existing = load_state(slug)
    if existing is not None:
        existing = _heal_state(existing)

    if existing and existing.status == ServiceStatus.RUNNING:
        obs = observe_process(existing.process)
        if obs is ProcessObservation.UNVERIFIABLE:
            raise ServiceError(
                f"Service '{slug}' has an unverifiable running process "
                f"(pid={existing.process.pid if existing.process else '?'}). "
                "Resolve manually before starting again."
            )
        if obs is ProcessObservation.VERIFIED_RUNNING:
            if has_overrides:
                raise ServiceError(
                    f"Service '{slug}' is already running. Stop it before changing configuration."
                )
            return StartResult(state=existing, idempotent=True)
        # verified_dead healed above

    # Resolve config
    if existing and not has_overrides:
        role = role_path_for_state(existing)
        if not role.is_file():
            raise ServiceError(f"Instance role missing for '{slug}'. Start with parameters again.")
        identity = start_daemon(slug, role)
        existing.status = ServiceStatus.RUNNING
        existing.process = identity
        existing.stopped_at = None
        existing.last_error = None
        if existing.started_at is None:
            existing.started_at = datetime.now(UTC).isoformat()
        save_state(existing)
        return StartResult(state=existing)

    # Materialize (first start or overrides)
    base_params = dict(existing.params) if existing else {}
    base_params.update(provided)
    resolved = resolve_params(definition, base_params)

    if every is not None:
        every_val = every
    elif existing is not None:
        every_val = existing.every
    else:
        every_val = definition.spec.every
    cron = resolve_every(every_val)
    timezone = definition.spec.defaults.timezone

    # None → catalog defaults inside materialize; list → replace (possibly empty)
    if sink_args is not None:
        mat_sink_arg: list[dict[str, Any]] | None = parse_sink_specs(sink_args)
    elif existing is not None and existing.sinks:
        mat_sink_arg = list(existing.sinks)
    else:
        mat_sink_arg = None

    d = instance_dir(slug)
    ensure_private_dir(d)
    ensure_private_dir(d / "data")
    generation = (existing.generation if existing else 0) + 1
    role_file = f"role.{generation}.yaml"
    dest = d / role_file

    digest, mat_sinks = materialize_instance_role(
        entry,
        resolved,
        mat_sink_arg,
        every=every_val,
        resolved_cron=cron,
        timezone=timezone,
        dest=dest,
    )

    now = datetime.now(UTC).isoformat()
    prev_version = existing.service_version if existing else ""
    new_version = definition.metadata.version or ""

    state = ServiceState(
        slug=slug,
        service_version=new_version,
        status=ServiceStatus.STOPPED,
        params=resolved,
        sinks=mat_sinks,
        every=every_val,
        resolved_cron=cron,
        timezone=timezone,
        started_at=existing.started_at if existing else None,
        stopped_at=now,
        generation=generation,
        role_file=role_file,
        role_digest=digest,
        catalog_path=str(entry.path),
        process=None,
        last_error=None,
        output_paths=_output_paths_from_sinks(mat_sinks),
    )
    save_state(state)
    _gc_old_roles(slug, generation)

    identity = start_daemon(slug, dest)

    state.status = ServiceStatus.RUNNING
    state.process = identity
    state.stopped_at = None
    if state.started_at is None:
        state.started_at = now
    save_state(state)
    return StartResult(
        state=state,
        version_from=prev_version,
        version_to=new_version,
    )


def stop_service(slug: str, *, purge: bool = False) -> None:
    slug = validate_slug(slug)
    with service_lock(slug):
        _stop_service_unlocked(slug, purge=purge)


def _stop_service_unlocked(slug: str, *, purge: bool = False) -> None:
    require_linux_supervision()
    state = load_state(slug)
    if state is None and not instance_dir(slug).exists():
        raise ServiceError(f"Service '{slug}' is not started")

    if state is not None:
        state = _heal_state(state)
        if state.status == ServiceStatus.RUNNING and state.process is not None:
            obs = observe_process(state.process)
            if obs is ProcessObservation.UNVERIFIABLE:
                raise ServiceError(
                    f"Service '{slug}' process is unverifiable "
                    f"(pid={state.process.pid}). Refusing to stop/purge."
                )
            if obs is ProcessObservation.VERIFIED_RUNNING:
                stop_daemon_identity(state.process)

    if purge:
        d = instance_dir(slug)
        root = _services_root()
        resolved = d.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as e:
            raise ServiceError("Refusing to purge path outside services directory") from e
        if resolved == root or resolved.name.startswith("."):
            raise ServiceError("Refusing to purge services root or lock directory")
        import shutil

        if resolved.is_dir():
            shutil.rmtree(resolved)
        return

    if state is not None:
        state.status = ServiceStatus.STOPPED
        state.process = None
        state.stopped_at = datetime.now(UTC).isoformat()
        save_state(state)


@dataclass
class ServiceStatusView:
    state: ServiceState
    observation: ProcessObservation
    log_tail: str
    role_path: Path | None
    last_run_at: str | None = None
    last_run_ok: bool | None = None
    cost_today_usd: float | None = None
    unverifiable_message: str | None = None
    rss_mb: int | None = None


def status(slug: str) -> ServiceStatusView:
    slug = validate_slug(slug)
    state = load_state(slug)
    if state is None:
        raise ServiceError(f"Service '{slug}' is not started")

    obs = observe_process(state.process) if state.process else ProcessObservation.VERIFIED_DEAD
    unverifiable_message = None
    if state.status == ServiceStatus.RUNNING:
        if obs is ProcessObservation.VERIFIED_DEAD:
            state = _heal_state(state)
            obs = ProcessObservation.VERIFIED_DEAD
        elif obs is ProcessObservation.UNVERIFIABLE:
            unverifiable_message = (
                f"Process pid={state.process.pid if state.process else '?'} is alive "
                "but identity cannot be verified"
            )

    role: Path | None = None
    try:
        role = role_path_for_state(state) if state.role_file else None
    except ServiceError:
        role = None

    last_run_at, last_run_ok, cost = _audit_snapshot(runtime_agent_name(slug))

    # Only once the PID is confirmed to be this service's daemon: reading
    # /proc for an unverified PID would report a recycled process's memory.
    rss_mb = None
    if state.process and obs is ProcessObservation.VERIFIED_RUNNING:
        from initrunner._proc import process_rss_mb

        rss_mb = process_rss_mb(state.process.pid)

    return ServiceStatusView(
        state=state,
        observation=obs,
        log_tail=_tail_log(slug, lines=15),
        role_path=role,
        last_run_at=last_run_at,
        last_run_ok=last_run_ok,
        cost_today_usd=cost,
        unverifiable_message=unverifiable_message,
        rss_mb=rss_mb,
    )


def _audit_snapshot(
    agent_name: str,
) -> tuple[str | None, bool | None, float | None]:
    last_run_at: str | None = None
    last_run_ok: bool | None = None
    cost: float | None = None
    try:
        from initrunner.services.operations import query_audit_sync

        rows = query_audit_sync(agent_name=agent_name, limit=1)
        if rows:
            rec = rows[0]
            last_run_at = getattr(rec, "timestamp", None) or None
            # Prefer explicit success/error fields when present
            err = getattr(rec, "error", None)
            if err is not None:
                last_run_ok = not bool(err)
            else:
                last_run_ok = True
    except Exception:
        _logger.debug("audit snapshot failed", exc_info=True)

    try:
        from initrunner.services.cost import cost_report_sync

        today = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00+00:00")
        report = cost_report_sync(agent_name=agent_name, since=today)
        cost = report.total_cost_usd
    except Exception:
        _logger.debug("cost snapshot failed", exc_info=True)

    return last_run_at, last_run_ok, cost


def service_logs(slug: str, *, lines: int = 50) -> str:
    slug = validate_slug(slug)
    if not instance_dir(slug).exists():
        raise ServiceError(f"Service '{slug}' is not started")
    return _tail_log(slug, lines=lines)


@dataclass
class ForcedRunResult:
    exit_code: int
    was_running: bool
    restart_error: str | None = None
    messages: list[str] = field(default_factory=list)


def forced_run(
    slug: str,
    *,
    model: str | None = None,
    extra_dirs: list[Path] | None = None,
) -> ForcedRunResult:
    """One-shot tick with concurrency rules under lifecycle lock."""
    slug = validate_slug(slug)
    with service_lock(slug):
        return _forced_run_unlocked(slug, model=model, extra_dirs=extra_dirs)


def _forced_run_unlocked(
    slug: str,
    *,
    model: str | None = None,
    extra_dirs: list[Path] | None = None,
) -> ForcedRunResult:
    require_linux_supervision()
    state = load_state(slug)
    if state is None:
        raise ServiceError(f"Service '{slug}' is not started")
    state = _heal_state(state)

    was_running = False
    if state.status == ServiceStatus.RUNNING and state.process is not None:
        obs = observe_process(state.process)
        if obs is ProcessObservation.UNVERIFIABLE:
            raise ServiceError(f"Service '{slug}' process is unverifiable; aborting run.")
        if obs is ProcessObservation.VERIFIED_RUNNING:
            was_running = True
            stop_daemon_identity(state.process)
            state.status = ServiceStatus.STOPPED
            state.process = None
            state.stopped_at = datetime.now(UTC).isoformat()
            save_state(state)

    role = role_path_for_state(state)
    prompt, autonomous = _prompt_from_role(role)

    cmd = [sys.executable, "-m", "initrunner", "run", str(role), "-p", prompt]
    if autonomous:
        cmd.append("-a")
    if model:
        cmd.extend(["--model", model])
    tick = subprocess.run(cmd, check=False)
    tick_code = tick.returncode

    restart_error: str | None = None
    messages: list[str] = []
    if was_running:
        try:
            _start_service_unlocked(slug, extra_dirs=extra_dirs, has_overrides=False)
        except ServiceError as e:
            restart_error = str(e)
            messages.append(f"restart failed: {e}")
            st = load_state(slug)
            if st is not None:
                st.status = ServiceStatus.STOPPED
                st.process = None
                st.last_error = restart_error
                save_state(st)

    if tick_code != 0:
        messages.insert(0, f"tick failed with exit code {tick_code}")
        exit_code = tick_code
    elif restart_error:
        exit_code = 1
    else:
        exit_code = 0
    return ForcedRunResult(
        exit_code=exit_code,
        was_running=was_running,
        restart_error=restart_error,
        messages=messages,
    )


def _prompt_from_role(role_path: Path) -> tuple[str, bool]:
    prompt = "Run the scheduled service task."
    autonomous = False
    try:
        data = yaml.safe_load(role_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return prompt, autonomous
    if not isinstance(data, dict):
        return prompt, autonomous
    from initrunner.services.starters import document_body

    body = document_body(data)
    for t in body.get("triggers") or []:
        if isinstance(t, dict) and t.get("type") == "cron":
            prompt = str(t.get("prompt") or prompt)
            autonomous = bool(t.get("autonomous", False))
            break
    if body.get("autonomy") is not None:
        autonomous = True
    return prompt, autonomous


def info_dict(slug: str, *, extra_dirs: list[Path] | None = None) -> dict[str, Any]:
    entry = get_catalog_entry(slug, extra_dirs=extra_dirs)
    d = entry.definition
    state = load_state(slug)
    if state is not None:
        state = _heal_state(state)
    params_out = {}
    for name, p in d.spec.params.items():
        params_out[name] = {
            "type": p.type.value,
            "required": p.required,
            "default": p.default,
            "description": p.description,
            "values": p.values or None,
        }
    return {
        "slug": slug,
        "version": d.metadata.version,
        "description": d.metadata.description,
        "source": entry.source,
        "path": str(entry.path),
        "primary_param": d.spec.primary_param,
        "every": d.spec.every,
        "params": params_out,
        "requires": {
            "env": d.spec.requires.env,
            "extras": d.spec.requires.extras,
        },
        "defaults": {
            "autonomy": d.spec.defaults.autonomy,
            "timezone": d.spec.defaults.timezone,
        },
        "status": state.status.value if state else ServiceStatus.STOPPED.value,
        "active_params": state.params if state else {},
        "runtime_agent_name": runtime_agent_name(slug),
    }
