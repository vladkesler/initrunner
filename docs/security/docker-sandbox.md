# Docker Sandbox for Tool Execution

InitRunner can run shell, Python, and script tool execution inside Docker containers, providing kernel-level isolation via network namespaces, cgroups, and filesystem restrictions. This is **opt-in** via `security.docker.enabled: true` in your role YAML. When disabled (the default), no behavior changes.

## Quick Start

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: sandboxed-agent
spec:
  role: You are a code execution assistant.
  model:
    provider: openai
    name: gpt-5-mini
  tools:
    - type: shell
    - type: python
  security:
    docker:
      enabled: true
```

This runs all shell and Python tool invocations inside `python:3.12-slim` containers with no network access and a read-only root filesystem.

## Prerequisites

Docker must be installed and the daemon running. Verify with:

```bash
initrunner doctor
```

The doctor command shows a `docker` row in the provider status table. If Docker is enabled in a role but not available, the agent fails to load with a `DockerNotAvailableError`.

## Configuration Reference

All fields under `security.docker`:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `false` | Enable Docker container isolation for tool execution. |
| `image` | `str` | `"python:3.12-slim"` | Docker image to use for containers. |
| `network` | `"none" \| "bridge" \| "host"` | `"none"` | Container network mode. `none` provides full network isolation. |
| `memory_limit` | `str` | `"256m"` | Memory limit in Docker format (`256m`, `1g`, etc.). |
| `cpu_limit` | `float` | `1.0` | CPU limit (fractional cores, must be > 0). |
| `read_only_rootfs` | `bool` | `true` | Mount root filesystem as read-only. A writable `/tmp` (64MB, noexec) is added automatically. |
| `user` | `"auto" \| str \| null` | `"auto"` | Container user. `"auto"` runs as current uid:gid when writable mounts exist. `null` runs as root. Explicit `"1000:1000"` sets a specific uid:gid. |
| `bind_mounts` | `list[BindMount]` | `[]` | Additional bind mounts into the container. |
| `env_passthrough` | `list[str]` | `[]` | Environment variable names to pass into the container (filtered through env scrubbing). |
| `extra_args` | `list[str]` | `[]` | Additional `docker run` flags. Security-sensitive flags are blocked. |

### BindMount Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `source` | `str` | *(required)* | Host path. Relative paths resolve against the role file's directory. |
| `target` | `str` | *(required)* | Container path. Must be absolute (start with `/`). |
| `read_only` | `bool` | `true` | Mount as read-only. |

## Security Defaults

The Docker sandbox applies strong defaults:

- **`network: none`** -- Containers have no network access by default. This is enforced at the kernel level and cannot be bypassed from inside the container.
- **`read_only_rootfs: true`** -- The container's root filesystem is read-only. A writable `/tmp` is provided with `noexec,nosuid` flags and a 64MB size limit.
- **`pids-limit: 256`** -- Limits the number of processes inside the container to prevent fork bombs.
- **Working directory** -- The tool's working directory is bind-mounted at `/work` inside the container. The `/work` target is reserved and cannot be used in `bind_mounts`.

## Network Isolation

The `network` field controls container networking:

| Value | Behavior |
|-------|----------|
| `none` | No network access (strongest isolation). |
| `bridge` | Container gets its own network namespace with NAT. Can access external hosts. |
| `host` | Container shares the host's network namespace. Least isolated. |

### Interaction with `network_disabled`

The Python tool has an existing `network_disabled` option that installs an in-process audit hook to block socket connections. When Docker is enabled:

- **`network: none`** -- Docker provides kernel-level network isolation. The in-process shim is skipped (redundant).
- **`network: bridge` or `host`** -- If `network_disabled: true`, the in-process shim is preserved inside the container for defense-in-depth.

## Blocked Extra Args

The following `docker run` flags are blocked in `extra_args` to prevent privilege escalation:

- `--privileged`
- `--cap-add`
- `--security-opt`
- `--pid=host`
- `--userns=host`
- `--network=host`
- `--ipc=host`

Attempting to use these raises a validation error at role load time.

## Examples

### Data Processing with File Access

```yaml
security:
  docker:
    enabled: true
    image: python:3.12-slim
    network: none
    memory_limit: 512m
    cpu_limit: 2.0
    bind_mounts:
      - source: ./data
        target: /data
        read_only: true
      - source: ./output
        target: /output
        read_only: false
    env_passthrough: [LANG, TZ]
```

### Minimal Sandbox

```yaml
security:
  docker:
    enabled: true
```

Uses all defaults: `python:3.12-slim`, no network, 256MB RAM, 1 CPU, read-only rootfs.

### Custom Image with Extra Args

```yaml
security:
  docker:
    enabled: true
    image: node:20-slim
    memory_limit: 1g
    read_only_rootfs: false
    extra_args: ["--pids-limit=100", "--ulimit=nofile=1024"]
```

### Complete Example Role

See [`examples/roles/docker-sandbox.yaml`](../../examples/roles/docker-sandbox.yaml) for a ready-to-use role with Docker isolation:

```bash
initrunner run examples/roles/docker-sandbox.yaml -p "Use python to compute 2**100"
```

## How It Works

When `security.docker.enabled` is `true`:

1. **Startup validation** -- `build_toolsets()` calls `require_docker()` to verify the Docker CLI and daemon are available. If not, the agent fails to load.

2. **Shell tools** -- Instead of `subprocess.run(tokens, ...)`, the tool runs `docker run --rm <image> <tokens>`. The working directory is bind-mounted at `/work`.

3. **Python tools** -- Code is written to a temporary file, bind-mounted at `/code/_run.py`, and executed via `docker run --rm <image> python /code/_run.py`. The temp directory is always cleaned up.

4. **Script tools** -- The script body is piped via stdin to `docker run -i --rm <image> <interpreter>`. Script environment variables are passed as `-e` flags.

All three paths reuse the existing timeout handling, output formatting, and truncation logic. `SubprocessTimeout` is raised on timeout just as in the non-Docker path.

## Custom Image Requirements

When using a custom `image`, the image must meet these requirements:

- **Interpreter on PATH** -- The Python tool expects `python` on `PATH`. The script tool uses the configured `interpreter` (default `/bin/sh`). If the interpreter is missing, the container exits with "not found".
- **Writable /tmp** -- When `read_only_rootfs: true` (default), a writable `/tmp` is provided as a tmpfs (64MB, noexec, nosuid). The image does not need to provide `/tmp` itself.
- **Working directory at /work** -- The tool's working directory is bind-mounted at `/work`. Your image should not expect a specific working directory.
- **Code mount at /code** -- Python tool code is mounted at `/code/_run.py` (read-only).
- **No special init system needed** -- InitRunner passes `--init` (tini) automatically.

## Limitations

- **Docker overhead** -- Container startup adds latency (~100-500ms per invocation depending on image and system). Not suitable for high-frequency tool calls.
- **Image pre-pull** -- The image is pulled automatically at agent startup if not locally available. For large images, pre-pull with `docker pull <image>` to avoid startup delay.
- **No GPU passthrough** -- The sandbox does not configure `--gpus`. Add `--gpus=all` via `extra_args` if needed (note: this reduces isolation).
- **Host paths** -- Bind mount source paths must exist on the host. Missing sources raise an error at container start time. Relative paths resolve against the role file's directory.
