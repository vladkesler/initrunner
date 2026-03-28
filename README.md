# InitRunner

<p align="center"><img src="https://raw.githubusercontent.com/vladkesler/initrunner/main/assets/mascot.png" alt="InitRunner mascot" width="300"></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-3776ab?logo=python&logoColor=white" alt="Python 3.11+">
  <a href="https://pypi.org/project/initrunner/"><img src="https://img.shields.io/pypi/v/initrunner?color=%2334D058&v=1" alt="PyPI version"></a>
  <a href="https://pypi.org/project/initrunner/"><img src="https://img.shields.io/pypi/dm/initrunner?color=%2334D058" alt="PyPI downloads"></a>
  <a href="https://github.com/vladkesler/initrunner"><img src="https://img.shields.io/github/stars/vladkesler/initrunner?style=flat&color=%2334D058" alt="GitHub stars"></a>
  <a href="https://hub.docker.com/r/vladkesler/initrunner"><img src="https://img.shields.io/docker/pulls/vladkesler/initrunner?color=%2334D058" alt="Docker pulls"></a>
  <a href="LICENSE-MIT"><img src="https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-%2334D058" alt="MIT OR Apache-2.0"></a>
  <a href="tests/"><img src="https://img.shields.io/badge/tests-4001+-%2334D058" alt="Tests"></a>
  <img src="https://img.shields.io/badge/latest-v2026.3.2-%2334D058" alt="v2026.3.2">
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-d4aa00?logo=ruff&logoColor=white" alt="Ruff"></a>
  <a href="https://ai.pydantic.dev/"><img src="https://img.shields.io/badge/PydanticAI-6e56cf?logo=pydantic&logoColor=white" alt="PydanticAI"></a>
  <a href="https://initrunner.ai/"><img src="https://img.shields.io/badge/website-initrunner.ai-blue" alt="Website"></a>
  <a href="https://discord.gg/GRTZmVcW"><img src="https://img.shields.io/badge/Discord-InitRunner%20Hub-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="https://initrunner.ai/">Website</a> · <a href="https://initrunner.ai/docs">Docs</a> · <a href="https://hub.initrunner.ai/">InitHub</a> · <a href="https://discord.gg/GRTZmVcW">Discord</a> · <a href="https://github.com/vladkesler/initrunner/issues">Issues</a>
</p>

**AI agents that work.** A docs assistant that answers from your knowledge base with citations. A code review team that catches bugs before your human reviewers do. A research team that plans queries, searches the web, and writes cited reports. A monitoring daemon that learns what "normal" looks like over time.

Each one is a single command:

```bash
initrunner run helpdesk -i                                    # docs Q&A with RAG + memory
initrunner run deep-researcher -p "Compare vector databases"  # 3-agent research team
initrunner run codebase-analyst -i                            # index & chat with your code
initrunner run code-review-team -p "Review the latest commit" # multi-perspective code review
initrunner run web-researcher -p "Compare React vs Svelte"    # web research with citations
initrunner run telegram-assistant --daemon                     # Telegram bot with memory
initrunner run discord-assistant --daemon                      # Discord bot with memory
```

Or define your own in one YAML file. Built-in RAG, persistent memory, 25+ tools, any model.

> **v2026.3.2** -- Dashboard now supports `--api-key` authentication. Memory template bug fixed -- agents built from the memory template retain their config. See the [Changelog](CHANGELOG.md).

## Contents

- [Quickstart](#quickstart)
- [Define an Agent in YAML](#define-agent-roles-in-yaml)
- [Why InitRunner](#why-initrunner)
- [Features](#features)
- [User Interfaces](#user-interfaces)
- [Security & Authorization](#security--authorization)
- [Distribution & Deployment](#distribution--deployment)
- [Documentation](#documentation)
- [Community](#community--contributing)

## Quickstart

**Install and configure:**

```bash
curl -fsSL https://initrunner.ai/install.sh | sh
initrunner setup        # wizard: pick provider, model, API key
```

Or install with a package manager: `uv pip install "initrunner[recommended]"` / `pipx install "initrunner[recommended]"`. See [Installation](docs/getting-started/installation.md) and [Setup](docs/getting-started/setup.md).

**Upgrade:** re-run the install command, or: `uv tool upgrade initrunner` / `pipx upgrade initrunner`.

### Try a starter agent

Run `initrunner run --list` to see all available starters. The model is auto-detected from your API key.

| Starter | What it does | Kind |
|---------|-------------|------|
| `helpdesk` | Drop your docs in, get an AI helpdesk with citations and memory | Agent (RAG) |
| `code-review-team` | Multi-perspective review: architect, security, maintainer | Team |
| `deep-researcher` | 3-agent pipeline: planner, web researcher, synthesizer with shared memory | Team |
| `codebase-analyst` | Index your repo, chat about architecture, learns patterns across sessions | Agent (RAG) |
| `web-researcher` | Search the web and produce structured briefings with citations | Agent |
| `content-pipeline` | Topic researcher, writer, editor/fact-checker via webhook or cron | Compose |
| `project-monitor` | Heartbeat-driven health checks, learns baselines over time | Agent (Daemon) |
| `telegram-assistant` | Telegram bot with memory and web search | Agent (Daemon) |
| `discord-assistant` | Discord bot with memory and web search | Agent (Daemon) |
| `rag-agent` | Document Q&A agent with ingestion and citations | Agent (RAG) |
| `memory-assistant` | Personal assistant that learns and remembers across sessions | Agent |
| `email-agent` | Monitors inbox, triages messages, drafts replies, alerts Slack on urgent mail | Agent (Daemon) |
| `ci-pipeline` | Webhook receiver, build analyzer, Slack notifier for CI events | Compose |
| `support-desk` | Sense-routed intake, researcher, responder, and escalator | Compose |

RAG starters auto-ingest on first run -- just `cd` into your project and go:

```bash
cd ~/myproject
initrunner run codebase-analyst -i   # indexes your code, then starts Q&A
```

Want to customize? Copy locally and edit:

```bash
initrunner run helpdesk --save ./my-helpdesk/
# add your docs to ./my-helpdesk/knowledge-base/, then:
initrunner run ./my-helpdesk/ -i
```

### Use a premade agent from InitHub

Browse [hub.initrunner.ai](https://hub.initrunner.ai/) or search from the terminal:

```bash
initrunner search "code review"                                    # find agents
initrunner install alice/code-reviewer                             # install one
initrunner run alice/code-reviewer -p "Review the latest commit"   # run it
```

See [Registry docs](docs/agents/registry.md) for version pinning, updates, and OCI sources.

### Or build your own

```bash
initrunner new "a research assistant that summarizes papers"  # AI-generates a role.yaml
initrunner run --ingest ./docs/    # or skip YAML entirely -- chat with your docs, memory on by default
```

Fork a hub agent as a starting point: `initrunner new --from hub:alice/code-reviewer`. See [Tutorial](docs/getting-started/tutorial.md).

**Or run with Docker**, no install needed:

```bash
docker run --rm -it -e OPENAI_API_KEY \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest run
```

See the [Docker guide](docs/getting-started/docker.md) for RAG, Telegram, API server, and more examples.

## Define Agent Roles in YAML

When you need more control, define an agent as a YAML file:

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
  model: { provider: openai, name: gpt-5-mini }
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

That's it. No Python, no boilerplate. Using Claude? `pipx install "initrunner[anthropic]"` and set `model: { provider: anthropic, name: claude-sonnet-4-5-20250929 }`.

## Why InitRunner

**Zero config to start.** `initrunner run` gives you an AI assistant with persistent memory and document search out of the box. No YAML, no setup beyond an API key.

**Config, not code.** Define your agent's tools, knowledge base, and memory in one YAML file. No framework boilerplate, no wiring classes together. 25+ built-in tools (filesystem, git, HTTP, Python, shell, SQL, search, email, MCP, think, script, and more) work out of the box. Need a custom tool? One file, one decorator.

**Version-control your agents.** Agent configs are plain text. Diff them, review them in PRs, validate in CI, reproduce anywhere. Your agent definition lives next to your code.

**Prototype to production.** Same YAML runs as an interactive chat, a one-shot CLI command, a trigger-driven daemon, or an OpenAI-compatible API. No rewrite when you're ready to deploy.

## How It Compares

|  | InitRunner | Build from scratch | LangChain |
|---|---|---|---|
| **Setup** | `curl -fsSL https://initrunner.ai/install.sh \| sh` + API key | Install 5-10 packages, write glue code | `pip install langchain` + adapters |
| **Agent config** | One YAML file | Python classes + wiring | Python chains + config objects |
| **RAG** | `--ingest ./docs/` (one flag) | Embed, store, retrieve, prompt - DIY | Loaders > splitters > vectorstore chain |
| **Bot deployment** | `--telegram` / `--discord` flag | Build bot framework integration | Separate bot framework + adapter |
| **Model switching** | `--model` flag, aliases, or change YAML | Rewrite client code | Swap LLM class + adjust prompts |
| **Multi-agent** | `compose.yaml` with delegation + auto-routing | Custom orchestration layer | Agent executor + custom routing |

## What Can You Build?

- **A Telegram bot that answers questions about your codebase** - point it at your repo, deploy with one flag
- **A cron job that monitors competitors and sends daily digests** - cron trigger + web scraper + Slack sink
- **A document Q&A agent for your team's knowledge base** - ingest PDFs and Markdown, serve as an API
- **A code review bot triggered by new commits** - file-watch trigger + git tools + structured output
- **A multi-agent pipeline with auto-routing: intake > researcher / responder / escalator** - sense routing picks the right target per message (`initrunner examples copy support-desk`)
- **A personal assistant that remembers everything** - persistent memory across sessions, no setup

## Features

Start with the code-reviewer above. Each step adds one capability - no rewrites, just add a section to your YAML.

### Knowledge & memory

Point at your docs for RAG - a `search_documents` tool is auto-registered. Set `auto: true` and it indexes on first run, no extra step:

```yaml
spec:
  ingest:
    auto: true
    sources: ["./docs/**/*.md", "./docs/**/*.pdf"]
  memory:
    semantic:
      max_memories: 1000
```

```bash
initrunner run role.yaml -i   # auto-ingests on first run, then search_documents + memory ready
```

Common junk directories (`node_modules`, `.venv`, `__pycache__`, `.git`) are auto-excluded from glob patterns. Or ingest manually: `initrunner ingest role.yaml`.

See [Ingestion](docs/core/ingestion.md) · [Memory](docs/core/memory.md) · [RAG Quickstart](docs/getting-started/rag-quickstart.md).

### Capabilities

Use native PydanticAI capabilities directly in YAML -- no tool wiring needed:

```yaml
spec:
  capabilities:
    - Thinking
    - WebSearch
    - WebFetch: { max_size: 1048576 }
  model: { provider: anthropic, name: claude-sonnet-4-5-20250929 }
```

Capabilities like Thinking, WebSearch, WebFetch, ImageGeneration, and MCP are resolved at build time. `InputGuardCapability` enforces content policy from `security.content_policy`. See [Capabilities](docs/core/capabilities.md).

### Clarify tool

Let agents ask follow-up questions mid-run instead of guessing:

```yaml
spec:
  tools:
    - type: clarify
```

The agent calls `clarify("Which branch should I deploy?")` and blocks until the user responds. Works in REPL, Telegram/Discord bots, daemon mode, and autonomous runs. See [Tools](docs/agents/tools.md).

### Context budget guard

Long autonomous runs accumulate history that can exceed the context window. The built-in history processor estimates token usage and drops oldest message pairs when the budget is exceeded:

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-5-20250929
    context_window: 200000   # optional -- auto-detected per provider
  autonomy:
    max_iterations: 50
```

No extra config needed -- the guard activates automatically for autonomous and daemon runs. See [Autonomy](docs/orchestration/autonomy.md).

### Triggers

Turn it into a daemon that reacts to events - cron, file watch, webhook, heartbeat, Telegram, or Discord:

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
initrunner run role.yaml --daemon   # runs until stopped
```

See [Triggers](docs/core/triggers.md) · [Telegram](docs/getting-started/telegram.md) · [Discord](docs/getting-started/discord.md).

### Compose agents

Orchestrate multiple agents into a chain - one agent's output feeds into the next. Use `strategy: sense` to auto-route messages to the right target:

```yaml
apiVersion: initrunner/v1
kind: Compose
metadata: { name: email-chain }
spec:
  services:
    inbox-watcher:
      role: roles/inbox-watcher.yaml
      sink: { type: delegate, target: triager }
    triager:
      role: roles/triager.yaml
      sink: { type: delegate, strategy: sense, target: [researcher, responder] }
    researcher: { role: roles/researcher.yaml }
    responder: { role: roles/responder.yaml }
```

Run with `initrunner compose up compose.yaml`. See [Orchestration Patterns](docs/orchestration/patterns-guide.md) for all five patterns side-by-side, or dive into [Compose](docs/orchestration/agent_composer.md) · [Delegation](docs/orchestration/delegation.md).

## User Interfaces

<p align="center">
  <img src="assets/screenshot-dashboard.png" alt="InitRunner Dashboard" width="800"><br>
  <em>Dashboard Launchpad - agents, activity, compositions, and teams at a glance</em>
</p>

Manage agents, run prompts, build compositions, and browse audit trails from a visual interface. Two modes are available: a web dashboard that opens in your browser, and a native desktop app.

### Dashboard (web)

```bash
pip install "initrunner[dashboard]"   # included in initrunner[all]
initrunner dashboard                  # opens http://localhost:8100
```

The browser opens automatically. Flags:

| Flag | Description |
|------|-------------|
| `--port` | Listen on a different port (default: `8100`) |
| `--no-open` | Don't open the browser automatically |
| `--expose` | Bind to `0.0.0.0` instead of localhost |
| `--api-key` | Protect access with a login page and cookie-based session |
| `--roles-dir` | Extra directories to scan for role YAML files (repeatable) |

### Desktop (native window)

```bash
pip install "initrunner[desktop]"     # adds pywebview
initrunner desktop                    # opens a native OS window
```

No browser needed. The desktop app embeds the dashboard in a native window using the platform's WebView (WKWebView on macOS, WebView2 on Windows). On Linux, GTK and WebKit packages are required -- the command detects missing packages and prints the install command for your distro.

If a dashboard is already running on the port, the desktop window connects to it instead of starting a second backend.

### What's in the UI

- **Agent management** -- browse, create, delete, and inspect agents in a flow canvas or list view
- **Run panel** -- send prompts and stream responses in real time
- **Compose and Team builders** -- visual editors for multi-agent orchestration
- **Audit log** -- filterable run history with token usage and durations
- **System health** -- detected providers, doctor checks, and tool registry

See the full [Dashboard docs](docs/interfaces/dashboard.md) and [Design System](docs/interfaces/design-system.md).

## Security & Authorization

Built-in security with optional [Cerbos](https://github.com/cerbos/cerbos) agent-as-principal policy engine. Agents get Cerbos identity from `role.metadata` (name, team, tags, author), with **tool-level authorization** and **delegation policy** enforced across CLI, compose, daemon, and API:

```bash
pip install initrunner[authz]
export INITRUNNER_CERBOS_ENABLED=true
export INITRUNNER_CERBOS_AGENT_CHECKS=true  # per-agent identity checks
initrunner run role.yaml   # tool calls + delegation checked against Cerbos policies
```

Also includes content filtering, PEP 578 sandboxing, Docker isolation, token budgets, and rate limiting out of the box. See [Agent Policy](docs/security/agent-policy.md) · [Security](docs/security/security.md) · [Guardrails](docs/configuration/guardrails.md).

### More capabilities

| Feature | Command / config | Docs |
|---------|-----------------|------|
| **Skills** - reusable tool + prompt bundles, auto-discovered | `spec: { skills: [../skills/web-researcher] }` | [Skills](docs/agents/skills_feature.md) |
| **Team mode** - multi-persona on one task | `kind: Team` + `spec: { personas: {…} }` | [Team Mode](docs/orchestration/team_mode.md) |
| **API server** - OpenAI-compatible endpoint | `initrunner run agent.yaml --serve --port 3000` | [Server](docs/interfaces/server.md) |
| **Multimodal** - images, audio, video, docs | `initrunner run role.yaml -p "Describe" -A photo.png` | [Multimodal](docs/core/multimodal.md) |
| **Structured output** - validated JSON schemas | `spec: { output: { schema: {…} } }` | [Structured Output](docs/core/structured-output.md) |
| **Evals** - test agent output quality | `initrunner test role.yaml -s eval.yaml` | [Evals](docs/core/evals.md) |
| **MCP gateway** - expose agents as MCP tools | `initrunner mcp serve agent.yaml` | [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| **MCP toolkit** - tools without an agent | `initrunner mcp toolkit` | [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| **Configure** - switch provider/model on any role | `initrunner configure role.yaml --provider groq` | [Providers](docs/configuration/providers.md) |

See [Tutorial](docs/getting-started/tutorial.md) for a guided walkthrough.

## Distribution & Deployment

### InitHub

```bash
initrunner search "code review"                          # browse InitHub
initrunner install alice/code-reviewer                   # install from InitHub
initrunner install alice/code-reviewer@1.2.0             # pin a version
```

See [Registry](docs/agents/registry.md).

```bash
initrunner login                        # browser-based device code auth
initrunner login --token <TOKEN>        # CI/headless
initrunner publish                      # publish from current agent directory
```

See [Publishing Guide](https://hub.initrunner.ai/docs/publish).

### OCI registry

Publish and install complete role bundles to any OCI-compliant container registry:

```bash
initrunner publish oci://ghcr.io/org/my-agent --tag 1.0.0       # from current dir
initrunner publish ./my-agent/ oci://ghcr.io/org/my-agent --tag 1.0.0  # or pass a path
initrunner install oci://ghcr.io/org/my-agent:1.0.0
```

See [OCI Distribution](docs/core/oci-distribution.md).

### Cloud deploy

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/FROM_REPO?referralCode=...)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/vladkesler/initrunner)

**Fly.io:** See the `deploy/fly.toml` configuration in the repository.

## Documentation

| Area | Key docs |
|------|----------|
| Getting started | [Installation](docs/getting-started/installation.md) · [Setup](docs/getting-started/setup.md) · [RAG Quickstart](docs/getting-started/rag-quickstart.md) · [Tutorial](docs/getting-started/tutorial.md) · [CLI Reference](docs/getting-started/cli.md) · [Docker](docs/getting-started/docker.md) · [Discord Bot](docs/getting-started/discord.md) · [Telegram Bot](docs/getting-started/telegram.md) |
| Agents & tools | [Tools](docs/agents/tools.md) · [Tool Creation](docs/agents/tool_creation.md) · [Tool Search](docs/core/tool-search.md) · [Skills](docs/agents/skills_feature.md) · [Structured Output](docs/core/structured-output.md) · [Providers](docs/configuration/providers.md) |
| Knowledge & memory | [Ingestion](docs/core/ingestion.md) · [Memory](docs/core/memory.md) · [Multimodal Input](docs/core/multimodal.md) |
| Orchestration | [Patterns Guide](docs/orchestration/patterns-guide.md) · [Compose](docs/orchestration/agent_composer.md) · [Delegation](docs/orchestration/delegation.md) · [Team Mode](docs/orchestration/team_mode.md) · [Autonomy](docs/orchestration/autonomy.md) · [Triggers](docs/core/triggers.md) · [Intent Sensing](docs/core/intent_sensing.md) |
| Interfaces | [Dashboard](docs/interfaces/dashboard.md) · [API Server](docs/interfaces/server.md) · [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| Distribution | [OCI Distribution](docs/core/oci-distribution.md) · [Shareable Templates](docs/getting-started/shareable-templates.md) |
| Operations | [Security](docs/security/security.md) · [Agent Policy](docs/security/agent-policy.md) · [Guardrails](docs/configuration/guardrails.md) · [Audit](docs/core/audit.md) · [Reports](docs/core/reports.md) · [Evals](docs/core/evals.md) · [Doctor](docs/operations/doctor.md) · [Deprecations](docs/operations/deprecations.md) · [Observability](docs/core/observability.md) · [CI/CD](docs/operations/cicd.md) |

See [`docs/`](docs/) for the full index.

## Examples

```bash
initrunner examples list               # see all available examples
initrunner examples copy code-reviewer # copy to current directory
```

The [`examples/`](examples/) directory includes 20+ ready-to-run agents, skills, and compose projects.

## Upgrading & Deprecations

Role YAML files now include `metadata.spec_version` to track schema compatibility. When InitRunner removes or renames a config field, the deprecation system gives a clear error message pointing to the fix instead of a cryptic validation failure.

Run `initrunner doctor --role role.yaml` to check any role file for deprecated fields, schema errors, and spec version status. Add `--fix` to auto-install missing SDKs, install required extras for your role's tools/triggers, and bump `spec_version` -- or `--fix --yes` for non-interactive CI. See the [Deprecations guide](docs/operations/deprecations.md) for the full list of removed fields and migration instructions.

## Community & Contributing

- [Discord - InitRunner Hub](https://discord.gg/GRTZmVcW) - Chat, ask questions, share roles
- [GitHub Issues](https://github.com/vladkesler/initrunner/issues) - Bug reports and feature requests
- [Changelog](CHANGELOG.md) - Release notes and version history

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup and PR guidelines. For security vulnerabilities, see [SECURITY.md](SECURITY.md).

## License

Licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option.

---

<p align="center"><sub>v2026.3.1</sub></p>
