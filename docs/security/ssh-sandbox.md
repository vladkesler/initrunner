# SSH backend

SSH is **remote execution, not a kernel sandbox.** It runs your agent's tool subprocesses on an existing host with whatever isolation that host already provides. Use it to choose *where* code runs (a build server, a GPU box, a customer staging VM), not to contain untrusted code.

If you need isolation, use [bwrap](bubblewrap.md) or [docker](docker-sandbox.md).

## Quickstart

```yaml
# role.yaml
security:
  sandbox:
    backend: ssh
    ssh:
      host: my-build-box       # alias from ~/.ssh/config, or user@hostname
      remote_cwd: /srv/work    # optional working directory on the remote host
```

That's the minimum. The host alias is resolved through your existing `~/.ssh/config` and `ssh-agent`. No keys live in InitRunner config.

```bash
# Sanity-check the connection separately
ssh -o BatchMode=yes my-build-box true && echo OK
```

## Configuration reference

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | string | required | Host alias from `~/.ssh/config` or `user@hostname`. |
| `remote_cwd` | string \| null | `null` | Working directory for every remote command. If unset, the SSH login directory is used. |
| `identity_file` | string \| null | `null` | Override `IdentityFile`. Prefer setting this in `~/.ssh/config` instead. |
| `config_file` | string \| null | `null` | Override `~/.ssh/config` path (rarely needed). |
| `connect_timeout` | int | `10` | Seconds for the initial connection. |
| `control_persist` | string | `"60s"` | How long the multiplexed connection stays warm between calls. Pass any OpenSSH duration. |

## How it works

Every tool call shells out to `ssh -- <host> <remote-command>` with `ControlMaster=auto` so the second and subsequent calls reuse a warm connection. Per-call latency on a fresh socket is ~150–500ms; reused, it's tens of ms.

The remote command is constructed as:

```
[cd <remote_cwd> && ] [env VAR=val ...] <argv...>
```

`argv` and the `env` mapping that the tool passed in are shell-quoted with `shlex.quote`. Sensitive env keys (anything matching the same prefix/suffix list other backends use — `*_KEY`, `*_TOKEN`, `OPENAI_API_KEY`, `AWS_*`, etc.) are stripped from the remote env before it leaves the local machine.

## Authentication

InitRunner does not handle SSH auth. The local `ssh` process inherits the parent environment unchanged, including `SSH_AUTH_SOCK` and `SSH_AGENT_PID`, so:

- `ssh-agent` and `ssh-add` work as you'd expect.
- `~/.ssh/config` `Host` blocks are honored (`User`, `Port`, `IdentityFile`, `ProxyJump`, `ForwardAgent`, etc.).
- Hardware keys, FIDO/U2F, and OpenSSH certificate auth all work because they work in your shell.

If you set `identity_file` in YAML, it's threaded through as `ssh -i <path>`.

## What is NOT supported (v1)

These fields/concepts don't apply to a real remote filesystem and are explicitly rejected at config load:

| Field | Reason |
|---|---|
| `bind_mounts` | No shared filesystem. v1.1 will add SCP staging. |
| `allowed_read_paths` | Same. |
| `allowed_write_paths` | Same. |
| `network: bridge` | SSH cannot enforce remote network policy. Use `none` (informational) or `host`. |

These fields are accepted but **inert** under SSH (kept so `backend: ssh` can be added to an existing role without touching unrelated config):

- `read_only_rootfs` — does nothing; the remote rootfs is whatever it is.
- `memory_limit`, `cpu_limit` — no remote enforcement in v1.
- `docker.*` — ignored.

### Tools that don't work over SSH (v1)

- `python_exec` — stages a local file and bind-mounts it as `/work/_run.py`. Without SCP staging there's no way to deliver the file. The tool fails fast with a v1.1 remediation message. **Workaround**: install Python on the remote host and use `shell` with `python -c "..."` or check a script into the remote machine ahead of time.
- Anything else that uses `extra_mounts`. The backend rejects non-empty `extra_mounts` at runtime with a clear `SandboxConfigError`.

## Coming in v1.1

- Stdin-piped `python_exec` (no filesystem staging).
- SCP-based mount staging for `extra_mounts`.

## Security posture

This is the bit that bites if you skim. SSH does **not**:

- isolate the agent's commands from the rest of the remote host's filesystem,
- enforce memory or CPU limits,
- prevent network access,
- contain a malicious or buggy tool.

Use it for trusted-but-remote execution. If your role's tools could be coaxed into running attacker-controlled commands, run those tools through `bwrap` or `docker` on a host you don't mind compromising — not via SSH on production infrastructure.

## Audit

Every remote call logs a `sandbox.exec` event with `backend=ssh host=<host> argv0=<first-token> rc=<n> duration_ms=<ms>`. Identity files, full argv arguments, and command output are not logged.

## Troubleshooting

`ssh client not found on PATH` — install OpenSSH (`apt install openssh-client`, `brew install openssh`, or `dnf install openssh-clients`).

`ssh probe to '<host>' returned rc=255` — usually auth or hostname. Reproduce out-of-band:

```bash
ssh -o BatchMode=yes -v <host> true
```

`ssh-agent` not running — `ssh-add -l` should list a key. If it says "Could not open a connection to your authentication agent," start one (`eval "$(ssh-agent -s)"`) and `ssh-add` your key.

ControlMaster socket lingering after a crash — the per-process temp dir under `/tmp/initrunner-ssh-*` is cleaned up on normal shutdown. If a hard kill leaves one behind, delete the directory or run `ssh -O exit <host>` once.
