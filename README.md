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

Define an agent in one YAML file. Chat with it. When it works, let it run autonomously. When you trust it, deploy it as a daemon that reacts to cron schedules, file changes, webhooks, and Telegram messages. Same file the whole way. No rewrite between prototyping and production.

## Quickstart

```bash
curl -fsSL https://initrunner.ai/install.sh | sh
initrunner setup        # wizard: pick provider, model, API key
```

Or: `uv pip install "initrunner[recommended]"` / `pipx install "initrunner[recommended]"`. See [Installation](docs/getting-started/installation.md).

### Starters

Eight starters you can run in one command. Browse the full catalog with `initrunner run --list`. The model is auto-detected from your API key.

| Starter | What it does |
|---------|-------------|
| `helpdesk` | Q&A agent over your docs (markdown, PDF, HTML, Word) with citations and per-user memory |
| `scholar` | Three-agent research team: planner, web researcher, synthesizer, with shared memory |
| `reviewer` | Multi-perspective code review: architect, security, maintainer |
| `reader` | Index a codebase, chat about architecture, remember patterns across sessions |
| `scout` | Web research with structured briefings and sourced citations |
| `writer` | Topic-to-article pipeline: researcher, writer, editor/fact-checker, driven by webhook or cron |
| `mail` | Monitors inbox, triages, drafts replies, alerts Slack on urgent mail |
| `librarian` | Knowledge-base Q&A agent with document ingestion |

### Build your own

```bash
initrunner new "a research assistant that summarizes papers"
# generates role.yaml, then asks: "Run it now? [Y/n]"

initrunner new "a regex explainer" --run "what does ^[a-z]+$ match?"
# generate and execute in one command

initrunner run --ingest ./docs/    # skip YAML entirely, just chat with your docs
```

Browse community agents at [InitHub](https://hub.initrunner.ai/): `initrunner search "code review"` / `initrunner install alice/code-reviewer`.

**Docker:**

```bash
docker run --rm -it -e OPENAI_API_KEY ghcr.io/vladkesler/initrunner:latest run -i
```

## One file, four modes

Here's a role file:

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

That file works four ways:

```bash
initrunner run reviewer.yaml -i                          # interactive REPL
initrunner run reviewer.yaml -p "Review PR #42"          # one prompt, one response
initrunner run reviewer.yaml -a -p "Audit the whole repo"  # autonomous loop
initrunner run reviewer.yaml --daemon                    # runs on triggers
```

The `model:` block is optional. Omit it and InitRunner auto-detects from your API key. Works with Anthropic, OpenAI, Google, Groq, Mistral, Cohere, xAI, OpenRouter, Ollama, and any OpenAI-compatible endpoint.

### Autonomous

Add `-a` and the agent builds a task list, works each item, reflects on progress, and stops when everything's done. Four reasoning strategies control how: `react` (default), `todo_driven`, `plan_execute`, `reflexion`.

```yaml
spec:
  autonomy:
    compaction: { enabled: true, threshold: 30 }
  guardrails:
    max_iterations: 15
    autonomous_token_budget: 100000
    autonomous_timeout_seconds: 600
```

Spin guards catch loops without progress. History compaction summarizes old context so long runs don't exhaust the token window. Iteration, token, and wall-clock caps bound every run. See [Autonomy](docs/orchestration/autonomy.md) · [Guardrails](docs/configuration/guardrails.md).

### Daemon

Add triggers and switch to `--daemon`. The agent runs continuously. Each event fires one prompt-response cycle.

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

Six trigger types: cron, webhook, file_watch, heartbeat, telegram, discord. The daemon hot-reloads role changes without restarting and runs up to four triggers concurrently. See [Triggers](docs/core/triggers.md).

### Autopilot

`--autopilot` is `--daemon` plus the autonomous loop on every trigger. A Telegram message like "find me flights from NYC to London next week" in daemon mode gets one LLM turn. In autopilot, the agent searches flights, compares options, checks dates, and replies with a shortlist.

```bash
initrunner run role.yaml --autopilot
```

Or go selective: set `autonomous: true` on individual triggers, leave the rest single-shot.

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
      # default: single response
```

### Memory across modes

Semantic memory (facts the agent learns), episodic memory (what happened in past sessions), and procedural memory (how the agent prefers to solve things) persist across interactive sessions, autonomous runs, and daemon triggers. After each session, an LLM consolidates durable facts into the store. Knowledge accumulates over time, not just within a single run.

## Agents that learn

Point your agent at a directory. It extracts, chunks, embeds, and indexes your documents automatically. During conversation, the agent searches the index and cites what it finds. New and changed files re-index on every run.

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
cd ~/myproject
initrunner run reader -i   # indexes your code, then starts Q&A
```

Consolidation is the interesting part. After each session, an LLM reads the conversation and distills it into the semantic store. Facts the agent learns during a Tuesday debugging session show up when it's reviewing code on Thursday. Shared memory across flows lets teams of agents build knowledge together. See [Memory](docs/core/memory.md) · [Ingestion](docs/core/ingestion.md) · [RAG Quickstart](docs/getting-started/rag-quickstart.md).

## Security

Five controls ship with the framework and turn on via config keys. Roles without a `security:` section get safe defaults.

**Input validation.** A content policy engine (blocked patterns, prompt length limits, optional LLM topic classifier) plus an input guard capability validate prompts before the agent starts.

**Tool authorization.** [InitGuard](https://github.com/initrunner/initguard) ABAC policy engine checks every tool call and delegation against CEL policies. Per-tool allow/deny glob patterns enforce argument-level permissions.

**Sandboxed code execution.** PEP 578 audit hooks block filesystem writes outside allowlisted paths, block `subprocess.Popen` and `os.system` by default, block `socket.connect` to private IPs, and always block `ctypes.dlopen` and new threads. Docker container sandboxing adds read-only rootfs, memory and CPU limits, and network isolation on top.

**Tamper-evident audit trail.** Every run writes to an append-only SQLite audit log, HMAC-SHA256 signed over the previous record's hash. `initrunner audit verify-chain` detects any middle-row mutation, reorder, or deletion. Secrets are scrubbed on write.

**Encrypted credential vault.** `initrunner vault init` creates `~/.initrunner/vault.enc`, encrypted with Fernet + scrypt from your passphrase. API keys resolve from env vars first, then the vault, so existing `api_key_env:` and `${VAR}` placeholders keep working.

```yaml
spec:
  security:
    audit_hooks_enabled: true
    block_private_ips: true
    input_guard:
      max_prompt_chars: 10000
      blocked_patterns: ["(?i)rm -rf /"]
```

See [Security](docs/security/security.md) · [Agent Policy](docs/security/agent-policy.md) · [Credential Vault](docs/security/vault.md) · [Audit Chain](docs/security/audit-chain.md) · [Guardrails](docs/configuration/guardrails.md).

## Cost control

USD budgets cap daemon spend. Hit the cap and triggers stop firing until the window resets.

```yaml
spec:
  guardrails:
    daemon_daily_cost_budget: 5.00    # USD per day
    daemon_weekly_cost_budget: 25.00  # USD per week
```

Cost estimation uses [genai-prices](https://pypi.org/project/genai-prices/) to compute spend per model and provider. Every run logs its cost to the audit trail. The dashboard plots cost across agents and time ranges. See [Cost Tracking](docs/core/cost-tracking.md).

## Multi-agent orchestration

Chain agents into flows. One agent's output feeds the next.

```yaml
apiVersion: initrunner/v1
kind: Flow
metadata: { name: email-chain }
spec:
  agents:
    inbox-watcher:
      role: roles/inbox-watcher.yaml
      sink: { type: delegate, target: triager }
    triager:
      role: roles/triager.yaml
      sink: { type: delegate, strategy: sense, target: [researcher, responder] }
    researcher: { role: roles/researcher.yaml }
    responder: { role: roles/responder.yaml }
```

```bash
initrunner flow up flow.yaml
```

Sense routing picks the right target per message using keyword scoring first (zero API calls); only ambiguous cases fall back to an LLM tiebreak.

**Team mode** gives multiple perspectives on one task without a full flow. Define personas in one file with three strategies: sequential handoff, parallel execution, or debate (multi-round argumentation with synthesis). See [Patterns Guide](docs/orchestration/patterns-guide.md) · [Team Mode](docs/orchestration/team_mode.md) · [Flow](docs/orchestration/flow.md).

## MCP and interfaces

Agents consume any [MCP](https://modelcontextprotocol.io/) server as a tool source (stdio, SSE, streamable-http). Going the other direction, expose your agents *as* MCP tools so Claude Code, Cursor, and Windsurf can call them:

```bash
initrunner mcp serve agent.yaml          # agent becomes an MCP tool
initrunner mcp toolkit --tools search,sql  # expose raw tools, no LLM needed
```

See [MCP Gateway](docs/interfaces/mcp-gateway.md).

<p align="center">
  <img src="assets/screenshot-dashboard.png" alt="InitRunner Dashboard" width="800"><br>
  <em>Dashboard: run agents, build flows, dig through audit trails</em>
</p>

```bash
pip install "initrunner[dashboard]"
initrunner dashboard                  # opens http://localhost:8100
```

Also available as a native desktop window (`initrunner desktop`). See [Dashboard](docs/interfaces/dashboard.md).

## Everything else

| Feature | Command / config | Docs |
|---------|-----------------|------|
| **Skills** (reusable tool + prompt bundles) | `spec: { skills: [../skills/web-researcher] }` | [Skills](docs/agents/skills_feature.md) |
| **API server** (OpenAI-compatible endpoint) | `initrunner run agent.yaml --serve --port 3000` | [Server](docs/interfaces/server.md) |
| **A2A server** (agent-to-agent protocol) | `initrunner a2a serve agent.yaml` | [A2A](docs/interfaces/a2a.md) |
| **Multimodal** (images, audio, video, docs) | `initrunner run role.yaml -p "Describe" -A photo.png` | [Multimodal](docs/core/multimodal.md) |
| **Structured output** (validated JSON schemas) | `spec: { output: { schema: {...} } }` | [Structured Output](docs/core/structured-output.md) |
| **Evals** (test agent output quality) | `initrunner test role.yaml -s eval.yaml` | [Evals](docs/core/evals.md) |
| **Capabilities** (native PydanticAI features) | `spec: { capabilities: [Thinking, WebSearch] }` | [Capabilities](docs/core/capabilities.md) |
| **Observability** (OpenTelemetry) | `spec: { observability: { enabled: true } }` | [Observability](docs/core/observability.md) |
| **Reasoning** (structured thinking patterns) | `spec: { reasoning: { pattern: plan_execute } }` | [Reasoning](docs/core/reasoning.md) |
| **Tool search** (on-demand tool discovery) | `spec: { tool_search: { enabled: true } }` | [Tool Search](docs/core/tool-search.md) |
| **Configure** (switch provider/model) | `initrunner configure role.yaml --provider groq` | [Providers](docs/configuration/providers.md) |

## Architecture

```
initrunner/
  agent/        Role schema, loader, executor, self-registering tools
  runner/       Single-shot, REPL, autonomous, daemon execution modes
  flow/         Multi-agent orchestration via flow.yaml
  triggers/     Cron, file watcher, webhook, heartbeat, Telegram, Discord
  stores/       Document + memory stores (LanceDB, zvec)
  ingestion/    Extract -> chunk -> embed -> store pipeline
  mcp/          MCP server integration and gateway
  audit/        Append-only SQLite audit trail with secret scrubbing
  services/     Shared business logic layer
  cli/          Typer + Rich CLI entry point
```

Built on [PydanticAI](https://ai.pydantic.dev/). See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup.

## Distribution

**InitHub:** Browse and install community agents at [hub.initrunner.ai](https://hub.initrunner.ai/). Publish your own with `initrunner publish`.

**OCI registries:** Push role bundles to any OCI-compliant registry: `initrunner publish oci://ghcr.io/org/my-agent --tag 1.0.0`. See [OCI Distribution](docs/core/oci-distribution.md).

## Documentation

| Area | Key docs |
|------|----------|
| Getting started | [Installation](docs/getting-started/installation.md) · [Setup](docs/getting-started/setup.md) · [Tutorial](docs/getting-started/tutorial.md) · [CLI Reference](docs/getting-started/cli.md) |
| Quickstarts | [RAG](docs/getting-started/rag-quickstart.md) · [Docker](docs/getting-started/docker.md) · [Discord Bot](docs/getting-started/discord.md) · [Telegram Bot](docs/getting-started/telegram.md) |
| Agents & tools | [Tools](docs/agents/tools.md) · [Tool Creation](docs/agents/tool_creation.md) · [Tool Search](docs/core/tool-search.md) · [Skills](docs/agents/skills_feature.md) · [Providers](docs/configuration/providers.md) |
| Intelligence | [Reasoning](docs/core/reasoning.md) · [Intent Sensing](docs/core/intent_sensing.md) · [Autonomy](docs/orchestration/autonomy.md) · [Structured Output](docs/core/structured-output.md) |
| Knowledge & memory | [Ingestion](docs/core/ingestion.md) · [Memory](docs/core/memory.md) · [Multimodal Input](docs/core/multimodal.md) |
| Orchestration | [Patterns Guide](docs/orchestration/patterns-guide.md) · [Flow](docs/orchestration/flow.md) · [Delegation](docs/orchestration/delegation.md) · [Team Mode](docs/orchestration/team_mode.md) · [Triggers](docs/core/triggers.md) |
| Interfaces | [Dashboard](docs/interfaces/dashboard.md) · [API Server](docs/interfaces/server.md) · [MCP Gateway](docs/interfaces/mcp-gateway.md) · [A2A](docs/interfaces/a2a.md) |
| Distribution | [OCI Distribution](docs/core/oci-distribution.md) · [Shareable Templates](docs/getting-started/shareable-templates.md) |
| Security | [Security Model](docs/security/security.md) · [Credential Vault](docs/security/vault.md) · [Audit Chain](docs/security/audit-chain.md) · [Agent Policy](docs/security/agent-policy.md) · [Guardrails](docs/configuration/guardrails.md) |
| Operations | [Audit](docs/core/audit.md) · [Cost Tracking](docs/core/cost-tracking.md) · [Reports](docs/core/reports.md) · [Evals](docs/core/evals.md) · [Doctor](docs/operations/doctor.md) · [Observability](docs/core/observability.md) · [CI/CD](docs/operations/cicd.md) |

## Examples

```bash
initrunner examples list               # browse all agents, teams, and flows
initrunner examples copy code-reviewer # copy to current directory
```

## Upgrading

Run `initrunner doctor --role role.yaml` to check any role file for deprecated fields, schema errors, and spec version issues. Add `--fix` to auto-repair. Use `--flow flow.yaml` to validate an entire flow and its referenced roles. See [Deprecations](docs/operations/deprecations.md).

## Community

- [Discord](https://discord.gg/GRTZmVcW): chat, ask questions, share roles
- [GitHub Issues](https://github.com/vladkesler/initrunner/issues): bug reports and feature requests
- [Changelog](CHANGELOG.md): release notes
- [CONTRIBUTING.md](CONTRIBUTING.md): dev setup and PR guidelines

## License

Licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option.

---

<p align="center"><sub>v2026.4.15</sub></p>
