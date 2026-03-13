# Docker

InitRunner is available on [GHCR](https://ghcr.io/vladkesler/initrunner) and [Docker Hub](https://hub.docker.com/r/vladkesler/initrunner). The image ships with all extras pre-installed.

## Quick start

```bash
# Interactive chat with memory
docker run --rm -it -e OPENAI_API_KEY \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest chat

# Chat with cherry-picked tools
docker run --rm -it -e OPENAI_API_KEY \
    -v initrunner-data:/data -v .:/workspace \
    ghcr.io/vladkesler/initrunner:latest \
    chat --tools git --tools filesystem

# Enable all built-in tools at once
#   chat --tool-profile all
```

## RAG (document chat)

```bash
# Chat with your documents (instant RAG)
docker run --rm -it -e OPENAI_API_KEY \
    -v initrunner-data:/data -v ./docs:/docs \
    ghcr.io/vladkesler/initrunner:latest chat --ingest /docs

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
    chat --telegram
```

## API server

```bash
# OpenAI-compatible API server on port 8000
docker run -d -e OPENAI_API_KEY -v ./roles:/roles \
    -p 8000:8000 ghcr.io/vladkesler/initrunner:latest \
    serve /roles/my-agent.yaml --host 0.0.0.0
```

## Web dashboard

```bash
# Web dashboard at http://localhost:8420
docker run -d -e OPENAI_API_KEY -v ./roles:/roles -v initrunner-data:/data \
    -p 8420:8420 ghcr.io/vladkesler/initrunner:latest ui --role-dir /roles
```

## Docker Compose

Use `docker compose up` with the included [`docker-compose.yml`](../../docker-compose.yml) (copy [`examples/.env.example`](../../examples/.env.example) to `.env` first). Example roles are seeded automatically on first boot. To use your own roles, uncomment the `./roles:/data/roles` volume mount in the compose file.

For authorization with Cerbos policies, use `docker compose -f docker-compose.cerbos.yml up`. See [Cerbos Authorization](../security/cerbos.md#docker-compose) for details.

## Docker sandbox for tool execution

Shell, Python, and script tools can run inside Docker containers for kernel-level isolation — network namespaces, cgroups, read-only rootfs, memory/CPU limits. Enable it in your role YAML:

```yaml
security:
  docker:
    enabled: true        # run tools in containers
    image: python:3.12-slim
    network: none        # no network access
    memory_limit: 256m
    cpu_limit: 1.0
    read_only_rootfs: true
    bind_mounts:
      - source: ./data
        target: /data
        read_only: true
```

Run `initrunner doctor` to verify Docker is available. See [Docker Sandbox](../security/docker-sandbox.md) for the full configuration reference.
