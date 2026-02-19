# Changelog

## [Unreleased]

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