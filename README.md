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
  <a href="https://initrunner.ai/">Website</a> · <a href="https://initrunner.ai/docs">Docs</a> · <a href="https://hub.initrunner.ai/">InitHub</a> · <a href="https://discord.gg/GRTZmVcW">Discord</a>
</p>

<p align="center">
  English · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a>
</p>

YAML-first AI agent platform. One file defines the agent. The same file runs as an interactive chat, a one-shot command, an autonomous worker, or a production daemon. 12 security layers in the box. Install with `curl` or `pip`.

<p align="center">
  <img src="assets/screenshot-pipeline.png" alt="InitRunner Team Pipeline" width="800"><br>
  <em>architecture-debate: optimist, skeptic, and pragmatist across 2 rounds, then synthesis</em>
</p>

```bash
initrunner run helpdesk -i                                    # docs Q&A with RAG + memory
initrunner run deep-researcher -p "Compare vector databases"  # 3-agent research team
initrunner run code-review-team -p "Review the latest commit" # multi-perspective code review
```

15 curated starters, 60+ examples, or define your own.

> **v2026.4.4**: `--autopilot` flag for multi-step autonomous triggers, README restructured around security and autonomy. See the [Changelog](CHANGELOG.md).

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
initrunner run --ingest ./docs/    # or skip YAML entirely, just chat with your docs
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

## Define an agent in YAML

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

The `model:` section is optional; omit it and InitRunner auto-detects from your API key. Works with Anthropic, OpenAI, Google, Groq, Mistral, Cohere, xAI, OpenRouter, Ollama, and any OpenAI-compatible endpoint. 28 built-in tools (filesystem, git, HTTP, Python, shell, SQL, search, email, Slack, MCP, audio, PDF extraction, CSV analysis, image generation) and you can [add your own](docs/agents/tool_creation.md) in a single file.

## From chat to autopilot

The same YAML file works across four escalating modes. You start by chatting with it. When it works, you let it run on its own. When you trust it, you deploy it as a daemon. No rewrite between stages.

**Interactive and one-shot:**

```bash
initrunner run role.yaml -i              # REPL: chat back and forth
initrunner run role.yaml -p "Scan for security issues"  # one prompt, one response
```

**Autonomous:** Add `-a` and the agent keeps going. It builds a task list, works through each item, reflects on progress, and finishes when everything is done. You set the budget so it can't run away.

```bash
initrunner run role.yaml -a -p "Scan this repo for security issues and file a report"
```

```yaml
spec:
  autonomy:
    compaction: { enabled: true, threshold: 30 }
  guardrails:
    max_iterations: 15
    autonomous_token_budget: 100000
    autonomous_timeout_seconds: 600
```

Four reasoning strategies control how the agent thinks through multi-step work: `react` (default), `todo_driven`, `plan_execute`, and `reflexion`. Budget enforcement, iteration limits, timeout, and spin guards (consecutive turns with no tool calls) keep autonomous runs bounded. See [Autonomy](docs/orchestration/autonomy.md) · [Guardrails](docs/configuration/guardrails.md).

**Daemon:** Add triggers and switch to `--daemon`. The agent runs continuously, reacting to cron schedules, file changes, webhooks, Telegram messages, or Discord mentions. Each event fires a single prompt-response cycle.

```yaml
spec:
  triggers:
    - type: cron
      schedule: "0 9 * * 1"
      prompt: "Generate the weekly status report."
    - type: file_watch
      paths: [./src]
      prompt_template: "File changed: {path}. Review it."
    - type: telegram
      allowed_user_ids: [123456789]
```

```bash
initrunner run role.yaml --daemon   # runs until Ctrl+C
```

Six trigger types: cron, webhook, file_watch, heartbeat, telegram, and discord. The daemon hot-reloads role changes without restarting, enforces daily and lifetime token budgets, and runs up to 4 triggers concurrently. See [Triggers](docs/core/triggers.md) · [Telegram](docs/getting-started/telegram.md) · [Discord](docs/getting-started/discord.md).

**Autopilot:** A daemon responds. An autopilot *thinks, then* responds. Someone messages your Telegram bot "find me flights from NYC to London next week" -- in daemon mode, you get one shot at an answer. In autopilot, the agent searches the web, compares options, checks dates, and sends back something worth reading.

```bash
initrunner run role.yaml --autopilot   # every trigger gets the full autonomous loop
```

`--autopilot` is `--daemon` where every trigger runs multi-step autonomous execution instead of single-shot. Same guardrails as `-a`: iteration limits, token budgets, spin guards, `finish_task`. The agent plans, uses tools, reflects, and replies when it's done.

You can also be selective. Set `autonomous: true` on individual triggers and leave the rest as quick single-shot responses.

```yaml
spec:
  triggers:
    - type: telegram
      autonomous: true          # think, research, then reply
    - type: cron
      schedule: "0 9 * * 1"
      prompt: "Generate the weekly status report."
      autonomous: true          # plan, gather data, write, review
    - type: file_watch
      paths: [./src]
      prompt_template: "File changed: {path}. Review it."
      # autonomous: false (default) -- quick single response
```

Agents can self-schedule follow-up tasks within a run. See [Autonomy](docs/orchestration/autonomy.md) · [Guardrails](docs/configuration/guardrails.md).

**Memory carries across everything.** Episodic, semantic, and procedural memory persist across interactive sessions, autonomous runs, and daemon triggers. After each session, consolidation extracts durable facts from episode history using an LLM. The agent doesn't just run. It learns. See [Memory](docs/core/memory.md).

## Security

InitRunner ships 12 security layers. They're opt-in via the `security:` config key, not on by magic, but they're integrated and ready to use. Roles without a `security:` section get safe defaults. The point is that these capabilities exist in the box rather than being something you bolt on from a third-party library six months into production.

**Input:** Server middleware (Bearer auth with timing-safe comparison, rate limiting, body size limits, HTTPS enforcement, security headers, CORS). Content policy engine (profanity filter, blocked-pattern matching, prompt length limits, optional LLM topic classifier). Input guard capability (PydanticAI `before_run` hook that validates prompts before the agent starts).

**Authorization:** [InitGuard](https://github.com/initrunner/initguard) ABAC policy engine (agents get identity from role metadata, every tool call and delegation checked against Cedar-like policies). Argument-level permission rules (per-tool allow/deny glob patterns, deny-wins precedence). SQL authorization callbacks (blocks dangerous operations at the engine level).

**Execution:** PEP 578 audit hook sandbox (per-thread enforcement of filesystem write restrictions, subprocess blocking, private-IP network blocking, dangerous-module import blocking, eval/exec blocking). Docker container sandboxing (read-only rootfs, memory/CPU limits, network isolation, pid limits). Environment variable scrubbing (prefix and suffix matching strips sensitive keys from every subprocess environment).

**Budget:** Token-bucket rate limiting for API requests. Token budgets at five granularities: per-run, per-session, per-autonomous-run, per-daemon-daily, and per-daemon-lifetime.

**Audit:** Append-only SQLite trail with automatic secret scrubbing (16 regex patterns covering GitHub tokens, AWS keys, Stripe keys, Slack tokens, and more). Every tool call, delegation event, and security violation is logged.

```bash
export INITRUNNER_POLICY_DIR=./policies
initrunner run role.yaml                  # tool calls + delegation checked against policies
```

See [Agent Policy](docs/security/agent-policy.md) · [Security](docs/security/security.md) · [Guardrails](docs/configuration/guardrails.md).

## Why InitRunner

**A YAML file is the agent.** One file. Readable, diffable, PR-reviewable. You open it and know what the agent does: which model, which tools, what knowledge sources, what guardrails. No Python class hierarchy to learn before you can configure a tool. New team members read the YAML and understand. You review agent changes in pull requests like any other config.

**Same file, different flag.** The agent you prototyped interactively with `-i` is the exact same one you deploy as a daemon with `--daemon`. No rewrite, no deployment adapter, no "production mode" that works differently from development. You pick the execution mode at runtime with a flag, not at design time with an architecture decision.

**Security is in the box, not bolted on.** Most agent frameworks treat security as "add auth middleware when you get to production." InitRunner ships with a policy engine, PII redaction, sandboxing, tool authorization, and audit logging already integrated. You turn them on with config, not with a weekend of plumbing.

**Autonomy with brakes.** The agent runs unsupervised, but it can't run away. Token budgets, iteration limits, wall-clock timeouts, and spin guards are all declarative YAML config. You decide how much rope to give it before a single autonomous run starts.

## Knowledge and memory

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

## Multi-agent orchestration

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

## User interfaces

<p align="center">
  <img src="assets/screenshot-dashboard.png" alt="InitRunner Dashboard" width="800"><br>
  <em>Dashboard: agents, activity, compositions, and teams at a glance</em>
</p>

```bash
pip install "initrunner[dashboard]"
initrunner dashboard                  # opens http://localhost:8100
```

Run agents, build compositions visually, and dig through audit trails. Also available as a native desktop window (`initrunner desktop`). See [Dashboard docs](docs/interfaces/dashboard.md).

## Everything else

| Feature | Command / config | Docs |
|---------|-----------------|------|
| **Skills** (reusable tool + prompt bundles) | `spec: { skills: [../skills/web-researcher] }` | [Skills](docs/agents/skills_feature.md) |
| **Team mode** (multi-persona on one task) | `kind: Team` + `spec: { personas: {…} }` | [Team Mode](docs/orchestration/team_mode.md) |
| **API server** (OpenAI-compatible endpoint) | `initrunner run agent.yaml --serve --port 3000` | [Server](docs/interfaces/server.md) |
| **Multimodal** (images, audio, video, docs) | `initrunner run role.yaml -p "Describe" -A photo.png` | [Multimodal](docs/core/multimodal.md) |
| **Structured output** (validated JSON schemas) | `spec: { output: { schema: {…} } }` | [Structured Output](docs/core/structured-output.md) |
| **Evals** (test agent output quality) | `initrunner test role.yaml -s eval.yaml` | [Evals](docs/core/evals.md) |
| **MCP gateway** (expose agents as MCP tools) | `initrunner mcp serve agent.yaml` | [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| **MCP toolkit** (tools without an agent) | `initrunner mcp toolkit` | [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| **Capabilities** (native PydanticAI features) | `spec: { capabilities: [Thinking, WebSearch] }` | [Capabilities](docs/core/capabilities.md) |
| **Observability** (OpenTelemetry integration) | `spec: { observability: { enabled: true } }` | [Observability](docs/core/observability.md) |
| **Configure** (switch provider/model on any role) | `initrunner configure role.yaml --provider groq` | [Providers](docs/configuration/providers.md) |
| **Reasoning** (structured thinking patterns) | `spec: { reasoning: { pattern: plan_execute } }` | [Reasoning](docs/core/reasoning.md) |
| **Tool search** (on-demand tool discovery) | `spec: { tool_search: { enabled: true } }` | [Tool Search](docs/core/tool-search.md) |

## Architecture

```
initrunner/
  agent/        Role schema, loader, executor, 28 self-registering tools
  authz.py      InitGuard ABAC policy engine integration
  runner/       Single-shot, REPL, autonomous, daemon execution modes
  compose/      Multi-agent orchestration via compose.yaml
  triggers/     Cron, file watcher, webhook, heartbeat, Telegram, Discord
  stores/       Document + memory stores (LanceDB, zvec)
  ingestion/    Extract -> chunk -> embed -> store pipeline
  mcp/          MCP server integration and gateway
  audit/        Append-only SQLite audit trail with secret scrubbing
  middleware.py Server security middleware (auth, rate limit, CORS, headers)
  services/     Shared business logic layer
  cli/          Typer + Rich CLI entry point
```

Built on [PydanticAI](https://ai.pydantic.dev/) for the agent framework, Pydantic for config validation, LanceDB for vector search. See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup.

## Distribution

**InitHub:** Browse and install community agents at [hub.initrunner.ai](https://hub.initrunner.ai/). Publish your own with `initrunner publish`. See [Registry](docs/agents/registry.md).

**OCI registries:** Push role bundles to any OCI-compliant registry: `initrunner publish oci://ghcr.io/org/my-agent --tag 1.0.0`. See [OCI Distribution](docs/core/oci-distribution.md).

**Cloud deploy:**

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/FROM_REPO?referralCode=...)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/vladkesler/initrunner)

## Documentation

| Area | Key docs |
|------|----------|
| Getting started | [Installation](docs/getting-started/installation.md) · [Setup](docs/getting-started/setup.md) · [Tutorial](docs/getting-started/tutorial.md) · [CLI Reference](docs/getting-started/cli.md) |
| Quickstarts | [RAG](docs/getting-started/rag-quickstart.md) · [Docker](docs/getting-started/docker.md) · [Discord Bot](docs/getting-started/discord.md) · [Telegram Bot](docs/getting-started/telegram.md) |
| Agents & tools | [Tools](docs/agents/tools.md) · [Tool Creation](docs/agents/tool_creation.md) · [Tool Search](docs/core/tool-search.md) · [Skills](docs/agents/skills_feature.md) · [Providers](docs/configuration/providers.md) |
| Intelligence | [Reasoning](docs/core/reasoning.md) · [Intent Sensing](docs/core/intent_sensing.md) · [Autonomy](docs/orchestration/autonomy.md) · [Structured Output](docs/core/structured-output.md) |
| Knowledge & memory | [Ingestion](docs/core/ingestion.md) · [Memory](docs/core/memory.md) · [Multimodal Input](docs/core/multimodal.md) |
| Orchestration | [Patterns Guide](docs/orchestration/patterns-guide.md) · [Compose](docs/orchestration/agent_composer.md) · [Delegation](docs/orchestration/delegation.md) · [Team Mode](docs/orchestration/team_mode.md) · [Triggers](docs/core/triggers.md) |
| Interfaces | [Dashboard](docs/interfaces/dashboard.md) · [API Server](docs/interfaces/server.md) · [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| Distribution | [OCI Distribution](docs/core/oci-distribution.md) · [Shareable Templates](docs/getting-started/shareable-templates.md) |
| Security | [Security Model](docs/security/security.md) · [Agent Policy](docs/security/agent-policy.md) · [Guardrails](docs/configuration/guardrails.md) |
| Operations | [Audit](docs/core/audit.md) · [Reports](docs/core/reports.md) · [Evals](docs/core/evals.md) · [Doctor](docs/operations/doctor.md) · [Observability](docs/core/observability.md) · [CI/CD](docs/operations/cicd.md) |

## Examples

```bash
initrunner examples list               # 60+ agents, teams, and compose projects
initrunner examples copy code-reviewer # copy to current directory
```

## Upgrading

Run `initrunner doctor --role role.yaml` to check any role file for deprecated fields, schema errors, and spec version issues. Add `--fix` to auto-repair, or `--fix --yes` for CI. See [Deprecations](docs/operations/deprecations.md).

## Community & contributing

- [Discord](https://discord.gg/GRTZmVcW): chat, ask questions, share roles
- [GitHub Issues](https://github.com/vladkesler/initrunner/issues): bug reports and feature requests
- [Changelog](CHANGELOG.md): release notes

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup and PR guidelines.

## License

Licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option.

---

<p align="center"><sub>v2026.4.4</sub></p>
