# Docker

InitRunner is available on [GHCR](https://ghcr.io/vladkesler/initrunner) and [Docker Hub](https://hub.docker.com/r/vladkesler/initrunner). The image ships with all extras pre-installed and the compiled web dashboard (the default command).

| Tag | What is in it | On disk |
|---|---|---|
| `latest`, `<version>` | Every extra: all providers, MCP, vector store, search, ingestion, channels, dashboard | 1.07 GB |
| `slim`, `<version>-slim` | Core runtime plus the dashboard: OpenAI and Ollama, every dependency-free tool, triggers, flows, teams, groups, `--serve` | 308 MB |

Use `slim` when you know what your roles need and none of it is MCP, vector
memory or ingestion. It also runs ~38 MB lighter, because the MCP client stack
loads whether or not a role uses it. A role that needs a missing extra fails at
load with the `uv pip install` line, so switching tags never fails silently.

One catch on `slim`: ephemeral mode (`initrunner run` with no role file) turns
on persistent memory by default, and that needs the vector extra. Pass
`--no-memory` to run it on `slim`, or use `latest`. Examples in this page that
name a role file are unaffected.

## Naming the command

The image's default command is `initrunner dashboard --expose --no-open`, and
its entrypoint runs whatever command it is given. Docker replaces the *whole*
default command when you pass your own, so every example below spells out
`initrunner` before the subcommand:

```bash
docker run ... ghcr.io/vladkesler/initrunner:latest run -i              # exec: run: not found
docker run ... ghcr.io/vladkesler/initrunner:latest initrunner run -i   # correct
```

The same applies to `command:` in Compose and to `command:`/`args:` in a
Kubernetes pod spec.

## API keys

The container needs API keys to reach your LLM provider. Three ways to pass them:

```bash
# 1. Inline (key exported in your shell)
docker run --rm -it -e OPENAI_API_KEY ...

# 2. From your initrunner setup (recommended if you ran `initrunner setup`)
docker run --rm -it --env-file ~/.initrunner/.env ...

# 3. Mount your entire initrunner config directory
#    The container reads /data/.env automatically (INITRUNNER_HOME=/data).
docker run --rm -it -v ~/.initrunner:/data ...
```

`--env-file` injects keys only. It does **not** copy `~/.initrunner/run.yaml`. If that file is absent and more than one provider key is set, auto-detect prefers Anthropic. Pin the model you want with `-e INITRUNNER_MODEL=openai:gpt-5-mini`, or use option 3 so the container sees `run.yaml`.

All examples below use `-e OPENAI_API_KEY` for brevity. Replace with `--env-file ~/.initrunner/.env` if your keys live there.

## Quick start

```bash
# Interactive chat with memory
docker run --rm -it -e OPENAI_API_KEY \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest initrunner run -i

# Chat with cherry-picked tools
docker run --rm -it -e OPENAI_API_KEY \
    -v initrunner-data:/data -v .:/workspace \
    ghcr.io/vladkesler/initrunner:latest \
    initrunner run -i --tools git --tools filesystem

# Enable all built-in tools at once
#   initrunner run -i --tool-profile all
```

## RAG (document chat)

```bash
# Chat with your documents (instant RAG)
docker run --rm -it -e OPENAI_API_KEY \
    -v initrunner-data:/data -v ./docs:/docs \
    ghcr.io/vladkesler/initrunner:latest initrunner run -i --ingest /docs

# Ingest documents for a role, then query
docker run --rm -e OPENAI_API_KEY \
    -v ./roles:/roles -v ./docs:/docs -v initrunner-data:/data \
    ghcr.io/vladkesler/initrunner:latest initrunner ingest /roles/rag-agent.yaml
docker run --rm -it -e OPENAI_API_KEY \
    -v ./roles:/roles -v initrunner-data:/data \
    ghcr.io/vladkesler/initrunner:latest initrunner run /roles/rag-agent.yaml -i
```

## Telegram bot

```bash
docker run -d -e OPENAI_API_KEY -e TELEGRAM_BOT_TOKEN \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest \
    initrunner run --bot telegram
```

## API server

```bash
# OpenAI-compatible API server on port 8000
docker run -d -e OPENAI_API_KEY -v ./roles:/roles \
    -p 8000:8000 ghcr.io/vladkesler/initrunner:latest \
    initrunner run /roles/my-agent.yaml --serve --host 0.0.0.0
```

## Web dashboard

This is the image default (`CMD`). `--expose` binds `0.0.0.0` and generates an API key if you do not set one; sign in at `/login` with the key printed in the container logs. `/api/health` stays unauthenticated.

```bash
# Web dashboard at http://localhost:8100
docker run -d -e OPENAI_API_KEY -v ./roles:/roles -v initrunner-data:/data \
    -p 8100:8100 ghcr.io/vladkesler/initrunner:latest \
    initrunner dashboard --expose --no-open --roles-dir /roles
```

## Using a different provider or model

Starter agents no longer hardcode a model. They auto-detect from your API key. To use a specific model (e.g. OpenRouter), set `INITRUNNER_MODEL`:

```bash
docker run --rm -it \
    -e OPENAI_API_KEY=sk-or-your-openrouter-key \
    -e OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
    -e INITRUNNER_MODEL=openai:google/gemini-3-flash-preview \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest initrunner run -i
```

Or use any supported provider directly:

```bash
# Anthropic
docker run --rm -it -e ANTHROPIC_API_KEY \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest initrunner run -i

# Google
docker run --rm -it -e GOOGLE_API_KEY \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest initrunner run -i
```

## Docker Compose

Use `docker compose up` with the included [`docker-compose.yml`](../../docker-compose.yml) (copy [`examples/.env.example`](../../examples/.env.example) to `.env` first). Example roles are seeded automatically on first boot. To use your own roles, uncomment the `./roles:/data/roles` volume mount in the compose file.

For agent policy enforcement, mount your policy directory and set `INITRUNNER_POLICY_DIR`. See [Agent Policy](../security/agent-policy.md) for details.

## Sizing the container

Memory limits count RSS, and RSS x time x replicas is the bill. Serving
`hello-world.yaml`, measured with `docker stats`:

```console
$ docker run -d --name agent -m 256m -e OPENAI_API_KEY -p 8000:8000 \
    ghcr.io/vladkesler/initrunner:slim \
    initrunner run /opt/initrunner/example-roles/hello-world.yaml --serve --host 0.0.0.0

$ docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' agent
agent 127.1MiB / 256MiB
```

Rules of thumb, all worth re-measuring against your own roles with ~30% headroom:

- **256m** for a plain agent, or a whole [group](../orchestration/groups.md) of
  them: members share the imported stack, so each extra agent costs under 1 MB.
- **512m** for a role with `ingest:` or vector `memory:`, which loads LanceDB
  when the store opens. The same hello-world shape with vector memory measures
  212 MiB idle on `:latest`, so 256m leaves nothing for an ingestion run.
- `MALLOC_ARENA_MAX=2` is already set in the image. It caps glibc's per-thread
  malloc arenas, which otherwise inflate RSS well past the live heap in a
  threaded Python process.

Both images seed `hello-world.yaml` and `code-reviewer.yaml` into `/data/roles`
on first boot -- the two examples that run on any install. Mount your own roles
at `/data/roles` and nothing is copied.

See [Memory Footprint](../operations/memory-footprint.md) for where the memory
goes and how to measure it.

### A CronJob against a warm server

The expensive pattern in Kubernetes is a CronJob that runs `initrunner run` on
every tick: each invocation pays the full ~110 MB import cost and several
seconds of startup, 1,440 times a day for a per-minute schedule. Keep one warm
server and have the CronJob call it:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: hourly-digest
spec:
  schedule: "0 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: call
              image: curlimages/curl:8.11.1
              resources:
                requests: {memory: 16Mi}
                limits: {memory: 32Mi}
              env:
                - name: API_KEY
                  valueFrom:
                    secretKeyRef: {name: desk-api, key: api-key}
              args:
                - -sSf
                - -H
                - "Authorization: Bearer $(API_KEY)"
                - -H
                - "Content-Type: application/json"
                - -d
                - '{"model":"digest","messages":[{"role":"user","content":"write the daily digest"}]}'
                - http://desk:8000/v1/chat/completions
```

The `desk` Deployment is the one from
[Grouped agents](../orchestration/groups.md#deploying-with-kubernetes-or-argo-cd),
serving every agent from one process. The CronJob pod is a 16 MB curl container.

If the schedule belongs to the agent rather than to the cluster, a
[cron trigger](../core/triggers.md) with `--daemon` keeps it all in the one
process and needs no CronJob at all.

## Docker sandbox for tool execution

Shell, Python, and script tools can run inside Docker containers for kernel-level isolation -- network namespaces, cgroups, read-only rootfs, memory/CPU limits. Enable it in your role YAML:

```yaml
security:
  sandbox:
    backend: docker      # run tools in containers
    network: none        # no network access
    memory_limit: 256m
    cpu_limit: 1.0
    read_only_rootfs: true
    bind_mounts:
      - source: ./data
        target: /data
        read_only: true
    docker:
      image: python:3.12-slim
```

Run `initrunner doctor` to verify Docker is available. See [Docker Sandbox](../security/docker-sandbox.md) for the full configuration reference. On Linux, you can also use [Bubblewrap](../security/bubblewrap.md) (`backend: bwrap`) to skip Docker entirely.

### Docker sandbox when running InitRunner in Docker (socket passthrough)

If you run InitRunner itself in a Docker container and want to use the sandbox feature, you must mount the host's Docker socket so the container can spawn sibling containers:

```bash
# Run a sandboxed role from inside Docker
docker run --rm -it \
    --env-file ~/.initrunner/.env \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v ./roles:/roles \
    -v initrunner-data:/data \
    ghcr.io/vladkesler/initrunner:latest \
    initrunner run /roles/my-sandboxed-agent.yaml -p "compute 2**100"
```

Or in `docker-compose.yml`, uncomment the socket volume:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
  - initrunner-data:/data
```

Verify the sandbox is available with `initrunner doctor` -- the `docker` row should show `Ready`.

**Security warning:** Mounting `/var/run/docker.sock` gives the InitRunner container full control over the host's Docker daemon. This is Docker-socket passthrough, not true Docker-in-Docker. Only do this in trusted environments where the agent's role configuration is under your control.
