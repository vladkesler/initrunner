# InitRunner

YAML-first AI agent platform. Define agents as declarative `role.yaml` files — model, tools, triggers, ingestion, guardrails — and run them as one-shot commands, interactive REPLs, trigger-driven daemons, or OpenAI-compatible API servers. Includes built-in RAG, long-term memory, multi-agent orchestration via `flow.yaml`, audit logging, and a self-registering tool system.

## Tech Stack

Python 3.11+ · PydanticAI (agent framework) · Pydantic (config/validation) · Typer + Rich (CLI) · SQLite (audit) · LanceDB (vector stores) · hatchling (build) · uv (package manager)

## Development Workflow

```bash
uv sync                      # install deps
uv run pytest tests/ -v      # run tests (710 tests)
uv run ruff check .          # lint
uv run ruff format .         # format
uv run ty check              # type check
scripts/release.sh <version> # bump version, commit, tag
```

## Project Layout

```
initrunner/              # main package (flat layout)
├── agent/               # role schema, loader, executor, tool registry
│   └── tools/           # self-registering tool modules
├── audit/               # append-only SQLite audit trail
├── cli/                 # Typer CLI entry point
├── flow/                # multi-agent orchestration (flow.yaml)
├── ingestion/           # extract → chunk → embed → store pipeline
├── mcp/                 # MCP server integration
├── runner/              # single-shot, REPL, autonomous, daemon modes
├── stores/              # DocumentStore + MemoryStore ABCs and zvec impls
├── triggers/            # cron, file watcher, webhook triggers
├── services/            # shared sync business logic (CLI uses this)
│   └── presets.py       # custom-provider preset definitions (OpenRouter etc.)
├── _compat.py           # optional dependency helpers
└── _html.py             # HTML fetch + markdown conversion
tests/                   # pytest test suite
examples/                # example role and flow YAML files
docs/                    # detailed documentation by subsystem
```

## Key Patterns

These rules apply to every task in this codebase:

- **Sync CLI, async flow**: CLI is synchronous -- use PydanticAI's `run_sync`. Flow and team execution use pydantic-graph beta with `anyio.run()` as the sync bridge. The sync facade (`run_flow()`, `start()`/`stop()`, `run_team_dispatch()`) is preserved. Graph steps use `execute_run_async()` for native async agent execution. Tools can provide async variants via `ToolBuildContext.prefer_async`.
- **Self-registering tools**: add a new tool by creating one file in `agent/tools/` using `@register_tool(type_name, ConfigClass)`. Auto-discovered via `pkgutil.iter_modules()`.
- **Lazy imports in CLI**: CLI commands use lazy imports so `--help` stays fast. Don't add top-level imports in `cli/main.py`.
- **`audit.log()` never raises**: audit failures must not crash agent runs.
- **Dataclasses for DTOs, Pydantic for config**: internal data (RunResult, AuditRecord) uses dataclasses. Role definitions and API schemas use Pydantic.
- **`services/` is the shared layer**: all business logic lives here. CLI is a thin wrapper that calls into `services.<submodule>.*`.

## Skills: Methodology-Only vs Tool-Providing

Skills come in two flavors. **Tool-providing** skills (e.g. kube skill brings `shell` with `allowed_commands: [kubectl, helm]`) declare `tools:` in their SKILL.md frontmatter. **Methodology-only** skills provide only prompt content (MUST/MUST NOT, workflows) and omit the `tools:` field -- the role provides all tools. Both are valid. Tool overlap between skill and role is handled silently (role wins, logged at debug level).

## Coding Conventions

- Run `ruff check` and `ruff format` before committing. Run `ty check` for type checking.
- Tests go in `tests/` mirroring the source layout. Use `pytest` fixtures and `unittest.mock`.
- Keep tool result sizes bounded (truncate with `[truncated]` marker). See existing tools for limits.
- Sensitive env vars must be scrubbed from subprocess environments (see `_SENSITIVE_ENV_KEYS` pattern).
- Optional-dependency imports must have `# type: ignore[import-not-found]` to suppress `ty` errors in environments where the extras aren't installed (e.g. `from opentelemetry import trace  # type: ignore[import-not-found]`).

## Versioning

The package uses Calendar Versioning: `YYYY.M.PATCH` (e.g. `2026.3.1`). The version is defined in one place: `initrunner/__init__.py` (`__version__ = "2026.3.1"`). Hatchling reads it at build time via `[tool.hatch.version]` in `pyproject.toml` -- do **not** add a static `version` field to `[project]`.

PATCH resets to 1 on month change (`2026.3.5` -> `2026.4.1`). Pre-releases use PEP 440 suffixes: `2026.4.1rc1`, `2026.4.1.dev1`.

### Releasing

`scripts/release.sh <version>` bumps `__init__.py`, adds a CHANGELOG header, and commits locally. It also creates a local tag, but **do not push directly** -- main is branch-protected. The canonical stable-release flow is:

1. Run `scripts/release.sh <version>` on local main (creates commit + local tag)
2. Create a branch (`release/<version>`), push it, open a PR
3. After CI passes and squash-merge: `git checkout main && git fetch origin && git reset --hard origin/main`
4. Delete the stale local tag, re-tag the merge commit: `git tag v<version> && git push origin v<version>`

The tag push triggers the release pipeline (PyPI publish + GitHub Release).

## Documentation Index

Detailed docs live in `docs/`. Key references:

| Topic | File |
|---|---|
| CLI commands & usage | `docs/getting-started/cli.md` |
| Choosing features (goal-to-config) | `docs/getting-started/choosing-features.md` |
| LangChain agent import | `docs/getting-started/langchain-import.md` |
| Creating new tools | `docs/agents/tool_creation.md` |
| Tool registry internals | `docs/agents/registry.md` |
| Security model | `docs/security/security.md` |
| Credential vault | `docs/security/vault.md` |
| HMAC-signed audit chain | `docs/security/audit-chain.md` |
| Ingestion pipeline | `docs/core/ingestion.md` |
| Memory system | `docs/core/memory.md` |
| Capabilities (PydanticAI) | `docs/core/capabilities.md` |
| Reasoning primitives | `docs/core/reasoning.md` |
| RAG quickstart | `docs/getting-started/rag-quickstart.md` |
| RAG patterns & guide | `docs/core/rag-guide.md` |
| Triggers (cron/file/webhook/heartbeat) | `docs/core/triggers.md` |
| Tool search meta-tool | `docs/core/tool-search.md` |
| OCI distribution & bundles | `docs/core/oci-distribution.md` |
| Discord bot quickstart | `docs/getting-started/discord.md` |
| Telegram bot quickstart | `docs/getting-started/telegram.md` |
| Cost tracking & budgets | `docs/core/cost-tracking.md` |
| Observability (OpenTelemetry) | `docs/core/observability.md` |
| Autonomous execution | `docs/orchestration/autonomy.md` |
| Team mode (multi-persona) | `docs/orchestration/team_mode.md` |
| Orchestration patterns (all 5, side-by-side) | `docs/orchestration/patterns-guide.md` |
| Multi-agent guide (choosing patterns) | `docs/orchestration/multi-agent-guide.md` |
| Flow orchestration | `docs/orchestration/delegation.md`, `docs/orchestration/sinks.md` |
| Dashboard (web UI) | `docs/interfaces/dashboard.md` |
| Dashboard design system | `docs/interfaces/design-system.md` |
| MCP gateway (serve agents) | `docs/interfaces/mcp-gateway.md` |
| A2A server (agent-to-agent) | `docs/interfaces/a2a.md` |
| Testing guide | `docs/operations/testing.md` |
| Runtime sandbox overview | `docs/security/sandbox.md` |
| Bubblewrap sandbox (Linux, no daemon) | `docs/security/bubblewrap.md` |
| Docker sandbox (cross-platform containers) | `docs/security/docker-sandbox.md` |
| Agent policy (initguard) | `docs/security/agent-policy.md` |
| Auth & guardrails | `docs/security/auth.md`, `docs/configuration/guardrails.md` |
| CI/CD & releases | `docs/operations/cicd.md`, `docs/operations/pypi_publish.md` |
| Role generation & wizards | `docs/agents/role_generation.md` |
| Provider configuration | `docs/configuration/providers.md`, `docs/configuration/ollama.md` |
| Model aliases & override | `docs/configuration/model-aliases.md` |
| Multimodal input | `docs/core/multimodal.md` |
| Report export | `docs/core/reports.md` |
| Doctor command | `docs/operations/doctor.md` |
| Deprecations & schema versioning | `docs/operations/deprecations.md` |
| Shareable templates | `docs/getting-started/shareable-templates.md`, `docs/getting-started/template-tutorial.md` |
