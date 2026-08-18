# What Do I Need?

An agent file only needs a name, a `prompt`, and usually a `model`. This page maps your goals to the fields you add. For interactive setup, use `initrunner setup` ([Setup Wizard](setup.md)). For a hands-on walkthrough, see the [Tutorial](tutorial.md).

Envelope files (`apiVersion` / `kind: Agent|Team|Flow`) still load. New files should be flat.

## Every Agent Needs These

```yaml
name: my-agent
model: openai:gpt-5-mini
prompt: |
  Your system prompt here.
guardrails:
  max_tokens_per_run: 10000
  max_tool_calls: 5
  timeout_seconds: 60
```

| Field | What it does | Docs |
|-------|-------------|------|
| `prompt` | System instructions | [Tutorial Step 1](tutorial.md#step-1-your-first-agent--a-simple-summarizer) |
| `model` | `provider:name` string, or a mapping | [Provider Configuration](../configuration/providers.md) |
| `guardrails` | Token budget, tool call cap, timeout | [Guardrails](../configuration/guardrails.md) |

See `examples/roles/hello-world.yaml` for a minimal working agent.

## Start Here

```
What does your agent need to do?
  |
  Just answer questions (no tools)?
  |  Yes --> Base agent only (prompt + model + guardrails)
  |          Example: hello-world.yaml
  |
  No --> Does it need to interact with external systems?
          |
          Yes --> Add tools (see matrix below)
          |
          Does it need to answer from your documents?
          |  Yes --> Add ingest
          |          See: docs/getting-started/rag-quickstart.md
          |
          Does it need to remember across sessions?
          |  Yes --> Add memory
          |          See: docs/core/memory.md
          |
          Does it need to run on a schedule or react to events?
          |  Yes --> Add triggers + sinks, run with --daemon
          |          See: docs/core/triggers.md
          |
          Does it need to plan, iterate, and self-correct?
          |  Yes --> Add reasoning + autonomy
          |          See: docs/core/reasoning.md
          |
          Does it need to return structured JSON?
          |  Yes --> Add output
          |          See: docs/core/structured-output.md
          |
          Does it need multiple agents?
             |
             Yes --> Add `agents:` (inline prompts or `use:` files).
                     `run: sequential` for a preset pipeline.
                     `then:` on a child for a graph.
                     Or add `delegate` / `spawn` tools if the model
                     should pick who runs.
```

## Goal-to-Config Matrix

Every row assumes the base fields (`prompt`, `model`, `guardrails`) are already set. **Fields to Add** shows what you layer on top.

| Goal | Fields to Add | Common Tool Types | Optional | Example | Docs |
|------|--------------|-------------------|----------|---------|------|
| Simple chatbot | -- | -- | `memory` | `hello-world.yaml` | [Tutorial](tutorial.md) |
| Web research | `tools` | search, web_reader | `memory`, `reasoning` | `web-searcher.yaml` | [Tools](../agents/tools.md) |
| Document Q&A (RAG) | `ingest`, `tools` | filesystem (read_only) | `memory` | `rag-agent/` | [RAG Quickstart](rag-quickstart.md), [RAG Guide](../core/rag-guide.md) |
| Local/offline RAG | `ingest`, `model` (both ollama) | -- | -- | `local-rag/` | [Ollama](../configuration/ollama.md) |
| Memory assistant | `memory` | datetime | consolidation, procedural | `memory-assistant.yaml` | [Memory](../core/memory.md) |
| Code review / git | `tools` | git, filesystem | shell | `pr-reviewer.yaml` | [Tools](../agents/tools.md) |
| Data analysis | `tools` | sql, python, filesystem | `reasoning` | `data-analyst/` | [Tools](../agents/tools.md) |
| Scheduled daemon | `triggers`, `sinks`, `guardrails` (daemon budgets) | http, slack | `memory` | `uptime-monitor.yaml` | [Triggers](../core/triggers.md), [Sinks](../orchestration/sinks.md) |
| Telegram bot | `triggers` (telegram), `memory` | web_reader, audio | consolidation | `telegram-assistant/` | [Telegram](telegram.md) |
| Discord bot | `triggers` (discord), `memory` | web_reader, audio | consolidation | `discord-assistant/` | [Discord](discord.md) |
| Webhook processor | `triggers` (webhook), `sinks`, `tools` | http | `security` | `webhook-processor.yaml` | [Triggers](../core/triggers.md) |
| Structured JSON | `output` | -- | -- | `invoice-classifier.yaml` | [Structured Output](../core/structured-output.md) |
| Autonomous planner | `reasoning`, `autonomy`, `tools` | think, todo | filesystem | `reasoning-planner/` | [Reasoning](../core/reasoning.md), [Autonomy](../orchestration/autonomy.md) |
| Multiple agents | varies by pattern | delegate, spawn | `reasoning` | `multi-agent/`, `research-team/` | [Multi-Agent Guide](../orchestration/multi-agent-guide.md) |
| Production hardening | `security`, `observability`, `resources` | any | docker sandbox | `traced-agent.yaml` | [Security](../security/security.md), [Observability](../core/observability.md) |

> **Multi-agent patterns** have distinct config surfaces: Team uses `agents` + `run`, Flow uses `agents` + `then` / `after`, and Spawn/Delegate use `tools`. See the [Multi-Agent Guide](../orchestration/multi-agent-guide.md) for the full decision tree.

All examples are in `examples/roles/`. Run `initrunner examples list` to browse them, or `initrunner new --from <name>` to copy one.

## Fields You Probably Don't Need Yet

These fields exist for advanced or production use cases. Skip them until you need them.

- **`security`** -- Content policies, PII redaction, rate limits, Docker sandboxing. Add when exposing agents to untrusted input. [Security](../security/security.md), [Docker Sandbox](../security/docker-sandbox.md)
- **`observability`** -- OpenTelemetry tracing for production debugging. [Observability](../core/observability.md)
- **`resources`** -- Memory/CPU limits for containerized deployments.
- **`capabilities`** -- Provider-specific features like extended thinking and native web search. [Capabilities](../core/capabilities.md)
- **`auto_skills`** -- Auto-discovered skills from `./skills/`. Enabled by default; only configure to tune `max_skills`. [Skills](../agents/skills_feature.md)
- **`tool_search`** -- Meta-tool that lets the LLM search available tools at runtime. Useful with large tool sets. [Tool Search](../core/tool-search.md)
- **`daemon`** -- Hot-reload settings for daemon mode. Defaults are fine for most use cases.

## What's Next

- **First time?** [Tutorial](tutorial.md) -- build a complete agent step by step
- **Want a ready-made template?** `initrunner examples list` / `initrunner new --from <name>` — browse bundled examples
- **Need multiple agents?** [Multi-Agent Guide](../orchestration/multi-agent-guide.md) -- pick the right coordination pattern
- **Going to production?** [Security](../security/security.md), [Guardrails](../configuration/guardrails.md), [Observability](../core/observability.md)
