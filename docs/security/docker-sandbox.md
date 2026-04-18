# Docker Sandbox

The Docker sandbox runs tool subprocesses inside disposable `docker run --rm --init` containers. It's the portable option: works on macOS, Windows, and Linux, supports pinned OS images, and handles bridge networking natively.

For the cross-backend config reference, see [Runtime Sandbox](sandbox.md). For the Linux-native alternative with no daemon, see [Bubblewrap Sandbox](bubblewrap.md). For running initrunner itself inside Docker (a different topic), see [Docker](../getting-started/docker.md).

## Why Docker

- **Cross-platform.** Works the same on macOS, Windows, and Linux.
- **Pinned environment.** The image is the filesystem. Upgrading the host doesn't change what the sandbox sees.
- **Bridge networking.** For tools that need outbound HTTP with a user-defined network, egress allowlist, or Docker DNS aliases, only Docker supports it.
- **Standard flags.** Memory (`-m`), CPU (`--cpus`), read-only rootfs (`--read-only`), pid limit (`--pids-limit`), container user (`--user`) — all stock `docker run` options.

## Requirements

A reachable Docker daemon. Preflight runs `docker info` before any tool launches and raises `SandboxUnavailableError` with install remediation when the daemon is missing:

| Platform | Command |
|---|---|
| Debian/Ubuntu | `apt install docker.io && systemctl start docker` |
| Fedora | `dnf install docker && systemctl start docker` |
| Arch | `pacman -S docker && systemctl start docker` |
| macOS | `brew install --cask docker`, then open Docker Desktop |
| Windows | Install Docker Desktop |

Preflight also checks the configured image with `docker image inspect` and runs `docker pull` if it's missing. Private images need `docker login` on the host first.

## Enabling it

```yaml
security:
  sandbox:
    backend: docker         # or: auto (prefers bwrap on Linux, falls back to Docker)
    network: none           # none | bridge | host
    memory_limit: 256m
    cpu_limit: 1.0
    read_only_rootfs: true
    allowed_read_paths: []
    allowed_write_paths: []
    bind_mounts: []
    env_passthrough: []
    docker:
      image: python:3.12-slim
      user: auto            # "auto" | "1000:1000" | null (root)
      extra_args: []        # dangerous flags blocked by schema
```

## Isolation model

Each tool call becomes one `docker run --rm --init` invocation. `--init` spawns a tiny PID-1 that reaps zombies and forwards signals — without it, ctrl-C won't stop a shell running `sleep`.

### Base flags

| Flag | Purpose |
|---|---|
| `--rm` | Container is deleted when the process exits. No lingering state. |
| `--init` | tini as PID 1 for signal handling and zombie reaping. |
| `--name initrunner-<hash>` | Unique name for cleanup on timeout. |
| `--label initrunner.managed=true` | Identifies initrunner-managed containers for bulk cleanup. |
| `--pids-limit 256` | Caps fork bombs. |
| `--read-only` (when `read_only_rootfs: true`) | Root filesystem is read-only. |
| `--tmpfs /tmp:rw,noexec,nosuid,size=64m` | Writable `/tmp` without allowing writes elsewhere. |

### Network

| `network:` | Flag | Behavior |
|---|---|---|
| `none` | `--network none` | No interfaces, no DNS, no connectivity. Kernel-level block. |
| `bridge` | `--network bridge` | Default Docker bridge — outbound traffic is NAT'd through the host. |
| `host` | `--network host` | Shares the host network stack. Equivalent to no isolation at the network layer. |

### Working directory and mounts

- **`/work`** — the tool's `cwd`, bind-mounted read-write. Set as the container's working directory via `-w /work`.
- **`/role`** — the role directory, read-only. Role-relative `bind_mounts` resolve against this path on the host.
- **`bind_mounts`** — user-configured. Each entry becomes one `-v host:container[:ro]` flag. Relative `source` paths resolve against `role_dir`. Missing sources raise `ValueError` at build time — no silent failures.
- **Tool-internal mounts** — e.g. python_exec binding a tempfile. Code-controlled, no schema validation.

### User mapping

The `--user` flag depends on `docker.user` and whether writable mounts exist:

| `docker.user` | Writable mount? | `--user` value |
|---|---|---|
| `"auto"` | yes (work_dir or rw bind_mount) | `<host uid>:<host gid>` |
| `"auto"` | no | (omitted — container default user) |
| `"1000:1000"` (explicit) | either | `1000:1000` |
| `null` | either | (omitted — runs as root inside container) |

Auto mapping prevents a common pain point: the container writes files as root, then the host user can't delete them.

### Environment

Container env starts clean. Host variables pass through only when:

1. They're listed in `env_passthrough` **and** exist on the host. `scrub_env()` still strips sensitive prefixes (`OPENAI_API_KEY`, `AWS_SECRET`, …) first.
2. The tool sets them explicitly via `env={...}` on its `run()` call.

Each becomes one `-e KEY=value` flag.

### Resource limits

| Field | Flag | Notes |
|---|---|---|
| `memory_limit` | `-m 256m` | Container is OOM-killed at the limit. Exit code 137 triggers an auto-appended hint: "Container killed (OOM). Increase security.sandbox.memory_limit (current: 256m)." |
| `cpu_limit` | `--cpus 1.0` | Fractional cores. |
| `pids_limit` | `--pids-limit 256` | Always on. Caps runaway forks. |

### `extra_args` validation

`docker.extra_args` accepts additional `docker run` flags (e.g. `--ulimit=nofile=1024`). A blocklist rejects flags that defeat isolation:

- `--privileged`
- `--cap-add` (any form: bare, `--cap-add=NET_ADMIN`, `--cap-add NET_ADMIN`)
- `--security-opt` when it disables seccomp/apparmor
- `--pid=host`, `--ipc=host`, `--uts=host`, `--userns=host`
- `--device`, `--volume-driver`, `--runtime`

See `initrunner/agent/schema/security.py` for the full `_DOCKER_BLOCKED_ARGS` set.

## Container cleanup on timeout

When a tool exceeds its timeout, `subprocess.run` kills the local `docker` CLI — but the container keeps running. The backend catches `subprocess.TimeoutExpired` and runs `docker rm -f <name>` to force-remove it. The backend swallows any cleanup failure so it can't mask the original timeout error.

## Preflight

`initrunner doctor --role <file>` checks two things:

1. The Docker daemon answers `docker info`.
2. The configured image exists locally, or `docker pull` succeeds.

Run it once per role change so image pulls happen outside the hot path.

## Example: code interpreter with a specific runtime

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: docker-node-runner
spec:
  role: |
    You are a JavaScript assistant running in a pinned Node 20 container.
    Network disabled, 512m memory.
  model:
    provider: openai
    name: gpt-5-mini
  tools:
    - type: shell
      allowed_commands: [node, npm]
    - type: script
      scripts:
        - name: run_js
          body: |
            node -e "$CODE"
          parameters:
            - name: code
              required: true
  security:
    sandbox:
      backend: docker
      network: none
      memory_limit: 512m
      cpu_limit: 1.0
      read_only_rootfs: true
      docker:
        image: node:20-slim
        user: auto
```

## Running initrunner itself in Docker

When initrunner runs inside a container and you want sandboxed tools, the inner initrunner still needs a Docker daemon. Two patterns:

1. **Socket passthrough** (simpler, less secure): mount `/var/run/docker.sock` into the initrunner container. The inner process gets effective root on the host via the socket — use only for trusted roles.
2. **Docker-in-Docker** (safer, heavier): run a dind sidecar and point initrunner at it with `DOCKER_HOST=tcp://dind:2375`.

See [Docker — socket passthrough](../getting-started/docker.md#docker-sandbox-when-running-initrunner-in-docker-socket-passthrough) for the compose snippet.

## Audit

Each `run()` emits a `sandbox.exec` security event:

```
backend=docker argv0=/usr/bin/python rc=0 duration_ms=312
```

Query with:

```bash
initrunner audit security-events --event-type sandbox.exec
```

## Limitations

- **Per-call startup cost.** A Docker container takes ~200–500ms to start. bwrap is ~10× faster on the same host. Use `backend: auto` to prefer bwrap when available.
- **Daemon dependency.** Every tool call needs the daemon up. If it dies, tools fail with `SandboxUnavailableError`.
- **Image distribution.** First run may pull the image (up to 5 minutes). Run `initrunner doctor` to pull outside the hot path.
- **No seccomp customization in v1.** The sandbox uses Docker's default seccomp profile. The schema doesn't expose custom profiles.
