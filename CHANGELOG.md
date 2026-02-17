# Changelog

All notable changes to this project will be documented in this file.

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