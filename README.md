# InitRunner — The AI Agent Runner

<p align="center"><img src="assets/mascot.png" alt="InitRunner mascot" width="300"></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-3776ab?logo=python&logoColor=white" alt="Python 3.11+">
  <a href="https://pypi.org/project/initrunner/"><img src="https://img.shields.io/pypi/v/initrunner?color=%2334D058" alt="PyPI version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-%2334D058" alt="MIT License"></a>
  <a href="tests/"><img src="https://img.shields.io/badge/tests-710+-%2334D058" alt="Tests"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-d4aa00?logo=ruff&logoColor=white" alt="Ruff"></a>
  <a href="https://ai.pydantic.dev/"><img src="https://img.shields.io/badge/PydanticAI-6e56cf?logo=pydantic&logoColor=white" alt="PydanticAI"></a>
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Beta">
  <a href="https://initrunner.ai/"><img src="https://img.shields.io/badge/website-initrunner.ai-blue" alt="Website"></a>
</p>

<p align="center">
  <a href="https://initrunner.ai/">Website</a> · <a href="https://initrunner.ai/docs">Docs</a> · <a href="https://github.com/vladkesler/initrunner/issues">Issues</a>
</p>

**Define AI agents like CI pipelines. YAML in, autonomous agents out.**

Your agent is a YAML file. Its tools, knowledge base, memory, and triggers — all config, not code. Deploy it as a CLI tool, a cron-driven daemon, or an OpenAI-compatible API. Compose agents into pipelines. RAG and long-term memory come batteries-included. Manage, chat, and audit from a web dashboard or terminal TUI.

> **Note:** InitRunner is in early release (v0.2.0). APIs may change between minor versions.

## Table of Contents

- [See It in Action](#see-it-in-action)
- [Why InitRunner](#why-initrunner)
- [From Simple to Powerful](#from-simple-to-powerful)
- [Community Roles](#community-roles)
- [Install & Quickstart](#install--quickstart)
- [Docker](#docker)
- [Core Concepts](#core-concepts)
- [CLI Quick Reference](#cli-quick-reference)
- [Documentation](#documentation)
- [Examples](#examples)
- [Community & Support](#community--support)
- [Contributing](#contributing)
- [License](#license)

## See It in Action

A code reviewer that can read your files and inspect git history — one YAML file:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: code-reviewer
  description: Reviews code for bugs and style issues
spec:
  role: |
    You are a senior engineer. Review code for correctness and readability.
    Use git tools to examine changes and read files for context.
  model: { provider: openai, name: gpt-4o-mini }
  tools:
    - type: git
      repo_path: .
    - type: filesystem
      root_path: .
      read_only: true
```

```bash
initrunner run reviewer.yaml -p "Review the latest commit"
```

That's it. No Python, no boilerplate. The same file also runs as an interactive chat (`-i`), a trigger-driven daemon, or an OpenAI-compatible API server.

## Why InitRunner

**Config, not code** — Define your agent's tools, knowledge base, and memory in one YAML file. No framework boilerplate, no wiring classes together. 13+ built-in tools (filesystem, git, HTTP, Python, shell, SQL, MCP) work out of the box. Need a custom tool? One file, one decorator.

**Version-control your agents** — Agent configs are plain text. Diff them, review them in PRs, validate in CI, reproduce anywhere. Your agent definition lives next to your code.

**Prototype to production** — Same YAML runs as an interactive chat, a one-shot CLI command, a trigger-driven daemon, or an OpenAI-compatible API. No rewrite when you're ready to deploy.

## From Simple to Powerful

Start with the code-reviewer above. Each step adds one capability — no rewrites, just add a section to your YAML.

### 1. Add knowledge & memory

Point at your docs for RAG — a `search_documents` tool is auto-registered. Add `memory` for persistent recall across sessions:

```yaml
spec:
  ingest:
    sources: ["./docs/**/*.md", "./docs/**/*.pdf"]
  memory:
    store_path: ./memory.db
    max_memories: 1000
```

```bash
initrunner ingest role.yaml   # extract | chunk | embed | store
initrunner run role.yaml -i --resume   # search_documents + memory ready
```

### 2. Add skills

Compose reusable bundles of tools and prompts. Each skill is a `SKILL.md` file — reference it by path:

```yaml
spec:
  skills:
    - ../skills/web-researcher
    - ../skills/code-tools.md
```

The agent inherits each skill's tools and prompt instructions automatically.

### 3. Add triggers

Turn it into a daemon that reacts to events:

```yaml
spec:
  triggers:
    - type: cron
      schedule: "0 9 * * 1"
      prompt: "Generate the weekly status report."
    - type: file_watch
      paths: [./src]
      prompt_template: "File changed: {path}. Review it."
```

```bash
initrunner daemon role.yaml   # runs until stopped
```

### 4. Compose agents

Orchestrate multiple agents into a pipeline. One agent's output feeds into the next:

```yaml
apiVersion: initrunner/v1
kind: Compose
spec:
  services:
    inbox-watcher:
      role: roles/inbox-watcher.yaml
      sink: { type: delegate, target: triager }
    triager:
      role: roles/triager.yaml
```

```bash
initrunner compose up pipeline.yaml
```

### 5. Serve as an API

Turn any agent into an OpenAI-compatible endpoint. Drop-in for Open WebUI, Vercel AI SDK, or any OpenAI-compatible client:

```bash
initrunner serve support-agent.yaml --port 3000
```

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:3000/v1", api_key="unused")
response = client.chat.completions.create(
    model="support-agent",
    messages=[{"role": "user", "content": "How do I reset my password?"}],
)
```

## Community Roles

Browse, install, and run roles shared by the community — no copy-paste needed:

```bash
initrunner search "code review"       # browse the community index
initrunner install code-reviewer      # download, validate, confirm
initrunner run ~/.initrunner/roles/code-reviewer.yaml -i
```

Install directly from any GitHub repo:

```bash
initrunner install user/repo:roles/support-agent.yaml@v1.0
```

Every install shows a security summary (tools, model, author) and asks for confirmation before saving. See [docs/agents/registry.md](docs/agents/registry.md) for source formats, the community index, and update workflows.

## Install & Quickstart

**1. Install**

```bash
curl -fsSL https://initrunner.ai/install.sh | sh
```

Or with a package manager:

```bash
pip install initrunner
# or
uv tool install initrunner
# or
pipx install initrunner
```

Common extras:

| Extra | What it adds |
|-------|--------------|
| `initrunner[anthropic]` | Anthropic provider (Claude) |
| `initrunner[ingest]` | PDF, DOCX, XLSX ingestion |
| `initrunner[dashboard]` | Web dashboard (FastAPI + Next.js) |

See [docs/getting-started/installation.md](docs/getting-started/installation.md) for the full extras table, dev setup, and environment configuration.

**2. Create your first agent** (`code-reviewer.yaml`)

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: code-reviewer
  description: An experienced code review agent
spec:
  role: |
    You are a senior engineer. Review code changes for correctness,
    readability, and potential bugs. Be constructive.
  model: { provider: openai, name: gpt-4o-mini }
  tools:
    - type: git
      repo_path: .
      read_only: true
    - type: filesystem
      root_path: .
      read_only: true
```

**3. Set your API key and run**

```bash
export OPENAI_API_KEY=sk-...
initrunner run code-reviewer.yaml -p "Review the last 3 commits"
```

Start an interactive chat with `-i`, or use `initrunner setup` for a guided wizard. See [docs/getting-started/setup.md](docs/getting-started/setup.md) for provider setup.

## Docker

Run InitRunner without installing Python — just Docker:

```bash
# One-shot prompt
docker run --rm -e OPENAI_API_KEY \
    -v ./roles:/roles ghcr.io/vladkesler/initrunner:latest \
    run /roles/my-agent.yaml -p "Hello"

# Interactive chat
docker run --rm -it -e OPENAI_API_KEY \
    -v ./roles:/roles ghcr.io/vladkesler/initrunner:latest \
    run /roles/my-agent.yaml -i

# Web dashboard
docker run -d -e OPENAI_API_KEY \
    -v ./roles:/roles -v initrunner-data:/data \
    -p 8420:8420 ghcr.io/vladkesler/initrunner:latest \
    ui --role-dir /roles
```

Or use the included `docker-compose.yml` to start the dashboard with persistent storage:

```bash
# Set API keys in .env or export them, then:
docker compose up
```

Build the image locally:

```bash
docker build -t initrunner .
docker run --rm initrunner --version
```

The default image includes dashboard, ingestion, all model providers, and safety extras. Override with `--build-arg EXTRAS="dashboard,anthropic"` to customize. Using Ollama on the host? Use `http://host.docker.internal:11434/v1` as the model endpoint.

## Core Concepts

### Role files

Every agent is a YAML file with four top-level keys:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: my-agent
  description: What this agent does
spec:
  role: "System prompt goes here."
  model: { provider: openai, name: gpt-4o-mini }
  tools: [...]
  guardrails: { max_tool_calls: 20, timeout_seconds: 300 }
```

Validate with `initrunner validate role.yaml` or scaffold one with `initrunner init --name my-agent`.

### Tools

Tools are configured in `spec.tools`. The most common ones:

| Type | What it does |
|------|-------------|
| `filesystem` | Read/write files within a root directory |
| `git` | Git log, diff, blame, show (read-only by default) |
| `http` | HTTP requests to a base URL |
| `python` | Run Python in an isolated subprocess |
| `shell` | Run shell commands with allowlist/blocklist |
| `mcp` | Connect to MCP servers (stdio, SSE, streamable-http) |
| `sql` | Query SQLite databases (read-only by default) |
| `delegate` | Hand off to other agents |

See [docs/agents/tools.md](docs/agents/tools.md) for the full reference.

### Creating tools

Add a built-in tool by creating a single file in `initrunner/agent/tools/` with a config class and a `@register_tool` decorated builder function. The tool is auto-discovered and immediately available in role YAML — no other files need editing. Tools use [PydanticAI's FunctionToolset](https://ai.pydantic.dev/tools/) under the hood. See [docs/agents/tool_creation.md](docs/agents/tool_creation.md) for the full guide, including custom tools loaded from external modules, declarative API tools, and the plugin registry.

### Skills

Skills are reusable bundles of tools and prompts packaged as `SKILL.md` files. They let you compose capabilities across agents without duplicating configuration. Reference them from a role with `spec.skills`:

```yaml
spec:
  skills:
    - ../skills/web-researcher
    - ../skills/code-tools.md
```

See [docs/agents/skills_feature.md](docs/agents/skills_feature.md) for skill file format, resolution rules, and examples.

### Run modes

| Mode | Command | Use case |
|------|---------|----------|
| Single-shot | `initrunner run role.yaml -p "prompt"` | One question, one answer |
| Interactive | `initrunner run role.yaml -i` | Multi-turn chat (REPL) |
| Daemon | `initrunner daemon role.yaml` | Trigger-driven (cron, file watch, webhook) |
| API server | `initrunner serve role.yaml` | OpenAI-compatible HTTP API |

### RAG & Memory

**Document ingestion** — add `spec.ingest` to your role pointing at your documents, then run `initrunner ingest role.yaml` to extract, chunk, embed, and store locally in SQLite (powered by `sqlite-vec`). A `search_documents` tool is automatically registered so the model can query the knowledge base at runtime. See [docs/core/ingestion.md](docs/core/ingestion.md) for custom embedding models, URL sources, and chunking strategies.

**Long-term memory** — add `spec.memory` to your role and the agent gets `remember()`, `recall()`, and `list_memories()` tools. Use `--resume` to continue previous REPL sessions. See [docs/core/memory.md](docs/core/memory.md).

### Triggers & Compose

**Triggers** let daemons react to events — cron schedules, file changes, or webhooks. See [docs/core/triggers.md](docs/core/triggers.md).

**Compose** orchestrates multiple agents as a pipeline with delegate sinks, health checks, and restart policies. Deploy with `compose up` (foreground) or `compose install` (systemd). See [docs/orchestration/agent_composer.md](docs/orchestration/agent_composer.md).

### Providers

The default provider is OpenAI (`gpt-4o-mini`). Switch providers by changing `spec.model` in your role file and installing the relevant extra (e.g. `pip install initrunner[anthropic]`). See [docs/configuration/providers.md](docs/configuration/providers.md) for Ollama, OpenRouter, Azure, custom endpoints, and the full provider table.

## CLI Quick Reference

| Command | Description |
|---------|-------------|
| `run <role.yaml> -p "..."` | Single-shot prompt |
| `run <role.yaml> -i` | Interactive REPL |
| `validate <role.yaml>` | Validate a role definition |
| `init --name <name>` | Scaffold a new role |
| `setup` | Guided provider setup wizard |
| `ingest <role.yaml>` | Ingest documents into vector store |
| `daemon <role.yaml>` | Run in trigger-driven daemon mode |
| `serve <role.yaml>` | Serve as OpenAI-compatible API |
| `tui` | Launch terminal dashboard |
| `ui` | Launch web dashboard |
| `compose up <compose.yaml>` | Run multi-agent orchestration |
| `install <source>` | Install a community role from GitHub |
| `uninstall <name>` | Remove an installed role |
| `search <query>` | Search the community role index |
| `info <source>` | Inspect a role before installing |
| `list` | Show installed roles |
| `update [name] / --all` | Update installed roles |

See [docs/getting-started/cli.md](docs/getting-started/cli.md) for the full command list and all options.

## Documentation

**Getting Started**

- [Installation](docs/getting-started/installation.md) — Install methods, extras, dev setup, environment
- [Setup](docs/getting-started/setup.md) — First-time setup wizard and provider configuration
- [CLI Reference](docs/getting-started/cli.md) — All commands and options

**Agent Development**

- [Tools](docs/agents/tools.md) — Full tool reference with configuration examples
- [Tool Creation](docs/agents/tool_creation.md) — Building custom tools and plugins
- [Skills](docs/agents/skills_feature.md) — Reusable skill definitions
- [Providers](docs/configuration/providers.md) — Provider configs, custom endpoints, model reference
- [Ollama](docs/configuration/ollama.md) — Local model setup with Ollama

**Advanced Features**

- [Ingestion](docs/core/ingestion.md) — Document extraction, chunking, and embedding
- [Memory](docs/core/memory.md) — Session persistence and semantic memory
- [Triggers](docs/core/triggers.md) — Cron, file watcher, and webhook triggers
- [Compose](docs/orchestration/agent_composer.md) — Multi-agent orchestration and delegate sinks
- [Delegation](docs/orchestration/delegation.md) — Agent-to-agent delegation patterns
- [Pipelines](docs/orchestration/pipelines.md) — Sequential and parallel agent pipelines
- [Sinks](docs/orchestration/sinks.md) — Output sinks (webhook, file, custom)
- [Server](docs/interfaces/server.md) — OpenAI-compatible API server

**Operations**

- [Dashboard](docs/interfaces/dashboard.md) — Web dashboard setup and API reference
- [TUI](docs/interfaces/tui.md) — Terminal dashboard key bindings and screens
- [Audit](docs/core/audit.md) — Audit trail queries, export, and pruning
- [Security](docs/security/security.md) — Security model, sandboxing, and content policies
- [Guardrails](docs/configuration/guardrails.md) — Guardrails config and token budgets
- [Token Control](docs/configuration/token_control.md) — Token budgets and usage limits
- [Testing](docs/operations/testing.md) — Test suites and assertions
- [CI/CD](docs/operations/cicd.md) — Continuous integration and deployment
- [Registry](docs/agents/registry.md) — Installing and sharing community roles

## Examples

The `examples/` directory includes 20+ ready-to-run agents, skills, and compose pipelines covering real-world scenarios:

**Role definitions** (`examples/roles/`) — single-agent configs for support bots, code reviewers, changelog generators, deploy notifiers, web monitors, data analysts, and more.

**Skills** (`examples/skills/`) — reusable capability bundles:
- `web-researcher/` — web research tools (fetch pages, HTTP requests)
- `code-tools.md` — code execution and file browsing tools

See `examples/roles/skill-demo.yaml` for a role composing multiple skills.

**Compose pipelines** (`examples/compose/`) — multi-agent orchestration:
- `email-pipeline/` — cron-driven email triage with fan-out to researcher and responder
- `content-pipeline/` — file-watch-driven content creation with `process_existing` startup scan
- `ci-pipeline/` — webhook-driven CI build analysis with notifications

## Community & Support

- [GitHub Issues](https://github.com/vladkesler/initrunner/issues) — Bug reports and feature requests
- [GitHub Discussions](https://github.com/vladkesler/initrunner/discussions) — Questions and community help
- [Changelog](CHANGELOG.md) — Release notes and version history

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Run local quality checks before pushing:

```bash
uv sync --dev
uv run pre-commit install
uv run pre-commit run --all-files
```

Manual Ruff commands (equivalent to CI formatting/lint checks):

```bash
uv run ruff format .
uv run ruff check .
```

### Share a role

Push your `role.yaml` to a public GitHub repo — anyone can install it with `initrunner install user/repo`. To list it in the community index so users can `initrunner install my-role` by name, open a PR to [vladkesler/community-roles](https://github.com/vladkesler/community-roles) adding an entry to `index.yaml`. See [docs/agents/registry.md](docs/agents/registry.md) for details.

For security vulnerabilities, please see [SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE) for details.
