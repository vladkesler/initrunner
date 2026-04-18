# Bubblewrap Sandbox

Bubblewrap (`bwrap`) is a daemonless Linux sandbox built on user namespaces. It isolates tool subprocesses without root, a container runtime, or a background service. On Linux, `backend: auto` picks it.

For the shared config reference and migration guide, see [Runtime Sandbox](sandbox.md). For the container-based alternative, see [Docker Sandbox](docker-sandbox.md).

## Why bubblewrap

- **No daemon, no root.** `bwrap` is a setuid binary that creates unprivileged user namespaces. Nothing runs in the background. No Docker Desktop, no socket.
- **Fast startup.** A sandbox costs roughly one `fork+execve` plus namespace setup. No image pull, no container runtime, no layered filesystem.
- **Minimal surface.** The binary does one thing: assemble a namespace and exec the command.

## Requirements

Bubblewrap is Linux-only and needs unprivileged user namespaces enabled in the kernel. Install:

| Distro | Command |
|---|---|
| Debian/Ubuntu | `apt install bubblewrap` |
| Fedora | `dnf install bubblewrap` |
| Arch | `pacman -S bubblewrap` |
| Alpine | `apk add bubblewrap` |

If the preflight probe fails, one of two sysctls is usually the cause. initrunner's error reads both and tells you which; here they are:

### The kernel disables user namespaces

Some older or hardened kernels ship with user namespaces off:

```bash
sudo sysctl -w kernel.unprivileged_userns_clone=1
# persistent:
echo 'kernel.unprivileged_userns_clone=1' | sudo tee /etc/sysctl.d/00-local-userns.conf
```

### AppArmor blocks user namespaces (Ubuntu 24.04+, Debian 13)

Ubuntu 24.04 shipped `kernel.apparmor_restrict_unprivileged_userns=1` in April 2024. User namespaces are a recurring source of kernel privilege-escalation CVEs — an attacker becomes fake-root inside a userns, then exploits a bug that forgets to check which namespace. The hardening limits userns to processes covered by an AppArmor profile that grants `userns` capability.

The symptom is a probe failure like `bwrap: setting up uid map: Permission denied`. Pick one of three fixes:

1. **Install an AppArmor profile for bwrap** (recommended — keeps the system-wide hardening):
   ```bash
   sudo apt install --reinstall bubblewrap apparmor
   sudo systemctl reload apparmor
   ```
   The Debian/Ubuntu `bubblewrap` package ships a profile on recent releases. Reinstalling ensures it's loaded.

2. **Relax the global restriction** (reduces hardening for every app on the host):
   ```bash
   sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
   # persistent:
   echo 'kernel.apparmor_restrict_unprivileged_userns=0' | \
     sudo tee /etc/sysctl.d/60-apparmor-userns.conf
   ```

3. **Switch the role** to `backend: docker` or `backend: auto`. `auto` tries bwrap and falls back to Docker when bwrap can't run.

For bundles that must run on mixed hosts, `backend: auto` is the safest default: bwrap on Linux hosts where it works, Docker everywhere else, no sysctl edits required.

## Enabling it

```yaml
security:
  sandbox:
    backend: bwrap          # or: auto (prefers bwrap on Linux, falls back to Docker)
    network: none           # unshare-net: no routes, no sockets
    memory_limit: 256m
    cpu_limit: 1.0
    allowed_read_paths: []
    allowed_write_paths: []
    bind_mounts: []
    env_passthrough: []
```

The schema doesn't expose a `bwrap.extra_args` field. Raw bwrap flags can defeat the sandbox — `--bind / /` undoes the mount namespace — so they stay out of reach.

## Isolation model

Every `bwrap` invocation creates fresh namespaces and mounts before executing the tool command:

- `--unshare-user` — new user namespace; the tool runs as a fake root with no host privileges.
- `--unshare-pid` — new PID namespace; the tool cannot see or signal host processes.
- `--unshare-uts` `--unshare-ipc` `--unshare-cgroup` — isolates hostname, SysV IPC, and cgroup view.
- `--die-with-parent` — if initrunner exits, the sandboxed process dies with it (no orphans).
- `--new-session` — attached only when stdin is not a TTY, to avoid breaking interactive sessions.

### Filesystem layout

| Mount | Source | Mode |
|---|---|---|
| `/usr`, `/bin`, `/lib`, `/lib64` | Host | read-only |
| `/etc/resolv.conf`, `/etc/ssl/certs`, `/etc/alternatives` | Host | read-only |
| `/work` | Tool's `cwd` | read-write |
| `/role` | Role directory | read-only (when a role is loaded) |
| `/tmp` | tmpfs | read-write |
| `/proc` | new proc namespace | read-only |
| `/dev` | minimal devtmpfs (null, zero, random, urandom, tty, full) | read-only |
| `allowed_read_paths` | Host paths | read-only |
| `allowed_write_paths` | Host paths | read-write |
| `bind_mounts` | Host paths (per entry) | per `read_only` flag |

initrunner creates paths under `allowed_*` and `bind_mounts` on the host if they don't exist, so bind-mounting never fails on a missing source.

### Network

| `network:` | Behavior |
|---|---|
| `none` | Adds `--unshare-net`. The sandbox has no interfaces beyond loopback, no routes, no DNS. |
| `host` | No network namespace. The sandbox shares the host's network — useful for tools that need your normal DNS/proxy setup. |
| `bridge` | **Not supported.** bwrap has no bridge-networking mode. Raises `SandboxConfigError` at runtime. Use `backend: docker` if you need bridge networking. |

### Environment

The sandbox starts with `--clearenv` — no host environment leaks in. Only these keys pass through:

1. The always-on allowlist: `PATH`, `HOME`, `LANG`, `TERM`.
2. Anything listed in `env_passthrough`.
3. Whatever the tool sets explicitly via its `env` arg (e.g. `PYTHONDONTWRITEBYTECODE`).

`scrub_env()` filters the whole set first, dropping entries that match `sensitive_env_prefixes` (`OPENAI_API_KEY`, `AWS_SECRET`, `DATABASE_URL`, …). Docker behaves the same, so presets carry over across backends.

### Resource limits

initrunner wraps the command in `systemd-run --user --scope` to enforce `memory_limit` and `cpu_limit`:

```
systemd-run --user --scope --quiet \
  -p MemoryMax=256m \
  -p CPUQuota=100% \
  -- bwrap ... -- /bin/python /work/_run.py
```

If `systemd-run --user` fails — non-systemd distros, CI without a user instance, inside some containers — initrunner logs one warning per role load and skips limit enforcement. The sandbox itself still runs. There's no prlimit/ulimit fallback: the warning surfaces the gap instead of silently half-enforcing.

## Preflight

`sandbox.backend: bwrap` (and `auto` on Linux) runs a functional probe before launching any tool:

```bash
bwrap --ro-bind /usr /usr -- /bin/true
```

This catches kernel-disabled user namespaces, AppArmor restrictions, and broken installs that a bare `which bwrap` check misses. On failure, initrunner raises `SandboxUnavailableError` with install and sysctl remediation.

`initrunner doctor --role <file>` runs the same probe and reports readiness without executing the agent.

## Mount validation tiers

Mounts fall into two categories:

1. **User-configured** (`allowed_read_paths`, `allowed_write_paths`, `bind_mounts` from role YAML). Validated at load time against the role's permitted roots via `validate_path_within()`. A typo'd or malicious `/etc` mount fails before the role loads.
2. **Tool-internal** (`extra_mounts` passed by tool code — e.g. `python_exec` binding a tempfile to `/work/_run.py`). Code-controlled, not user-controlled; passes through without validation.

## Example: code interpreter

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: bwrap-python-runner
spec:
  role: |
    You are a code execution assistant running in a bubblewrap sandbox.
    No network access, read-only root filesystem, 256m memory, 1 CPU.
  model:
    provider: openai
    name: gpt-5-mini
  tools:
    - type: shell
      blocked_commands: []
    - type: python
  security:
    sandbox:
      backend: bwrap
      network: none
      memory_limit: 256m
      cpu_limit: 1.0
      allowed_read_paths:
        - /usr/share/dict
      allowed_write_paths:
        - /srv/workspace
```

Inside the sandbox:

- `python -c "open('/etc/shadow').read()"` → `PermissionError`. `/etc/shadow` isn't mounted.
- `python -c "import urllib.request; urllib.request.urlopen('https://example.com')"` → `OSError: Network is unreachable`. The network namespace is empty.
- `python -c "open('/srv/workspace/out.txt','w').write('ok')"` → succeeds. That path is bind-mounted read-write.
- `python -c "import os; print(os.environ.get('OPENAI_API_KEY'))"` → `None`. The host env was cleared.

## Audit

Each `run()` emits a `sandbox.exec` security event:

```
backend=bwrap argv0=/usr/bin/python rc=0 duration_ms=48
```

Query with:

```bash
initrunner audit security-events --event-type sandbox.exec
```

## When to pick bwrap vs docker

| You want… | Use |
|---|---|
| No daemon, no root, minimal setup on Linux | `bwrap` |
| Fastest per-call startup | `bwrap` |
| macOS, Windows, or non-Linux hosts | `docker` |
| Bridge networking with a custom Docker network | `docker` |
| A specific OS/runtime image (e.g. `python:3.12-slim`, `node:20`) | `docker` |
| Cross-host reproducibility of the sandbox environment | `docker` |
| Auto-detect at runtime | `auto` |

`backend: auto` is the recommended default for published bundles. It picks `bwrap` on Linux where user namespaces work and falls back to `docker` elsewhere. It never falls to `none`.

## Limitations

- **Linux only.** `sandbox.backend: bwrap` on macOS or Windows raises at load time. Use `docker` there.
- **No seccomp profile.** bwrap ships without a seccomp filter in v1. A determined tool can still make any syscall the kernel allows from inside its namespaces. Rely on filesystem + network isolation as the primary boundary.
- **No image pinning.** The sandbox inherits the host's `/usr` tree. Upgrading the host upgrades the sandbox. If you need reproducibility across hosts, use `docker` with a pinned image.
- **systemd-run dependency for limits.** Without it, `memory_limit`/`cpu_limit` are advisory. The sandbox still isolates the filesystem and network.
