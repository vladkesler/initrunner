# InitRunner

YAML-first AI agent platform. Define agents as declarative `role.yaml` files — model, tools, triggers, ingestion, guardrails — and run them as one-shot commands, interactive REPLs, trigger-driven daemons, or OpenAI-compatible API servers. Includes built-in RAG, long-term memory, multi-agent orchestration via `compose.yaml`, audit logging, and a self-registering tool system.

## Tech Stack

Python 3.11+ · PydanticAI (agent framework) · Pydantic (config/validation) · Typer + Rich (CLI) · SQLite + sqlite-vec (audit, vector stores) · Jinja2 + HTMX + DaisyUI (dashboard) · hatchling (build) · uv (package manager)

## Development Workflow

```bash
uv sync                      # install deps
uv run pytest tests/ -v      # run tests (710 tests)
uv run ruff check .          # lint
uv run ruff format .         # format
uv run ty check              # type check
```

## Project Layout

```
initrunner/              # main package (flat layout)
├── agent/               # role schema, loader, executor, tool registry
│   └── tools/           # self-registering tool modules
├── api/                 # FastAPI web dashboard (server-rendered HTML + JSON API)
├── audit/               # append-only SQLite audit trail
├── cli/                 # Typer CLI entry point
├── compose/             # multi-agent orchestration (compose.yaml)
├── ingestion/           # extract → chunk → embed → store pipeline
├── mcp/                 # MCP server integration
├── runner/              # single-shot, REPL, autonomous, daemon modes
├── stores/              # DocumentStore + MemoryStore ABCs and sqlite-vec impls
├── triggers/            # cron, file watcher, webhook triggers
├── tui/                 # Textual terminal UI
├── services.py          # shared sync business logic (CLI, API, TUI all use this)
├── _templates/          # Jinja2 HTML templates (HTMX + DaisyUI)
├── _static/             # static assets (HTMX, Tailwind, DaisyUI CSS, app.js)
├── _compat.py           # optional dependency helpers
└── _html.py             # HTML fetch + markdown conversion
tests/                   # pytest test suite
examples/                # example role and compose YAML files
docs/                    # detailed documentation by subsystem
```

## Key Patterns

These rules apply to every task in this codebase:

- **Sync-first**: CLI is synchronous. Use PydanticAI's `run_sync`. Use threads (not asyncio) for concurrency (triggers, compose services).
- **Self-registering tools**: add a new tool by creating one file in `agent/tools/` using `@register_tool(type_name, ConfigClass)`. Auto-discovered via `pkgutil.iter_modules()`.
- **Lazy imports in CLI**: CLI commands use lazy imports so `--help` stays fast. Don't add top-level imports in `cli/main.py`.
- **`audit.log()` never raises**: audit failures must not crash agent runs.
- **Dataclasses for DTOs, Pydantic for config**: internal data (RunResult, AuditRecord) uses dataclasses. Role definitions and API schemas use Pydantic.
- **`services.py` is the shared layer**: all business logic lives here. CLI, API, and TUI are thin wrappers that call into `services.*`.

## Coding Conventions

- Run `ruff check` and `ruff format` before committing. Run `ty check` for type checking.
- Tests go in `tests/` mirroring the source layout. Use `pytest` fixtures and `unittest.mock`.
- Keep tool result sizes bounded (truncate with `[truncated]` marker). See existing tools for limits.
- Sensitive env vars must be scrubbed from subprocess environments (see `_SENSITIVE_ENV_KEYS` pattern).

## Documentation Index

Detailed docs live in `docs/`. Key references:

| Topic | File |
|---|---|
| CLI commands & usage | `docs/getting-started/cli.md` |
| Creating new tools | `docs/agents/tool_creation.md` |
| Tool registry internals | `docs/agents/registry.md` |
| Security model | `docs/security/security.md` |
| Ingestion pipeline | `docs/core/ingestion.md` |
| Memory system | `docs/core/memory.md` |
| RAG patterns & guide | `docs/core/rag-guide.md` |
| Triggers (cron/file/webhook) | `docs/core/triggers.md` |
| Autonomous execution | `docs/orchestration/autonomy.md` |
| Compose orchestration | `docs/orchestration/delegation.md`, `docs/orchestration/sinks.md` |
| Web dashboard | `docs/interfaces/dashboard.md` |
| Textual TUI | `docs/interfaces/tui.md` |
| Testing guide | `docs/operations/testing.md` |
| Auth & guardrails | `docs/security/auth.md`, `docs/configuration/guardrails.md` |
| CI/CD & releases | `docs/operations/cicd.md`, `docs/operations/pypi_publish.md` |
| Role generation & wizards | `docs/agents/role_generation.md` |
| Provider configuration | `docs/configuration/providers.md`, `docs/configuration/ollama.md` |
| Multimodal input | `docs/core/multimodal.md` |
