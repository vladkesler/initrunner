# InitRunner

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/logo-light.svg">
    <img src="assets/logo-light.svg" alt="InitRunner" width="500">
  </picture>
</p>

<p align="center">
  <a href="https://pypi.org/project/initrunner/"><img src="https://img.shields.io/pypi/v/initrunner?color=%2334D058&v=1" alt="PyPI version"></a>
  <a href="https://pypi.org/project/initrunner/"><img src="https://img.shields.io/pypi/dm/initrunner?color=%2334D058" alt="PyPI downloads"></a>
  <a href="https://hub.docker.com/r/vladkesler/initrunner"><img src="https://img.shields.io/docker/pulls/vladkesler/initrunner?color=%2334D058" alt="Docker pulls"></a>
  <a href="LICENSE-MIT"><img src="https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-%2334D058" alt="MIT OR Apache-2.0"></a>
  <a href="https://ai.pydantic.dev/"><img src="https://img.shields.io/badge/PydanticAI-6e56cf?logo=pydantic&logoColor=white" alt="PydanticAI"></a>
  <a href="https://discord.gg/GRTZmVcW"><img src="https://img.shields.io/badge/Discord-InitRunner%20Hub-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="https://initrunner.ai/">Website</a> · <a href="https://initrunner.ai/docs">Docs</a> · <a href="https://hub.initrunner.ai/">InitHub</a> · <a href="https://discord.gg/GRTZmVcW">Discord</a> · <a href="https://github.com/vladkesler/initrunner/issues">Issues</a>
</p>

A docs assistant that answers from your knowledge base with citations. A research team that searches the web and writes sourced reports. A code review team that catches bugs from three different angles. Each one is a YAML file and a command:

```bash
initrunner run helpdesk -i                                    # docs Q&A with RAG + memory
initrunner run deep-researcher -p "Compare vector databases"  # 3-agent research team
initrunner run code-review-team -p "Review the latest commit" # multi-perspective code review
```

You describe the agent -- its role, tools, knowledge sources, memory -- in a single YAML file. InitRunner handles tool wiring, retrieval, model switching, and deployment. The same file runs as an interactive chat, a one-shot CLI command, a trigger-driven daemon, or an OpenAI-compatible API. 15 curated starters, 60+ examples, or define your own.

> **v2026.4.2** -- PydanticAI + LangChain agent import: convert existing agents to InitRunner with `initrunner new --pydantic-ai my_agent.py` or `--langchain`. See the [Changelog](CHANGELOG.md).

## Quickstart

```bash
curl -fsSL https://initrunner.ai/install.sh | sh
initrunner setup        # wizard: pick provider, model, API key
```

Or: `uv pip install "initrunner[recommended]"` / `pipx install "initrunner[recommended]"`. See [Installation](docs/getting-started/installation.md).

### Try a starter

Run `initrunner run --list` for the full catalog. The model is auto-detected from your API key.

| Starter | What it does | Kind |
|---------|-------------|------|
| `helpdesk` | Drop your docs in, get a Q&A agent with citations and memory | Agent (RAG) |
| `code-review-team` | Multi-perspective review: architect, security, maintainer | Team |
| `deep-researcher` | 3-agent pipeline: planner, web researcher, synthesizer with shared memory | Team |
| `codebase-analyst` | Index your repo, chat about architecture, learns patterns across sessions | Agent (RAG) |
| `web-researcher` | Search the web and produce structured briefings with citations | Agent |
| `content-pipeline` | Topic researcher, writer, editor/fact-checker via webhook or cron | Compose |
| `telegram-assistant` | Telegram bot with memory and web search | Agent (Daemon) |
| `email-agent` | Monitors inbox, triages messages, drafts replies, alerts Slack on urgent mail | Agent (Daemon) |
| `support-desk` | Sense-routed intake: auto-routes to researcher, responder, or escalator | Compose |
| `memory-assistant` | Personal assistant that remembers across sessions | Agent |

RAG starters auto-ingest on first run. Just `cd` into your project:

```bash
cd ~/myproject
initrunner run codebase-analyst -i   # indexes your code, then starts Q&A
```

### Build your own

```bash
initrunner new "a research assistant that summarizes papers"  # generates a role.yaml
initrunner run --ingest ./docs/    # or skip YAML entirely -- chat with your docs
```

Browse and install community agents from [InitHub](https://hub.initrunner.ai/): `initrunner search "code review"` / `initrunner install alice/code-reviewer`.

**Docker**, no install needed:

```bash
docker run -d -e OPENAI_API_KEY -p 8100:8100 \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest        # dashboard
docker run --rm -it -e OPENAI_API_KEY \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest run -i # chat
```

See the [Docker guide](docs/getting-started/docker.md) for more.

## Define an Agent in YAML

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

No Python, no boilerplate. The `model:` section is optional -- omit it and InitRunner auto-detects from your API key. Works with Anthropic, OpenAI, Google, Groq, Mistral, Cohere, xAI, OpenRouter, Ollama, and any OpenAI-compatible endpoint. 28 built-in tools: filesystem, git, HTTP, Python, shell, SQL, search, email, Slack, MCP, audio, PDF extraction, CSV analysis, image generation, and more. Need a custom tool? [One file, one decorator](docs/agents/tool_creation.md).

## Why InitRunner

A YAML file *is* the agent. Its tools, knowledge sources, memory, triggers, model, guardrails -- all declared in one place. You can read it and immediately understand what the agent does. You can diff it, review it in a PR, hand it to a teammate. When you want to switch from GPT to Claude, you change one line. When you want to add RAG, you add an `ingest:` section.

The same file runs as an interactive chat (`-i`), a one-shot command (`-p "..."`), a cron/webhook/file-watch daemon (`--daemon`), or an OpenAI-compatible API (`--serve`). You don't pick a deployment mode upfront and build around it. You pick it at runtime with a flag.

What this gets you in practice: your agent config lives in version control next to your code. New team members read the YAML and understand what the agent does. You review agent changes in PRs like any other config. And the agent you prototyped interactively is the same one you deploy as a daemon or API -- no rewrite, just a different flag.

## How It Compares

|  | InitRunner | LangChain | CrewAI | AutoGen |
|---|---|---|---|---|
| **Agent config** | YAML file | Python chains + config | Python classes | Python classes |
| **RAG** | `--ingest ./docs/` (one flag) | Loaders + splitters + vectorstore | RAG tool or custom | External setup |
| **Memory** | Built-in, on by default | Add-on (multiple options) | Short/long-term memory | External |
| **Multi-agent** | `compose.yaml` or `kind: Team` | LangGraph | Crew definition | Group chat |
| **Deployment modes** | Same YAML: REPL / daemon / API | Custom per mode | CLI or Kickoff | Custom |
| **Model switching** | Change 1 YAML line | Swap LLM class | Config per agent | Config per agent |
| **Custom tools** | 1 file, 1 decorator | `@tool` decorator | `@tool` decorator | Function call |
| **Bot deployment** | `--telegram` / `--discord` flag | Separate integration | Separate integration | Separate integration |
| **Migration** | `--pydantic-ai` / `--langchain` import | N/A | N/A | N/A |

## What You Get

### Knowledge and memory

Point your agent at a directory. It extracts, chunks, embeds, and indexes your documents. During conversation, the agent searches the index automatically and cites what it finds. Memory persists across sessions.

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
initrunner run role.yaml -i   # auto-ingests on first run, memory + search ready
```

See [Ingestion](docs/core/ingestion.md) · [Memory](docs/core/memory.md) · [RAG Quickstart](docs/getting-started/rag-quickstart.md).

### Triggers and daemons

Turn any agent into a daemon that reacts to cron schedules, file changes, webhooks, or heartbeats:

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

### Multi-agent orchestration

Chain agents together. One agent's output feeds into the next. Sense routing auto-picks the right target per message (keyword matching first, single LLM call to break ties):

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

Run with `initrunner compose up compose.yaml`. See [Patterns Guide](docs/orchestration/patterns-guide.md) · [Compose](docs/orchestration/agent_composer.md).

### Reasoning and tool management

Control how your agent thinks, not just what it does:

```yaml
spec:
  reasoning:
    pattern: plan_execute    # plans upfront, then executes each step
    auto_plan: true
  tools:
    - type: think            # internal scratchpad with self-critique
      critique: true
    - type: todo             # structured task list for multi-step work
```

Four reasoning patterns: `react`, `todo_driven`, `plan_execute`, and `reflexion`. See [Reasoning](docs/core/reasoning.md).

Agents with many tools waste context and pick worse. Tool search hides tools behind on-demand keyword discovery -- the agent sees only `search_tools` and a few pinned tools, then discovers what it needs per-turn. BM25 scoring, no API calls, typically saves 60-80% context. See [Tool Search](docs/core/tool-search.md).

## Architecture

```
initrunner/
  agent/        Role schema, loader, executor, 28 self-registering tools
  runner/       Single-shot, REPL, autonomous, daemon execution modes
  compose/      Multi-agent orchestration via compose.yaml
  triggers/     Cron, file watcher, webhook, heartbeat, Telegram, Discord
  stores/       Document + memory stores (LanceDB, zvec)
  ingestion/    Extract -> chunk -> embed -> store pipeline
  mcp/          MCP server integration and gateway
  audit/        Append-only SQLite audit trail
  services/     Shared business logic layer
  cli/          Typer + Rich CLI entry point
```

Built on [PydanticAI](https://ai.pydantic.dev/) for the agent framework, Pydantic for config validation, LanceDB for vector search. See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup.

## Security

InitRunner ships with an embedded [initguard](https://github.com/initrunner/initguard) policy engine. Agents get identity from their role metadata (name, team, tags, author), and every tool call and delegation is checked against your policies:

- **Tool-level authorization** -- agents can only call tools their policy allows
- **Delegation policy** -- controls which agents can hand off to which others
- **Content filtering** -- input guardrails with configurable content policy
- **PEP 578 sandboxing** -- audit hooks for dangerous operations
- **Docker isolation** -- optional sandboxed execution environment
- **Token budgets and rate limiting** -- prevent runaway costs
- **Env var scrubbing** -- sensitive keys stripped from subprocess environments
- **Append-only audit trail** -- every tool call logged to SQLite

```bash
export INITRUNNER_POLICY_DIR=./policies
initrunner run role.yaml                  # tool calls + delegation checked against policies
```

See [Agent Policy](docs/security/agent-policy.md) · [Security](docs/security/security.md) · [Guardrails](docs/configuration/guardrails.md).

## User Interfaces

<p align="center">
  <img src="assets/screenshot-dashboard.png" alt="InitRunner Dashboard" width="800"><br>
  <em>Dashboard -- agents, activity, compositions, and teams at a glance</em>
</p>

```bash
pip install "initrunner[dashboard]"
initrunner dashboard                  # opens http://localhost:8100
```

Browse agents, run prompts, build compositions visually, configure reasoning patterns, and review audit trails. Also available as a native desktop window (`initrunner desktop`). See [Dashboard docs](docs/interfaces/dashboard.md).

## More Capabilities

| Feature | Command / config | Docs |
|---------|-----------------|------|
| **Skills** -- reusable tool + prompt bundles | `spec: { skills: [../skills/web-researcher] }` | [Skills](docs/agents/skills_feature.md) |
| **Team mode** -- multi-persona on one task | `kind: Team` + `spec: { personas: {…} }` | [Team Mode](docs/orchestration/team_mode.md) |
| **API server** -- OpenAI-compatible endpoint | `initrunner run agent.yaml --serve --port 3000` | [Server](docs/interfaces/server.md) |
| **Multimodal** -- images, audio, video, docs | `initrunner run role.yaml -p "Describe" -A photo.png` | [Multimodal](docs/core/multimodal.md) |
| **Structured output** -- validated JSON schemas | `spec: { output: { schema: {…} } }` | [Structured Output](docs/core/structured-output.md) |
| **Evals** -- test agent output quality | `initrunner test role.yaml -s eval.yaml` | [Evals](docs/core/evals.md) |
| **MCP gateway** -- expose agents as MCP tools | `initrunner mcp serve agent.yaml` | [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| **MCP toolkit** -- tools without an agent | `initrunner mcp toolkit` | [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| **Capabilities** -- native PydanticAI features | `spec: { capabilities: [Thinking, WebSearch] }` | [Capabilities](docs/core/capabilities.md) |
| **Observability** -- OpenTelemetry integration | `spec: { observability: { enabled: true } }` | [Observability](docs/core/observability.md) |
| **Configure** -- switch provider/model on any role | `initrunner configure role.yaml --provider groq` | [Providers](docs/configuration/providers.md) |

## Distribution

**InitHub:** Browse and install community agents at [hub.initrunner.ai](https://hub.initrunner.ai/). Publish your own with `initrunner publish`. See [Registry](docs/agents/registry.md).

**OCI registries:** Push role bundles to any OCI-compliant registry: `initrunner publish oci://ghcr.io/org/my-agent --tag 1.0.0`. See [OCI Distribution](docs/core/oci-distribution.md).

**Cloud deploy:**

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/FROM_REPO?referralCode=...)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/vladkesler/initrunner)

## Documentation

| Area | Key docs |
|------|----------|
| Getting started | [Installation](docs/getting-started/installation.md) · [Setup](docs/getting-started/setup.md) · [RAG Quickstart](docs/getting-started/rag-quickstart.md) · [Tutorial](docs/getting-started/tutorial.md) · [CLI Reference](docs/getting-started/cli.md) · [Docker](docs/getting-started/docker.md) · [Discord Bot](docs/getting-started/discord.md) · [Telegram Bot](docs/getting-started/telegram.md) |
| Agents & tools | [Tools](docs/agents/tools.md) · [Tool Creation](docs/agents/tool_creation.md) · [Tool Search](docs/core/tool-search.md) · [Skills](docs/agents/skills_feature.md) · [Structured Output](docs/core/structured-output.md) · [Providers](docs/configuration/providers.md) |
| Intelligence | [Reasoning](docs/core/reasoning.md) · [Intent Sensing](docs/core/intent_sensing.md) · [Tool Search](docs/core/tool-search.md) · [Autonomy](docs/orchestration/autonomy.md) |
| Knowledge & memory | [Ingestion](docs/core/ingestion.md) · [Memory](docs/core/memory.md) · [Multimodal Input](docs/core/multimodal.md) |
| Orchestration | [Patterns Guide](docs/orchestration/patterns-guide.md) · [Compose](docs/orchestration/agent_composer.md) · [Delegation](docs/orchestration/delegation.md) · [Team Mode](docs/orchestration/team_mode.md) · [Autonomy](docs/orchestration/autonomy.md) · [Triggers](docs/core/triggers.md) |
| Interfaces | [Dashboard](docs/interfaces/dashboard.md) · [API Server](docs/interfaces/server.md) · [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| Distribution | [OCI Distribution](docs/core/oci-distribution.md) · [Shareable Templates](docs/getting-started/shareable-templates.md) |
| Operations | [Security](docs/security/security.md) · [Agent Policy](docs/security/agent-policy.md) · [Guardrails](docs/configuration/guardrails.md) · [Audit](docs/core/audit.md) · [Reports](docs/core/reports.md) · [Evals](docs/core/evals.md) · [Doctor](docs/operations/doctor.md) · [Observability](docs/core/observability.md) · [CI/CD](docs/operations/cicd.md) |

## Examples

```bash
initrunner examples list               # 60+ agents, teams, and compose projects
initrunner examples copy code-reviewer # copy to current directory
```

## Upgrading

Run `initrunner doctor --role role.yaml` to check any role file for deprecated fields, schema errors, and spec version issues. Add `--fix` to auto-repair, or `--fix --yes` for CI. See [Deprecations](docs/operations/deprecations.md).

## Community & Contributing

- [Discord](https://discord.gg/GRTZmVcW) -- chat, ask questions, share roles
- [GitHub Issues](https://github.com/vladkesler/initrunner/issues) -- bug reports and feature requests
- [Changelog](CHANGELOG.md) -- release notes

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup and PR guidelines.

## License

Licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option.

---

<p align="center"><sub>v2026.4.2</sub></p>
