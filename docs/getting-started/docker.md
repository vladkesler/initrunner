# Docker

InitRunner is available on [GHCR](https://ghcr.io/vladkesler/initrunner) and [Docker Hub](https://hub.docker.com/r/vladkesler/initrunner). The image ships with all extras pre-installed.

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

All examples below use `-e OPENAI_API_KEY` for brevity. Replace with `--env-file ~/.initrunner/.env` if your keys live there.

## Quick start

```bash
# Interactive chat with memory
docker run --rm -it -e OPENAI_API_KEY \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest run -i

# Chat with cherry-picked tools
docker run --rm -it -e OPENAI_API_KEY \
    -v initrunner-data:/data -v .:/workspace \
    ghcr.io/vladkesler/initrunner:latest \
    run -i --tools git --tools filesystem

# Enable all built-in tools at once
#   run -i --tool-profile all
```

## RAG (document chat)

```bash
# Chat with your documents (instant RAG)
docker run --rm -it -e OPENAI_API_KEY \
    -v initrunner-data:/data -v ./docs:/docs \
    ghcr.io/vladkesler/initrunner:latest run -i --ingest /docs

# Ingest documents for a role, then query
docker run --rm -e OPENAI_API_KEY \
    -v ./roles:/roles -v ./docs:/docs -v initrunner-data:/data \
    ghcr.io/vladkesler/initrunner:latest ingest /roles/rag-agent.yaml
docker run --rm -it -e OPENAI_API_KEY \
    -v ./roles:/roles -v initrunner-data:/data \
    ghcr.io/vladkesler/initrunner:latest run /roles/rag-agent.yaml -i
```

## Telegram bot

```bash
docker run -d -e OPENAI_API_KEY -e TELEGRAM_BOT_TOKEN \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest \
    run --bot telegram
```

## API server

```bash
# OpenAI-compatible API server on port 8000
docker run -d -e OPENAI_API_KEY -v ./roles:/roles \
    -p 8000:8000 ghcr.io/vladkesler/initrunner:latest \
    run /roles/my-agent.yaml --serve --host 0.0.0.0
```

## Web dashboard

```bash
# Web dashboard at http://localhost:8100
docker run -d -e OPENAI_API_KEY -v ./roles:/roles -v initrunner-data:/data \
    -p 8100:8100 ghcr.io/vladkesler/initrunner:latest \
    dashboard --expose --no-open --roles-dir /roles
```

## Using a different provider or model

Starter agents no longer hardcode a model. They auto-detect from your API key. To use a specific model (e.g. OpenRouter), set `INITRUNNER_MODEL`:

```bash
docker run --rm -it \
    -e OPENAI_API_KEY=sk-or-your-openrouter-key \
    -e OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
    -e INITRUNNER_MODEL=openai:google/gemini-3-flash-preview \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest run -i
```

Or use any supported provider directly:

```bash
# Anthropic
docker run --rm -it -e ANTHROPIC_API_KEY \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest run -i

# Google
docker run --rm -it -e GOOGLE_API_KEY \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest run -i
```

## Docker Compose

Use `docker compose up` with the included [`docker-compose.yml`](../../docker-compose.yml) (copy [`examples/.env.example`](../../examples/.env.example) to `.env` first). Example roles are seeded automatically on first boot. To use your own roles, uncomment the `./roles:/data/roles` volume mount in the compose file.

For agent policy enforcement, mount your policy directory and set `INITRUNNER_POLICY_DIR`. See [Agent Policy](../security/agent-policy.md) for details.

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
    run /roles/my-sandboxed-agent.yaml -p "compute 2**100"
```

Or in `docker-compose.yml`, uncomment the socket volume:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
  - initrunner-data:/data
```

Verify the sandbox is available with `initrunner doctor` -- the `docker` row should show `Ready`.

**Security warning:** Mounting `/var/run/docker.sock` gives the InitRunner container full control over the host's Docker daemon. This is Docker-socket passthrough, not true Docker-in-Docker. Only do this in trusted environments where the agent's role configuration is under your control.
