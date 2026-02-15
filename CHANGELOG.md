# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-02-15

First public release candidate.

### Added

- **Agent runner** with single-shot, interactive REPL (`--resume` support), and daemon modes
- **Role YAML schema** with Pydantic validation and discriminated unions for type-safe configs
- **Built-in tools**: filesystem, HTTP, web_reader, datetime, Python (subprocess isolation), SQL (read-only SQLite), git
- **MCP tool support** via FastMCP integration
- **Document ingestion pipeline**: extract (PDF/DOCX/XLSX), chunk, embed, store with batched embedding
- **sqlite-vec vector store** with dimension auto-detection, glob SQL pre-filtering, and auto-retrieval tool
- **Memory system**: remember/recall/list_memories tools with SQLite persistence and session resume
- **Trigger system**: cron (croniter), file watcher (watchfiles), and webhook (starlette/uvicorn) triggers
- **Compose orchestration**: multi-agent services via `compose.yaml` with delegate sinks, health monitoring, restart policies, and cycle detection
- **Audit trail**: append-only SQLite log with auto-pruning (configurable retention and max records)
- **TUI dashboard** (optional `[tui]` extra): Textual-based k9s-style interface with roles, chat, audit, ingest, memory, and daemon screens
- **Web dashboard** (optional `[dashboard]` extra): FastAPI + Next.js browser UI with WebSocket chat, SSE ingestion, and daemon event streaming
- **OpenAI-compatible API server** (`initrunner serve`): serve any role as a chat completions endpoint with optional API key auth
- **Agent pipelines** (`initrunner pipeline`): chain multiple agents in sequence
- **Role registry** (`initrunner install/search/update`): install roles from GitHub or the community index
- **Tool plugins** (`initrunner plugins`): discover and list third-party tool plugins
- **Test suites** (`initrunner test`): run test suites against agent roles
- **Agent delegation** for multi-agent workflows
- **Skills system** for reusable agent capabilities
- **Content safety policies** with configurable enforcement
- **Tool sandboxing** via PEP 578 audit hooks
- **CLI** via Typer: `run`, `validate`, `init`, `ingest`, `daemon`, `ui`, `compose up/validate`, `memory clear/export`
- **Multi-provider support**: OpenAI, Anthropic, Google, Groq, Mistral (via pydantic-ai-slim extras)
- **Context window safety**: REPL history sliding window, max_resume_messages, daemon session pruning
- **Security hardening**: env var scrubbing for Python/git subprocesses, SQL query_only pragma, bounded tool results
