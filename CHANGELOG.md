# Changelog

## [1.7.0] - 2026-02-26

### Added
- Tool permission system: declarative allow/deny rules for tool calls with fnmatch glob patterns, deny-wins evaluation, and sanitized denial messages
- `ToolPermissions` schema with `default`, `allow`, `deny` fields on any tool config
- `PermissionToolset` wrapper auto-applied by tool registry when permissions are configured
- Quick Chat in web dashboard: zero-config `/chat` page with provider auto-detection, SSE streaming, and file upload (20 MB limit)
- Quick Chat in TUI: press `c` from any screen for ephemeral chat with auto-detected provider
- Sense (auto-role selection) in TUI (`s` key) and web dashboard (`/chat/sense`) for matching prompts to roles
- `build_agent_from_role_sync()` for building agents from in-memory RoleDefinition without a file path
- `build_quick_chat_role_sync()` one-shot builder for ephemeral roles with provider detection and tool filtering
- Sense redirect in role chat page: auto-fills and submits prompt when redirected with `?prompt=` query param
- `sandboxed-dev-assistant.yaml` example role demonstrating tool permissions
- `docs/security/tool_permission_system.md` documentation

### Fixed
- Sense LLM tiebreaker now evaluates top 15 candidates instead of top 5 for better role matching accuracy

### Changed
- Default web dashboard landing page changed from `/roles` to `/chat`
- `ChatSession.role_path` now optional to support ephemeral sessions
- Chat command refactored to delegate to shared `build_quick_chat_role_sync()` service
- Shared tool constants (`EPHEMERAL_TOOL_DEFAULTS`, `TOOL_REQUIRED_ENVS`, `TOOL_PROFILES`) moved to `services.providers`

### Documentation
- New Quick Chat sections in web dashboard and TUI docs
- New Sense (auto-role selection) sections in dashboard and TUI docs
- Updated chat getting-started guide with Quick Chat links

## [1.6.0] - 2026-02-26

### Added
- **Team mode** (`kind: Team`) — single-file, one-shot multi-agent collaboration. Define personas as `name: "description"` pairs; they run sequentially with output handoff, prompt injection framing, and cumulative budget controls
- `--task` CLI option as alias for `--prompt` (`-p`) on the `run` command
- `detect_yaml_kind()` helper for dispatching Team/Compose/Agent files before full validation
- Team guardrails: per-persona `max_tokens_per_run`/`max_tool_calls`/`timeout_seconds`, cumulative `team_token_budget` and `team_timeout_seconds`
- Team validation via `initrunner validate team.yaml`
- Team audit logging with `trigger_type="team"` and metadata for team_name, team_run_id, agent_name
- `examples/teams/code-review.yaml` example
- `docs/orchestration/team_mode.md` documentation

### Security
- Escape single quotes in all zvec filter expressions to prevent filter injection
- Block absolute paths in roles API directory scanning to prevent filesystem traversal
- Sanitize generic exception messages in ingestion SSE stream to avoid leaking internal details

### Fixed
- Memory deserialization now tolerates corrupt `metadata_json` and unknown `memory_type` values instead of crashing
- `_release_collection` logs flush failures instead of silently swallowing them

## [1.5.0] - 2026-02-22

## [1.4.1] - 2026-02-22

### Changed
- Docker image now ships with all extras pre-installed (`EXTRAS="all"`)

### Documentation
- Expanded Docker section in README with examples for chat, tools, RAG ingestion, Telegram bot, and API server

## [1.4.0] - 2026-02-22

### Added
- Persistent memory for `initrunner chat` — enabled by default, remembers facts across sessions. Use `--no-memory` to disable
- `--ingest PATH` flag (repeatable) for zero-config document Q&A — runs ingestion pipeline before REPL, auto-handles embedding model changes
- `--resume` flag to load previous session history with auto-recall of relevant memories
- Tool search auto-enabled in ephemeral chat — tools behind on-demand discovery to reduce context overhead
- `resolve_func_names()` in tool registry for extracting function names for tool search `always_available` list
- `auto_recall_for_resume()` in `memory_ops` — embeds recent messages, searches memory store, returns formatted recalled context
- Chat configuration file (`~/.initrunner/chat.yaml`) for persistent chat defaults (provider, model, tool_profile, ingest paths, personality, name)
- `allowed_user_ids` for Telegram trigger — user-ID-based access control with union semantics (match either username or user ID); user ID included in trigger event metadata
- `allowed_user_ids` for Discord trigger — user-ID-based access control that works in both guild channels and DMs; extracted `_check_discord_access()` helper for testability
- `--allowed-users` and `--allowed-user-ids` CLI flags for `chat --telegram` and `chat --discord`
- Security headers middleware: X-Frame-Options, X-Content-Type-Options, Content-Security-Policy on all API responses
- Open redirect prevention in auth UI — rejects absolute URLs, protocol-relative URLs, javascript: schemes
- Regex complexity validation with 1s timeout to detect catastrophic backtracking in guardrail patterns

### Changed
- `_INITRUNNER_DIR` changed from module-level constant to `_get_initrunner_dir()` function for testability
- Tool profile envvar checking now runs for all profiles to maximize tool search discoverability
- Tool search system prompt more assertive: "ALWAYS call `search_tools`" when no visible tool fits
- `ephemeral_context()` now registers/unregisters memory stores for proper multiplexing
- Auth cookies support configurable `secure` flag for HTTPS deployments
- Discord access control refactored into standalone `_check_discord_access()` function
- Telegram and Discord trigger `summary()` methods now include user IDs and roles

### Fixed
- Memory tools no longer crash with collection lock conflicts when called during ephemeral chat runs
- Removed stale `# type: ignore` comments from extractors and telegram trigger

### Documentation
- README: new "Try It" section, "Define Agent Roles in YAML" heading, "Zero config to start" bullet
- Expanded chat, memory, ingestion, tool-search, RAG quickstart, Telegram, and Discord docs for zero-config features
- Telegram and Discord docs updated with `allowed_user_ids` configuration, union semantics, and security recommendations
- New "Chat Configuration File" section in chat docs

## [1.3.0] - 2026-02-22

### Breaking Changes
- **Vector store backend migrated from sqlite-vec to Zvec** — existing `.db` store files are not compatible; users must re-ingest documents (`initrunner ingest --force`) and memory stores will start fresh. Store paths change from `<name>.db` to `<name>.zvec`.

### Added
- Zvec-backed `ZvecDocumentStore` and `ZvecMemoryStore` implementations (`stores/zvec_store.py`)
- Reference-counted memory store registry (`register_memory_store` / `unregister_memory_store`) preventing collection lock conflicts when tools and system prompts share a store
- `[all]` extras group — meta-dependency that bundles all provider and feature extras
- `read_store_meta()` / `write_store_meta()` abstract methods on `DocumentStore` ABC
- `EmbeddingModelChangedError` exported from `initrunner.stores` (moved from deleted sqlite_vec module)

### Changed
- Python version constraint tightened to `>=3.11,<3.13` — zvec does not yet ship Python 3.13 wheels
- Zvec-dependent tests skipped in CI (`SKIP_ZVEC_TESTS=1`) — zvec native extension triggers illegal instruction on GitHub Actions runners
- Default `StoreBackend` enum value: `SQLITE_VEC` → `ZVEC` across all config schemas (IngestConfig, MemoryConfig, SharedMemoryConfig, StoreConfig)
- Ingestion pipeline uses factory-based store creation instead of low-level sqlite3 calls
- `build_memory_system_prompt()` accepts optional `store` parameter to reuse an already-open store
- Agent loader passes existing memory store to procedural-memory system prompt callback
- Memory store `close()` is now reference-counted — only releases underlying zvec collections when the last reference is closed

### Fixed
- `chat --tool-profile all` no longer fails when optional tool env vars (e.g. `SLACK_WEBHOOK_URL`) are missing — tools are skipped with a warning
- Memory tools (`remember`, `recall`, `list_memories`, `learn_procedure`, `record_episode`) no longer crash with "Can't lock read-write collection" when called during an agent run

### Dependencies
- Removed: `sqlite-vec>=0.1.6`
- Added: `zvec>=0.2.0`
- New extras group: `[all]` (bundles ingest, search, audio, safety, all-models, observability, channels, tui, dashboard)

### Documentation
- Rewritten ingestion docs — Zvec collection schemas replace SQL table descriptions
- Rewritten memory docs — Zvec store format, locking model, directory layout
- Expanded installation docs — restructured extras into categorised tables (Providers, Features, Messaging, Interfaces), added `[all]` install examples
- Updated provider, orchestration, and delegation docs for zvec references
- Updated README extras section
- Updated CLAUDE.md tech stack

## [1.2.0] - 2026-02-21

### Added
- Telegram long-polling bot trigger with username-based access control and message chunking (4096 chars)
- Discord WebSocket bot trigger with role/channel-based access control and message chunking (2000 chars)
- Multi-turn conversation persistence for messaging triggers (LRU store, TTL expiry)
- `chat` command — zero-config REPL with provider auto-detection, tool profiles (`none`/`minimal`/`all`), and one-command bot mode (`--telegram`/`--discord`)
- `tool_search` meta-tool — BM25 keyword search over tool catalog; hides tools behind on-demand discovery to reduce context for large (10+) tool sets
- Provider auto-detection service (`services/providers.py`) — priority-ordered key detection (Anthropic → OpenAI → Google → Groq → Mistral → Cohere → Ollama)
- Bot token redaction for Discord and Telegram in sensitive env scrubbing
- Example roles: `discord-assistant.yaml`, `telegram-assistant.yaml`
- Docs: Discord quickstart, Telegram quickstart, chat quickstart, tool search reference

### Changed
- Daemon runner: messaging triggers reply immediately before post-processing (display, sinks, episode capture)
- Messaging triggers skip autonomous mode even when `autonomous: true` is set — use direct execution for low-latency replies
- Daemon concurrency limited to 4 simultaneous trigger executions with backpressure

### Dependencies
- New optional extras: `telegram` (`python-telegram-bot>=21.0`), `discord` (`discord.py>=2.3`), `channels` (both)

## [1.1.6] - 2026-02-19

### Fixed
- **fix:** migrate search tool from deprecated `duckduckgo-search` to `ddgs` — import, context
  manager removal, and error messages updated
- **fix:** `web-searcher` example role prompt tightened to avoid exhausting tool call limit;
  `max_tool_calls` bumped 10→15, `timeout_seconds` bumped 60→120

### Changed
- **deps:** `search` extra now requires `ddgs>=9.10.0` (replaces `duckduckgo-search>=7.0.0`)

## [1.1.5] - 2026-02-19

### Added
- **feat:** `--sense` flag for intent sensing — picks the best matching role using keyword
  scoring + optional LLM tiebreaker. New flags: `--sense`, `--role-dir PATH`, `--confirm-role`.
- **feat:** `csv_analysis` tool — inspect, summarize, and query CSV files within a sandboxed
  directory. Three tools: `inspect_csv` (schema + preview), `summarize_csv` (column stats),
  `query_csv` (filter + column projection). Config: `root_path`, `max_rows`, `max_file_size_mb`,
  `delimiter`.
- **docs:** `docs/core/intent_sensing.md` — full reference for Intent Sensing: algorithm
  internals, role discovery paths, scoring weights, selection methods, tagging guide, examples,
  troubleshooting.
- **example:** `examples/roles/csv-analyst/` — ready-to-run CSV analyst role with sample data.

## [1.1.4] - 2026-02-18

### Changed
- **ux:** `setup` "Next steps" panel restructured into three sections (Create your agent / Or run the scaffold / Interfaces); examples discovery (`examples list` → `examples copy` → `run`) replaces the broken `init --template rag` hint

## [1.1.3] - 2026-02-18

### Fixed
- **fix:** `install_extra` now correctly reinstalls into uv tool environments
  (`uv tool install --force`) and pipx environments (`pipx install --force`)
  instead of failing with `uv pip install` which has no target environment
- **fix:** Rich markup escaping in `install_extra` failure warning —
  `[tui]`/`[dashboard]` brackets now appear literally instead of being silently dropped

## [1.1.2] - 2026-02-18

### Added
- **feat:** `api_key_env` now works for standard embedding providers (openai, anthropic, google), not just custom endpoints
- **feat:** `doctor` command shows Embedding Providers table with key status and Anthropic note
- **feat:** Wizard warns when Anthropic is selected with RAG/memory about needing `OPENAI_API_KEY`

### Fixed
- **fix:** Missing embedding API keys now fail fast with actionable error messages naming the required env var
- **fix:** `is_reasoning_model()` now correctly detects gpt-5 as a reasoning model (excluding gpt-5.1+, gpt-5-chat)
- **fix:** Wrap sqlite_vec migration queries with `_retry_on_locked` for robustness

### Changed
- **chore:** Bump hello-world example `max_tokens` from 256 to 1024

### Documentation
- **docs:** Updated embedding key documentation in ingestion, memory, providers, ollama, doctor, and role generation docs

## [1.1.1] - 2026-02-18

### Changed
- **Services package split**: Reorganize `initrunner/services.py` into a `services/` package with domain submodules (`discovery`, `execution`, `memory`, `roles`, `api_models`, `operations`). All public imports remain available from `initrunner.services`. Internal refactor only — no public API changes.

## [1.1.0] - 2026-02-18

### Added
- Shareable role templates with `init export-template` / `init import-template`
- `--export-report` and `--report-template` flags for structured run output
- `doctor --quickstart` command for guided first-run setup

### Fixed
- Suppress temperature warning for OpenAI reasoning models (o1, o3, etc.)
- Resolve `ty` type-check errors across codebase
- Wrap store migration queries with `_retry_on_locked` for CI stability
- Wrap long test method signature to satisfy ruff line-length

### Documentation
- Shareable templates tutorial and example roles
- Updated README version to 1.1.0

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-02-18

### Breaking Changes
- **Schema package split**: `initrunner.agent.schema` is now a package (`schema/`) with domain sub-modules (`role`, `tools`, `triggers`, `memory`, `guardrails`, `security`, `ingestion`, `sinks`, `autonomy`, `observability`, `output`, `base`). Direct imports from `initrunner.agent.schema` must be updated to the specific sub-module (e.g. `from initrunner.agent.schema.role import RoleDefinition`).

### Added
- **Audio tool**: YouTube transcript fetching via `get_youtube_transcript` and local audio/video file transcription via `transcribe_audio` with multimodal model support
- `AudioToolConfig` with configurable languages, timestamps, transcription model override, file size limits, and output truncation
- `audio-assistant` bundled example role demonstrating YouTube and local audio workflows
- Audio tool documentation in `docs/agents/tools.md`
- RAG quickstart guide (`docs/getting-started/rag-quickstart.md`)
- Embedding provider guidance in `docs/configuration/providers.md`
- Setup wizard RAG improvements with better ingestion flow

### Fixed
- Update `youtube-transcript-api` v1.2.4 compatibility (instance-based API, attribute access on transcript snippets)
- Fix real bugs from code audit: profanity filter missing-dependency guard, compose trigger typing, file watcher error handling, audit logger thread safety, API route error responses
- Fix `TriggerConfig` import path after schema split in compose module
- Resolve `ty` type checker errors in observability module

### Changed
- Default OpenAI model changed from `gpt-4o-mini` to `gpt-5-mini` across all templates, examples, docs, and CLI defaults
- DRY improvements: deduplicate API route patterns, simplify interactive/TUI run logic

### Documentation
- Complete audio tool reference with options, install instructions, security, and examples
- Improved RAG setup documentation with quickstart and embedding guidance
- Updated all code examples and references to use `gpt-5-mini`

## [0.5.0] - 2026-02-17

### Added
- rich memory architecture: episodic, semantic, and procedural memory types
- memory consolidation: automatic extraction of semantic facts from episodic records via LLM
- episodic auto-capture in autonomous and daemon modes with structured metadata
- procedural memory injection into agent system prompts
- `learn_procedure()` and `record_episode()` memory tools (conditional on type config)
- `memory_types` filter parameter on `recall()` tool
- `memory_type` filter parameter on `list_memories()` tool
- `memory list` CLI command with `--type`, `--category`, `--limit` filters
- `memory consolidate` CLI command for manual consolidation
- `--type` option on `memory clear` CLI command for type-scoped clearing
- `rich-memory-assistant` example role demonstrating all memory types
- auto-migration for existing memory databases (adds `memory_type`, `metadata_json`, `consolidated_at` columns)
- structured output (`spec.output`) with JSON Schema validation for role definitions
- `invoice-classifier` example role demonstrating structured output
- structured output documentation (`docs/core/structured-output.md`)
- OpenTelemetry observability with OTLP, console, and Logfire backends
- `traced-agent` example role with console observability
- observability documentation (`docs/core/observability.md`)
- add multimodal input section and bump version to v0.4.0 in README (e1aa97f)
- add model selection to role creation and setup (v0.3.0) (d69be97)
- add GitHub Release creation to release workflow and update changelog (1422f79)
- add Docker support and CI workflow for image publishing (e808b5d)

### Fixed
- add retry-on-locked wrapper to sqlite-vec write paths (0573a74)
- update version assertion in test_cli.py and fix ruff formatting (3859649)
- bust GitHub Camo cache for PyPI version badge (04a25a6)
- use correct Docker Hub namespace and fix latest tag in publish workflow (3cbf5d4)
- clear pip index env vars during wheel install to avoid TestPyPI dependency pollution (d7fc20b)
- download wheel from TestPyPI with --no-deps to avoid name-squatted packages (8f460da)

### Documentation
- complete rewrite of `docs/core/memory.md` for rich memory architecture
- update memory tools section in `docs/agents/tools.md` (3 → 5 tools)
- update autonomy docs with episodic auto-capture and consolidation
- add `memory list` and `memory consolidate` to CLI reference
- surface autonomous mode and budget controls in README and CLI docs (2af688a)
- add Open WebUI integration guide to server docs and README (6cf6109)
- add documentation changes to CHANGELOG.md for v0.3.0 (b890321)
- improve RAG documentation, fix search_documents signature, add examples (1223c0b)
- reduce repetition in README.md (03ade5e)
- mention Docker Hub as alternative registry (615e48f)
- remove release_preparation.md, superseded by pypi_publish.md (53edbc5)

### Changed
- fix ruff formatting in _registry.py and test_htmx_pages.py (6d9c980)

### Maintenance
- release 0.2.0 (2bb690f)
- bump version to 0.2.0rc2 for TestPyPI re-publish (c4c6118)
- bump version to 0.2.0rc1 and add TestPyPI workflow (24167ac)
- initial release (499b56e)