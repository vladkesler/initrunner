# Runtime Sandbox

Tool subprocesses run under kernel-level isolation, outside the initrunner process. This is distinct from the PEP 578 audit-hook sandbox (`security.tools.audit_hooks_enabled`), which runs inside the Python process.

Pick one of two backends:

- **[Bubblewrap](bubblewrap.md)** — Linux user namespaces. No daemon, no Docker, no root. Default on Linux.
- **[Docker](docker-sandbox.md)** — containers via the Docker daemon. Works on macOS, Windows, and Linux. Supports pinned images and bridge networking.

`backend: auto` tries bwrap on Linux and falls back to Docker. This page is the shared config reference; the linked pages cover each backend's details, examples, and limits.

## Configuration

```yaml
security:
  sandbox:
    backend: auto | bwrap | docker | none   # default: none
    network: none | bridge | host            # default: none
    allowed_read_paths: []
    allowed_write_paths: []
    memory_limit: "256m"
    cpu_limit: 1.0
    read_only_rootfs: true
    bind_mounts: []
    env_passthrough: []
    docker:
      image: "python:3.12-slim"
      user: "auto"
      extra_args: []
```

### `backend`

| Value | Behavior |
|---|---|
| `none` | No isolation. Tool subprocesses run on the host. |
| `bwrap` | Bubblewrap (Linux only). Lightweight user-namespace sandbox. |
| `docker` | Docker container. Requires a running Docker daemon. |
| `auto` | Prefers bwrap on Linux, falls back to Docker. Never falls to none. |

### `network`

| Value | bwrap | docker |
|---|---|---|
| `none` | `--unshare-net` (empty namespace) | `--network none` |
| `bridge` | Not supported (raises error) | `--network bridge` |
| `host` | Host network (no namespace) | `--network host` |

### `docker` sub-config

- `image`: Docker image to use (default: `python:3.12-slim`)
- `user`: Container user. `"auto"` maps to current uid:gid when writable mounts exist. `null` runs as root.
- `extra_args`: Additional `docker run` arguments. The schema blocks dangerous flags like `--privileged` and `--cap-add`.

## Backends at a glance

The dedicated [bubblewrap](bubblewrap.md) and [Docker](docker-sandbox.md) pages cover each backend in depth. Summary:

| | bubblewrap | Docker |
|---|---|---|
| **Platform** | Linux only | macOS, Windows, Linux |
| **Daemon** | None (`bwrap` binary) | Docker daemon required |
| **Startup cost** | ~fork+execve | ~200–500ms per call |
| **Filesystem** | Host `/usr`, `/bin`, `/lib` bound read-only | Pinned image |
| **Network isolation** | `--unshare-net` | `--network none` |
| **Bridge networking** | Not supported | `--network bridge` |
| **Resource limits** | `systemd-run --user` (skipped with warning if unavailable) | `-m`, `--cpus`, `--pids-limit` |
| **Install** | `apt install bubblewrap` | `apt install docker.io` or Docker Desktop |

## Mount validation

Mounts fall into two categories:

- **User-configured** (`allowed_read_paths`, `allowed_write_paths`, `bind_mounts` from role YAML): validated at load time against the role's permitted roots. A typo'd `/etc` mount fails before the role ever runs.
- **Tool-internal** (e.g. `python_exec` writes code to `/tmp` and mounts it at `/work/_run.py`): code-controlled, trusted, no validation.

## Audit

Every sandboxed call logs a `sandbox.exec` security event:

| Field | Meaning |
|---|---|
| `backend` | which backend ran the command |
| `argv0` | the command that ran |
| `rc` | exit code |
| `duration_ms` | wall-clock time |

Query with: `initrunner audit security-events --event-type sandbox.exec`

## Migrating from `security.docker`

`security.docker` has been removed. A role still using it fails schema validation with migration instructions. The equivalent new config:

```yaml
# Old
security:
  docker:
    enabled: true
    image: python:3.12-slim
    network: none

# New
security:
  sandbox:
    backend: docker
    network: none
    docker:
      image: python:3.12-slim
```

## Bundle metadata

Published bundles declare `supported_sandbox_backends` in the manifest. `initrunner install` checks the host and warns if none of the listed backends is available.
