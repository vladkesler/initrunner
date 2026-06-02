# Runtime Sandbox

Tool subprocesses run under kernel-level isolation, outside the initrunner process. This is distinct from the PEP 578 audit-hook sandbox (`security.tools.audit_hooks_enabled`), which runs inside the Python process.

Pick one of three backends:

- **[Bubblewrap](bubblewrap.md)** — Linux user namespaces. No daemon, no Docker, no root. Default on Linux.
- **[Docker](docker-sandbox.md)** — containers via the Docker daemon. Works on macOS, Windows, and Linux. Supports pinned images, bridge networking, and hardened runtimes (gVisor, Kata Containers) via `docker.runtime`.
- **[SSH](ssh-sandbox.md)** — remote execution on an existing host via OpenSSH. Not a kernel sandbox; use for *where* code runs (a build server, a GPU box), not for *containing* untrusted code.

`backend: auto` tries bwrap on Linux and falls back to Docker. SSH is opt-in only (`backend: ssh`) because it needs an explicit remote host. This page is the shared config reference; the linked pages cover each backend's details, examples, and limits.

For an honest comparison across backends and isolation classes (container vs userspace kernel vs microVM), see [Sandbox Backend Comparison](sandbox-comparison.md).

## Configuration

```yaml
security:
  sandbox:
    backend: auto | bwrap | docker | ssh | none   # default: none
    network: none | bridge | host                  # default: none
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
    ssh:
      host: my-build-box           # required when backend: ssh
      remote_cwd: /srv/work        # optional; SSH login dir if unset
      identity_file: null          # optional override; falls back to ~/.ssh/config
      config_file: null            # optional override
      connect_timeout: 10
      control_persist: "60s"
```

### `backend`

| Value | Behavior |
|---|---|
| `none` | No isolation. Tool subprocesses run on the host. |
| `bwrap` | Bubblewrap (Linux only). Lightweight user-namespace sandbox. |
| `docker` | Docker container. Requires a running Docker daemon. |
| `ssh` | Remote execution on a host via OpenSSH. Not a kernel sandbox. See [ssh-sandbox.md](ssh-sandbox.md). |
| `auto` | Prefers bwrap on Linux, falls back to Docker. Never selects `ssh` (requires explicit host) and never falls to `none`. |

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
| **Startup cost** | ~fork+execve | ~200-500ms per call |
| **Filesystem** | Host `/usr`, `/bin`, `/lib` bound read-only | Pinned image |
| **Network isolation** | `--unshare-net` | `--network none` |
| **Bridge networking** | Not supported | `--network bridge` |
| **Resource limits** | `systemd-run --user` (skipped with warning if unavailable) | `-m`, `--cpus`, `--pids-limit` |
| **Hardened runtime** | n/a | `docker.runtime: runsc / kata-runtime / kata-qemu / kata-fc / kata-clh` |
| **Install** | `apt install bubblewrap` | `apt install docker.io` or Docker Desktop |

For when a microVM checkbox is the actual question, see [Sandbox Backend Comparison](sandbox-comparison.md).

## Mount validation

Mounts fall into two categories:

- **User-configured** (`allowed_read_paths`, `allowed_write_paths`, `bind_mounts` from role YAML): at **load time**, the schema refuses any *writable* bind whose source is a host system root (`/`, `/etc`, `/usr`, `/home`, ...), so a role can't hand the agent the host filesystem. Relative sources are confined to the role directory by the backend at **build time**. Read-only binds of system paths are permitted (they cannot write the host).
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
