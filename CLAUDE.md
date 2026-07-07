# InitRunner

YAML-first AI agent platform: define agents as declarative `role.yaml` files (model, tools, triggers, ingestion, guardrails) and run them as one-shot commands, interactive REPLs, trigger-driven daemons, or OpenAI-compatible API servers. Multi-agent orchestration via `flow.yaml`.

Python 3.11+ with PydanticAI (agent framework), Pydantic (config/validation), Typer + Rich (CLI), SQLite (audit), LanceDB (vector stores), hatchling (build), uv (package manager). Web dashboard frontend is SvelteKit, managed with pnpm.

## Project map

```
initrunner/              # main package (flat layout)
├── a2a/                 # A2A (agent-to-agent) protocol server
├── agent/               # role schema/, loader, executor, capabilities/, runtime_sandbox/
│   └── tools/           # self-registering tool modules
├── audit/               # append-only SQLite audit trail
├── cli/                 # Typer CLI entry point
├── credentials/         # credential resolution + encrypted vault
├── dashboard/           # FastAPI backend for the web UI
├── eval/                # eval framework: test roles against prompt suites
├── flow/                # multi-agent orchestration (flow.yaml)
├── ingestion/           # document pipeline: extract, chunk, embed, store
├── mcp/                 # MCP server integration
├── packaging/           # OCI bundles: build, push, pull
├── registry/            # community role registry (install, search, manage)
├── runner/              # single-shot, REPL, autonomous, daemon modes
├── server/              # OpenAI-compatible HTTP API server
├── services/            # shared sync business logic (CLI is a thin wrapper over this)
│   └── presets.py       # custom-provider preset definitions (OpenRouter etc.)
├── sinks/               # flow output sinks (file, webhook, custom)
├── stores/              # DocumentStore + MemoryStore ABCs and LanceDB impls
├── team/                # team mode: one-shot multi-persona collaboration
├── telemetry/           # opt-in anonymous usage telemetry (PostHog)
├── triggers/            # cron, file watcher, webhook triggers
├── _compat.py           # optional dependency helpers
└── _html.py             # HTML fetch + markdown conversion
dashboard/               # SvelteKit web UI frontend (pnpm workspace)
tests/                   # pytest suite, mirrors source layout
examples/                # example role and flow YAML files
docs/                    # detailed documentation by subsystem (index below)
scripts/                 # release.sh, build-dashboard.sh, dev scripts
deploy/                  # Docker entrypoint, fly.toml
```

<important if="you need to run commands to install, test, lint, type-check, build, or release">

| Command | What it does |
|---|---|
| `uv sync` | install deps |
| `uv run pytest tests/ -v` | run tests |
| `uv run ruff check .` | lint |
| `uv run ruff format .` | format |
| `uv run ty check` | type check |
| `scripts/release.sh <version>` | bump version, add CHANGELOG header, local commit + tag |
| `scripts/build-dashboard.sh` | build the SvelteKit dashboard into the package |

The dashboard frontend (`dashboard/`) uses pnpm, never npm.
</important>

<important if="you are working on flow, team, or agent execution paths">

Sync CLI, async flow: the CLI is synchronous and uses PydanticAI's `run_sync`. Flow and team execution use pydantic-graph with `anyio.run()` as the sync bridge; the sync facade (`run_flow()`, `start()`/`stop()`, `run_team_dispatch()`) is preserved. Graph steps use `execute_run_async()` (in `initrunner/agent/executor.py`, wrapped by `initrunner/services/execution.py`) for native async agent execution.
</important>

<important if="you are creating or modifying agent tools">

- Add a new tool by creating one file in `initrunner/agent/tools/` using `@register_tool(type_name, ConfigClass)` (see `initrunner/agent/tools/_registry.py`). Tools are auto-discovered via `pkgutil.iter_modules()`.
- Keep tool result sizes bounded (truncate with a `[truncated]` marker). See existing tools for limits.
- Sensitive env vars must be scrubbed from subprocess environments: `DEFAULT_SENSITIVE_ENV_PREFIXES` / `DEFAULT_SENSITIVE_ENV_SUFFIXES` in `initrunner/agent/_subprocess.py`.
</important>

<important if="you are modifying the CLI (initrunner/cli/)">
CLI commands use lazy imports so `--help` stays fast. Don't add top-level imports in `cli/main.py`.
</important>

<important if="you are adding business logic or new CLI commands">
All business logic lives in `initrunner/services/`. The CLI is a thin wrapper that calls into `services.<submodule>.*`.
</important>

<important if="you are touching audit logging">
`audit.log()` never raises -- audit failures must not crash agent runs (see `initrunner/audit/logger.py`).
</important>

<important if="you are defining new config schemas or internal data structures">
Dataclasses for DTOs, Pydantic for config: internal data (RunResult, AuditRecord) uses dataclasses. Role definitions and API schemas use Pydantic.
</important>

<important if="you are importing an optional dependency">
Optional-dependency imports need `# type: ignore[import-not-found]` to suppress `ty` errors in environments where the extras aren't installed (e.g. `from opentelemetry import trace  # type: ignore[import-not-found]`).
</important>

<important if="you are working on skills (SKILL.md)">

Skills come in two flavors. **Tool-providing** skills (e.g. kube skill brings `shell` with `allowed_commands: [kubectl, helm]`) declare `tools:` in their SKILL.md frontmatter. **Methodology-only** skills provide only prompt content (MUST/MUST NOT, workflows) and omit the `tools:` field -- the role provides all tools. Both are valid. Tool overlap between skill and role is handled silently (role wins, logged at debug level).
</important>

<important if="you are writing or modifying tests">

- Tests go in `tests/` mirroring the source layout. Use `pytest` fixtures and `unittest.mock`.
- `setup_logging()` (`initrunner/_log.py`) sets `propagate=False` on the `initrunner` logger, so `caplog` sees nothing from it by default. Tests that assert on log records must re-enable propagation: `monkeypatch.setattr(logging.getLogger("initrunner"), "propagate", True)`.
</important>

<important if="you are bumping the version or preparing a release">

Calendar Versioning: `YYYY.M.PATCH`. The version is defined in one place, `initrunner/__init__.py` (`__version__`). Hatchling reads it at build time via `[tool.hatch.version]` in `pyproject.toml` -- do **not** add a static `version` field to `[project]`. PATCH resets to 1 on month change (`2026.3.5` becomes `2026.4.1`). Pre-releases use PEP 440 suffixes: `rc1`, `.dev1`.

`scripts/release.sh <version>` bumps `__init__.py`, adds a CHANGELOG header, and commits locally. It also creates a local tag, but **do not push directly** -- main is branch-protected. The canonical stable-release flow:

1. Run `scripts/release.sh <version>` on local main (creates commit + local tag)
2. Create a branch (`release/<version>`), push it, open a PR
3. After CI passes and squash-merge: `git checkout main && git fetch origin && git reset --hard origin/main`
4. Delete the stale local tag, re-tag the merge commit: `git tag v<version> && git push origin v<version>`

The tag push triggers the release pipeline (PyPI publish + GitHub Release).
</important>

<important if="you need detailed docs for a subsystem, or you are adding or changing a feature (update its docs and add an index row here)">

| Topic | File |
|---|---|
| Installation | `docs/getting-started/installation.md` |
| Installer script internals (`curl \| sh`) | `docs/getting-started/installer.md` |
| Setup wizard (`initrunner setup`) | `docs/getting-started/setup.md` |
| Tutorial (build a site monitor agent) | `docs/getting-started/tutorial.md` |
| Docker image | `docs/getting-started/docker.md` |
| CLI commands & usage | `docs/getting-started/cli.md` |
| Choosing features (goal-to-config) | `docs/getting-started/choosing-features.md` |
| LangChain agent import | `docs/getting-started/langchain-import.md` |
| PydanticAI Python agent import | `docs/getting-started/pydanticai-import.md` |
| PydanticAI Agent Spec import/export | `docs/getting-started/agent-spec-import.md` |
| Tool configuration reference (all built-in types) | `docs/agents/tools.md` |
| Tool examples cookbook | `docs/agents/example_tools.md` |
| Creating, scaffolding (`tool new`) & hot-attaching (`--dev`) tools | `docs/agents/tool_creation.md` |
| Tool registry internals | `docs/agents/registry.md` |
| Skills (SKILL.md bundles) | `docs/agents/skills_feature.md` |
| Security model | `docs/security/security.md` |
| Human-in-the-loop approval | `docs/security/approvals.md` |
| Credential vault | `docs/security/vault.md` |
| HMAC-signed audit chain | `docs/security/audit-chain.md` |
| Tool permissions (arg-pattern allow/deny) | `docs/security/tool_permission_system.md` |
| Ingestion pipeline | `docs/core/ingestion.md` |
| Memory system | `docs/core/memory.md` |
| Audit trail | `docs/core/audit.md` |
| Intent sensing (auto role selection) | `docs/core/intent_sensing.md` |
| Capabilities (PydanticAI) | `docs/core/capabilities.md` |
| Reasoning primitives | `docs/core/reasoning.md` |
| Structured output modes | `docs/core/structured-output.md` |
| Agent evals & test suites | `docs/core/evals.md` |
| RAG quickstart | `docs/getting-started/rag-quickstart.md` |
| RAG patterns & guide | `docs/core/rag-guide.md` |
| Triggers (cron/file/webhook/heartbeat) | `docs/core/triggers.md` |
| Tool search meta-tool | `docs/core/tool-search.md` |
| OCI distribution & bundles | `docs/core/oci-distribution.md` |
| Discord bot quickstart | `docs/getting-started/discord.md` |
| Telegram bot quickstart | `docs/getting-started/telegram.md` |
| Cost tracking & budgets | `docs/core/cost-tracking.md` |
| Token usage control (guardrail budgets) | `docs/configuration/token_control.md` |
| Observability (OpenTelemetry) | `docs/core/observability.md` |
| Autonomous execution | `docs/orchestration/autonomy.md` |
| Team mode (multi-persona) | `docs/orchestration/team_mode.md` |
| Orchestration patterns (all 5, side-by-side) | `docs/orchestration/patterns-guide.md` |
| Multi-agent guide (choosing patterns) | `docs/orchestration/multi-agent-guide.md` |
| Flow orchestration (comprehensive guide) | `docs/orchestration/flow.md` |
| Flow orchestration (delegation & sinks) | `docs/orchestration/delegation.md`, `docs/orchestration/sinks.md` |
| Blackboard (shared in-run state) | `docs/orchestration/blackboard.md` |
| Durable, resumable flows | `docs/orchestration/durability.md` |
| Dashboard (web UI) | `docs/interfaces/dashboard.md` |
| Dashboard design system | `docs/interfaces/design-system.md` |
| OpenAI-compatible API server (`--serve`) | `docs/interfaces/server.md` |
| MCP gateway (serve agents) | `docs/interfaces/mcp-gateway.md` |
| A2A server (agent-to-agent) | `docs/interfaces/a2a.md` |
| Testing guide | `docs/operations/testing.md` |
| Smoke tests (example role validation) | `docs/operations/smoke_tests.md` |
| Runtime sandbox overview | `docs/security/sandbox.md` |
| Sandbox backend comparison (microVM, gVisor, etc.) | `docs/security/sandbox-comparison.md` |
| Bubblewrap sandbox (Linux, no daemon) | `docs/security/bubblewrap.md` |
| Docker sandbox (cross-platform containers, hardened runtimes) | `docs/security/docker-sandbox.md` |
| SSH backend (remote execution) | `docs/security/ssh-sandbox.md` |
| Agent policy (initguard) | `docs/security/agent-policy.md` |
| Guardrails | `docs/configuration/guardrails.md` |
| CI/CD & releases | `docs/operations/cicd.md`, `docs/operations/pypi_publish.md` |
| Role generation & wizards | `docs/agents/role_generation.md` |
| Provider configuration | `docs/configuration/providers.md`, `docs/configuration/ollama.md` |
| Model aliases & override | `docs/configuration/model-aliases.md` |
| Multimodal input | `docs/core/multimodal.md` |
| Report export | `docs/core/reports.md` |
| Doctor command | `docs/operations/doctor.md` |
| Agent dry-run (`plan`) | `docs/operations/plan.md` |
| Usage telemetry (PostHog, opt-out) | `docs/operations/telemetry.md` |
| Deprecations & schema versioning | `docs/operations/deprecations.md` |
| Shareable templates | `docs/getting-started/shareable-templates.md`, `docs/getting-started/template-tutorial.md` |
</important>
