# Changelog

## [1.33.1] - 2026-03-19

### Fixed
- Version bump for PyPI re-release (v1.33.0 tag pointed to post-release README commit; PyPI rejects duplicate versions)

## [1.33.0] - 2026-03-19

### Added
- **Team mode v2** -- parallel execution strategy (`strategy: parallel`), per-persona model/tools/environment overrides, shared memory across personas, shared documents (RAG) with pre-run ingestion, and OpenTelemetry observability support
- **Installed role name resolution** -- `initrunner run code-reviewer` resolves installed roles by display name, `owner/name`, or qualified key (`hub:owner/name`). All commands accepting a role path gain this: `run`, `validate`, `test`, `ingest`, `daemon`, `serve`, `chat`
- **Install "Run:" hint** -- `initrunner install` and `initrunner pull` now print `Run: initrunner run <name> -p "your prompt"` after successful install
- **Streaming single-shot output** -- `initrunner run` streams tokens live on interactive terminals. Use `--no-stream` to disable
- **Stale-docs-bloodhound example** (`examples/roles/stale-docs-bloodhound/`) -- daemon agent that monitors a repo for stale documentation using git blame analysis and reference cross-checking
- New `InstallResult` dataclass in `registry.py` returns both `path` and `display_name` from install operations
- New `resolve_installed_path()` function with ambiguity detection (raises clear error when display name matches multiple sources)

### Changed
- `initrunner list` now shows a "Run" column with the execution command instead of "Installed At" timestamp
- `confirm_install()`, `install_role()` return `InstallResult` instead of bare `Path`
- Help text for all role-accepting commands updated to mention installed role names
- Kube-advisor team example updated with per-persona tool overrides

## [1.32.0] - 2026-03-19

### Added
- **Kube-advisor example agent** (`examples/roles/kube-advisor/`) -- Kubernetes troubleshooting agent with team mode, reusable kubernetes skill, diagnostic scripts, and curated reference guides
- **InitRunner support example** (`examples/roles/initrunner-support/`) -- support agent with RAG over InitRunner documentation and long-term memory

### Fixed
- **InitHub publish README not displaying** -- `hub_publish()` sent readme, repository_url, and categories as multipart form fields; the InitHub API expects them as query parameters. READMEs now appear on package detail pages

### Changed
- Compact, user-friendly READMEs for helpdesk, initrunner-support, and kube-advisor examples
- Updated metadata descriptions for helpdesk and initrunner-support to be action-oriented

## [1.31.0] - 2026-03-18

### Added
- **Helpdesk example agent** (`examples/roles/helpdesk/`) -- generic knowledge base helpdesk with multi-format ingestion, memory, security hardening, and API server support

### Fixed
- **Bundle extraction path resolution** -- installed roles now resolve relative paths correctly (`data/` prefix stripped during extraction so `./knowledge-base/` matches the original layout)
- **LanceDB deprecation warning** -- include `_distance` in vector search projection to suppress `lance::dataset::scanner` warning

## [1.30.0] - 2026-03-18

### Breaking Changes
- **Removed community roles (GitHub index)**: bare-name installation (`initrunner install code-reviewer`) now shows an error with a search hint instead of looking up the community index
- **Removed GitHub source syntax**: `user/repo[:path][@ref]` format that downloaded from `raw.githubusercontent.com` is no longer supported. Use `owner/name[@ver]` to install from InitHub instead
- `initrunner hub` subcommands are deprecated (still functional with warnings). Use top-level equivalents: `initrunner login`, `initrunner logout`, `initrunner whoami`, `initrunner publish`, `initrunner search`

### Added
- **`owner/name[@ver]` installs from InitHub** by default (no `hub:` prefix required)
- **`initrunner login`** top-level command with smart dispatch: no args = InitHub (device code flow), hostname arg = OCI registry
- **`initrunner logout`** and **`initrunner whoami`** promoted to top-level commands
- **`initrunner publish`** smart dispatch: no OCI ref = InitHub, with OCI ref = OCI registry. Adds `--readme`, `--repo-url`, `--category` options for InitHub
- **`initrunner search`** now shows version, downloads, and tags columns. Added `--tag` filter option
- `parse_hub_source()` in `hub.py` accepts both `owner/name[@ver]` and `hub:owner/name[@ver]`
- Early version validation in `preview_install()`: fails before download if requested `@version` does not exist
- Hub list display shows owner/name and version for installed hub packages
- Legacy GitHub manifest entries handled gracefully on `update` (returns "no longer supported" message)

### Removed
- `resolve_source()`, `_resolve_from_index()`, `search_index()`, `hub_search_index()` from `registry.py`
- `_validate_yaml_content()`, `check_dependencies()`, `_role_info_from_definition()` from `registry.py`
- `download_yaml()`, `fetch_commit_sha()`, `_build_request()`, `_fetch_index()` from `registry.py`
- `ResolvedSource`, `IndexEntry`, `RoleInfo` dataclasses from `registry.py`
- `INDEX_URL`, `_ALLOWED_HOST`, `_SOURCE_RE` constants from `registry.py`
- GitHub install, preview, and update code paths

## [1.29.0] - 2026-03-18

### Added
- **`hub login` device code flow** -- `initrunner hub login` opens the browser for one-time device code authorization; `--token` flag for CI/headless environments. Replaces manual token paste.
- **CLI path resolution** -- all commands that accept a role file now also accept a directory. Resolves `<dir>/role.yaml` or scans for a single `apiVersion: initrunner/v1` YAML file. Enables `initrunner run .` and `initrunner hub publish` from an agent directory.
- **`hub publish` from directory** -- defaults to current directory; accepts directory or file path
- `resolve_role_path()` and `resolve_role_paths()` helpers in `cli/_helpers.py`
- 27 new tests for path resolution, device code flow, and hub CLI commands

### Changed
- All CLI help text updated from "Path to role.yaml" to "Agent directory or role YAML file"
- `hub publish` argument changed from required file to optional path (default `.`)
- CLI reference docs updated: `<role.yaml>` -> `<PATH>`, new hub command and path resolution sections
- Registry docs enhanced with authentication section (device code flow, `--token`)

## [1.28.0] - 2026-03-17

### Added
- **`initrunner new` conversational builder** -- single command replaces `init`, `create`, and wizard. Supports 6 seed modes (blank, template, description, local file, example, hub), multi-turn LLM refinement with syntax-highlighted YAML preview, auto-repair on validation failure, and contextual next-step hints
- **InitHub marketplace** -- `initrunner hub` sub-commands (login, logout, whoami, search, info, download, publish), `hub.py` API client with token management, hub-aware `install`/`info` in registry
- **`initrunner skill new`** sub-command for skill scaffolding
- `BuilderSession` service layer (`services/agent_builder.py`) -- UI-agnostic multi-turn builder
- `build_tool_summary()` in `role_generator.py` -- tool reference from live registry
- 68 new builder tests, 657+ new hub/registry tests

### Changed
- `generate_role()` is now a thin wrapper over `BuilderSession`
- Zero-arg TTY: unconfigured shows setup hint panel; configured shows "Tip: use 'initrunner new'" before chat
- `registry.py` enhanced with hub and OCI source resolution
- `registry_cmd.py` enhanced with hub-aware install/info

### Removed
- `initrunner init` command
- `initrunner create` command
- `initrunner/cli/wizard.py`

### Fixed
- `hub.py`: `urllib.request.quote` -> `urllib.parse.quote`
- `registry_cmd.py`: type narrowing for dict result
- `test_hub.py`: `HTTPError` constructor type annotations
- `test_executor_agent_principal.py`: null guard for `get_current_agent_principal()`

## [1.27.0] - 2026-03-14

### Added
- **Agent-as-principal Cerbos policy engine** -- agents get Cerbos identity from `role.metadata` (name, team, tags, author), enforced across CLI, compose, daemon, API, and pipeline
- **`check_delegation_policy()`** -- Cerbos-based delegation authorization between agents (inline with full metadata, MCP remote with name-only)
- **`DELEGATE` action constant** and `agent_checks_enabled` property on `CerbosAuthz`
- **`agent_principal_from_role()`** factory constructs Cerbos principals from role metadata
- **Per-run agent principal scoping** in executor via `_enter_agent_context()`/`_exit_agent_context()` with ContextVar token management
- Agent policy examples: `examples/policies/agent/` with derived roles, delegation policy, and tool policy
- Documentation: `docs/security/agent-policy.md`

### Changed
- `Principal.attrs` widened from `dict[str, str]` to `dict[str, Any]` (tags stored as native list)
- `CerbosToolset` now uses agent principals (`get_current_agent_principal()`) instead of user principals
- `DelegateSink` accepts `source_metadata`/`target_metadata` for policy checks using role metadata (not compose service keys)
- `InlineInvoker` and `McpInvoker` accept optional `source_metadata` for delegation policy checks
- `docker-compose.cerbos.yml` mounts agent policies, uses `INITRUNNER_CERBOS_AGENT_CHECKS`

### Removed
- User-management Cerbos code: `api/authz.py` (route guards, `AuthzGuard`, `ResourceFilter`, condition AST evaluator), JWT middleware, user principals, `ANONYMOUS` constant, `PlanResult`, `plan()`/`plan_async()` methods
- `requires()` FastAPI dependency from all 7 route files
- `authz_config` parameter from middleware, dashboard app, server app, CLI server command
- PyJWT from `authz` extra dependency
- User-role policy sets (`strict/`, `permissive/`, `team/`) and base-level user policy YAMLs
- `examples/roles/cerbos-tool-auth.yaml`, `docs/security/cerbos.md`

## [1.26.0] - 2026-03-14

### Added
- **Auto-discovered skills** -- skills in well-known directories (`./skills/`, `.agents/skills/`, `~/.agents/skills/`, `~/.initrunner/skills/`) are automatically found and exposed via a lightweight catalog. The model activates skills on demand using the `activate_skill` tool (agentskills.io three-tier progressive disclosure). Enabled by default; opt out with `auto_skills: { enabled: false }`
- **`activate_skill` meta-tool** -- loads full SKILL.md instructions and lists resource files when the model decides a skill matches the current task. Session-level deduplication prevents re-injection
- **`skill list --auto / --all`** -- CLI flags to show auto-discovered skills with scope and source info
- **History compaction exemption** -- `activate_skill` tool returns are preserved during conversation compaction instead of being truncated
- Example role `auto-skill-demo.yaml` and example auto-discoverable skill `summarizer`

## [1.25.0] - 2026-03-14

### Added
- **Memory import** -- `initrunner memory import role.yaml data.json` seeds an agent's memory store from exported JSON. Re-embeds content using the role's embedding config, preserves original `created_at` timestamps, validates records and fails fast on malformed input. Batch embeds in groups of 50
- **Shared document stores in compose** -- `spec.shared_documents` in compose YAML lets all services share a single document store with compose-owned embedding config. Prevents embedding model mismatches. Roles without ingest config get a minimal one injected so `search_documents` works

### Changed
- `MemoryStore.add_memory()` ABC and LanceDB implementation accept optional `created_at` parameter for timestamp preservation during import

## [1.24.0] - 2026-03-14

### Changed
- **Replace zvec with LanceDB** -- vector store backend switched from zvec (C++ native extension) to LanceDB (pure-Python, columnar). Removes Python 3.13 restriction and CI SIGILL workaround
- **Python 3.13 support** -- `requires-python` widened from `>=3.11,<3.13` to `>=3.11`; CI matrix now tests 3.11/3.12/3.13
- **Docker images default to Python 3.13** -- `Dockerfile`, installer Dockerfiles updated
- Legacy `store_backend: zvec` in role YAML is auto-migrated to `lancedb` with a deprecation warning

### Removed
- `zvec` dependency and all zvec store implementations (`_zvec_common.py`, `zvec_document_store.py`, `zvec_memory_store.py`, `zvec_store.py`)
- `SKIP_ZVEC_TESTS` CI workaround

## [1.23.0] - 2026-03-14

### Added
- **Curated Cerbos policy sets** -- three ready-to-use policy sets (`strict/`, `permissive/`, `team/`) in `examples/policies/`, each with 7 policy files covering agent, audit, daemon, ingest, memory, tool, and derived roles
- **Docker Compose for Cerbos** -- `docker-compose.cerbos.yml` runs InitRunner + Cerbos PDP with healthcheck, configurable policy set mount
- **Resource attribute resolver registry** -- `requires()` dependency automatically loads agent metadata (author, team, tags) as Cerbos resource attributes via registered resolvers on `app.state`
- **`team` field on Metadata** -- `metadata.team` in role YAML enables team-based Cerbos policy conditions
- **`GET /api/roles/{role_id}` authz guard** -- previously unguarded endpoint now checks Cerbos before returning role details

### Fixed
- **Cerbos SDK protobuf 6.x compatibility** -- switched from broken gRPC client to HTTP client (`cerbos.sdk.client`), resolving `TypeError` with protobuf >= 6.31
- **PlanResources list filtering** -- `should_include()` now passes `author` and `team` attributes alongside `name`, enabling policy conditions on agent metadata
- **Default Cerbos port** -- changed from 3593 (gRPC) to 3592 (HTTP) to match the HTTP client transport

### Changed
- `RoleSummary` API model now includes `author`, `tags`, and `team` fields
- `role_to_summary()` populates new metadata fields from loaded role

## [1.22.0] - 2026-03-13

### Fixed
- **Invalid YAML in example policy** -- quote CEL expression in `examples/policies/tool_policy.yaml` so leading `!` isn't interpreted as a YAML tag

## [1.21.0] - 2026-03-13

### Added
- **Cerbos tool-level authorization** -- per-tool-call identity-based checks via Cerbos PDP, controlled by `INITRUNNER_CERBOS_TOOL_CHECKS=true`. `CerbosToolset` wrapper reads principal from ContextVars; no-op when disabled or no principal (CLI/trigger paths). Policies match on `tool_type`, `agent`, `callable`, and `instance` attributes
- **Route-level Cerbos authorization** -- all dashboard and API endpoints protected by `requires()` dependency that checks Cerbos before handler execution. PlanResources-based list filtering for collection endpoints
- **Audit trail principal tracking** -- every audit record includes `principal_id` from JWT identity, API-key anonymous principal, or trigger platform identity (e.g. `telegram:12345`). Queryable via `GET /api/audit?principal_id=...`
- **Example Cerbos policies and role** -- `examples/policies/tool_policy.yaml` and `examples/roles/cerbos-tool-auth.yaml` demonstrating tiered tool access

### Changed
- `_run_with_timeout()` uses `contextvars.copy_context()` to propagate ContextVars through `ThreadPoolExecutor`
- `build_toolsets()` wraps all toolsets with `CerbosToolset` (inner) and `PermissionToolset` (outer, when configured)
- `TriggerEvent` carries `principal_id` and `principal_roles` from platform identity

### Documentation
- New: `docs/security/cerbos.md` -- full Cerbos reference (identity model, resource model, route matrix, tool-level auth, policy authoring)
- Updated: README security section mentions tool-level authorization

## [1.20.1] - 2026-03-12

### Fixed
- **Streaming retry bug** — `on_retry` callback (which clears partial output) was called even on terminal failure (last retry attempt), silently discarding accumulated streaming output. Now only called when a retry will actually follow

### Changed
- **Executor sync/async deduplication** — extracted shared helpers (`_should_retry`, `_process_agent_output`, `_process_stream_output`, `_record_span_metrics`, `_create_run_span`), reducing `executor.py` from 761 to ~580 lines and eliminating duplicated logic between sync and async paths
- **`zvec_store.py` split** — 1033-line god file split into `_zvec_common.py`, `zvec_document_store.py`, and `zvec_memory_store.py`; original file is now a backward-compatible re-export shim
- **Services layer compliance** — CLI and API routes now import business logic through `services/` layer: new `services/compose.py`, extended `services/operations.py` and `services/discovery.py`, updated `cli/audit_cmd.py`, `cli/compose_cmd.py`, `cli/memory_cmd.py`, `cli/role_cmd.py`, and API route files
- **Bare assertions replaced** — 42 bare `assert` statements across production code replaced with explicit `if`/`raise` for clear error messages (RuntimeError, ValueError, TypeError as appropriate)
- **Lazy import fix** — moved `_PROVIDER_API_KEY_ENVS` import in `setup_cmd.py` from top-level into function body

## [1.20.0] - 2026-03-12

### Added
- **Model aliases** — define semantic names (`fast`, `smart`, `local`) in `~/.initrunner/models.yaml` and use them in role files, CLI flags, and `chat.yaml`
- **`--model` CLI override** — override the role's model at runtime on `run`, `daemon`, `serve`, and `test` commands; backed by `INITRUNNER_MODEL` env var
- **`chat --model` alias support** — ephemeral chat and role-file chat modes resolve aliases; `chat.yaml` `model` field accepts aliases
- **`ModelConfig` inline provider:model syntax** — `name: openai:gpt-4o` auto-splits into provider + name when `provider` is omitted

### Changed
- `ModelConfig.provider` is now optional in role YAML when `name` contains a colon or resolves via alias (existing files with explicit `provider:` are unaffected)

### Documentation
- New: `docs/configuration/model-aliases.md` — full reference for aliases, `--model` override, precedence, and edge cases
- Updated: `docs/configuration/providers.md` — model aliases section, updated model config reference table
- Updated: `docs/getting-started/cli.md` — `--model` flag documented on `run`, `serve`, and `chat` option tables
- Updated: `CLAUDE.md` — model aliases doc added to documentation index

## [1.19.0] - 2026-03-12

### Changed
- **BREAKING: Collapse report CLI flags** — `--export-report` + `--report-path` replaced by `--report PATH`; `--report-template` without `--report` now errors
- **BREAKING: Simplify `memory clear` filters** — `--sessions-only`/`--memories-only` replaced by `--what` (sessions|memories|all); `--what sessions --type X` errors
- **BREAKING: Rename `timeout` → `timeout_seconds`** on `McpToolConfig`, `ApiEndpoint`, `ToolkitWebReaderConfig`, `ToolkitHttpConfig` — aligns with all other tool configs
- Extract `reduce_history()` helper in `agent/history.py` — deduplicates compact+trim sequence from autonomous and daemon runners
- Inline `_capture_autonomous_episode()` — removed trivial 3-line wrapper in favour of direct `capture_episode()` call

### Documentation
- Report export docs updated with new `--report PATH` flag syntax
- CLI reference updated for `--report` and `memory clear --what`

## [1.18.0] - 2026-03-11

### Changed
- **BREAKING: Remove `MemoryConfig.max_memories`** — use `semantic.max_memories` instead; old YAML files get a clear migration error with instructions
- `apply_shared_memory()` now patches `semantic.max_memories` instead of the removed top-level field
- API `MemoryDetail` model no longer exposes `max_memories` (use `semantic_max`)

### Added
- **Shared CLI option aliases** — `AuditDbOption`, `NoAuditOption`, `SkillDirOption` in `initrunner/cli/_options.py` eliminate per-command duplication
- **`INITRUNNER_AUDIT_DB` env var** — sets default audit database path (overridden by `--audit-db` flag)

### Documentation
- All memory config examples updated to use nested `semantic.max_memories`
- CLI reference updated with `INITRUNNER_AUDIT_DB` env var
- Removed deprecated backward-compatibility notes from memory docs

## [1.17.0] - 2026-03-11

### Added
- **Compose auto-routing** — `strategy: keyword|sense` on delegate sinks routes messages to the best-matching target via intent scoring instead of static fan-out
- **`RouterSink`** — wraps multiple `DelegateSink` instances, scores output against target metadata, forwards to winner
- **`select_candidate_sync()`** — reusable intent-scoring core extracted from `role_selector` (no filesystem I/O)
- **Dual-scoring fallback** — falls back to original user prompt when output text is inconclusive
- **Support-desk example** — 4-service compose pipeline demonstrating `strategy: sense`
- New test files: `test_compose_router_sink.py`, `test_role_selector.py`

### Changed
- `DelegateSinkConfig` accepts `strategy` field (`all`/`keyword`/`sense`, default `all`)
- `select_role_sync()` refactored as thin wrapper over `select_candidate_sync()`
- Orchestrator tracks `_router_sinks` separately to avoid double-close

### Documentation
- Updated: `docs/orchestration/agent_composer.md` — routing strategy section
- Updated: `docs/orchestration/sinks.md` — strategy mention
- Updated: `docs/core/intent_sensing.md` — compose integration section
- Updated: `README.md` — auto-routing in feature comparison, compose section, examples

## [1.16.0] - 2026-03-06

### Added
- **Async compose orchestrator**: services run as asyncio tasks on a shared event loop instead of individual threads; agent executions dispatched to a configurable `ThreadPoolExecutor` (`max_agent_workers`). Sync façade (`run_compose()`, `start()`/`stop()`) preserved
- **Async tool execution**: `execute_run_async()` and `execute_run_stream_async()` use PydanticAI's native `agent.run()` with `asyncio.wait_for` for timeouts — no thread-pool hop
- **`prefer_async` tool build flag**: `ToolBuildContext.prefer_async` propagates through `build_agent → build_toolsets → tool builders`, letting I/O-bound tools register async closures
- **Async tool variants**: `http`, `web_reader`, `web_scraper` (concurrent embeddings via `asyncio.gather`), and `search` tools provide native async closures when `prefer_async=True`
- **Async signal handler**: `install_async_shutdown_handler()` in `_signal.py` with double-Ctrl-C force-exit pattern for asyncio event loops
- **Queue bridge pattern**: sync `queue.Queue` → `asyncio.Queue` bridge inside `ComposeService` preserves `DelegateSink` sync contract while enabling async service loops
- **Dual-mode health monitor**: `HealthMonitor` runs as asyncio task (compose) or thread (standalone)
- **`AsyncSSRFSafeTransport`**: async SSRF protection for `httpx.AsyncClient`
- **`fetch_url_as_markdown_async()`**: async HTML fetch and markdown conversion
- **`embed_single_async()`**: async embedding for concurrent batch processing
- **Native async API streaming**: `_streaming.py` uses `execute_run_stream_async()` directly — eliminates thread-pool hop for SSE streaming
- New test files: `test_compose_async_internals.py`, `test_executor_async.py`, `test_signal_async.py`

### Fixed
- OCI registries on localhost now work over plain HTTP (previously required HTTPS)
- Credential helpers warning test uses explicit logger name for reliable caplog capture

### Changed
- Compose services build agents with `prefer_async=True` for async tool closures
- `HealthMonitor.start()` accepts optional `loop` parameter for task-mode scheduling
- `ComposeService.start()` accepts optional `loop` and `executor` parameters

### Documentation
- Updated: `docs/orchestration/agent_composer.md` — new Runtime Architecture section (async event loop, queue bridge, shutdown semantics, executor pool sizing)
- Updated: `docs/agents/tool_creation.md` — `prefer_async` in ToolBuildContext table, new Async Tool Builders section
- Updated: `docs/operations/testing.md` — new Async Tests section with test file table
- Updated: `CLAUDE.md` — "Sync CLI, async compose" key pattern

## [1.15.0] - 2026-03-06

### Added
- **OCI registry distribution**: publish and install complete role bundles to any OCI-compliant registry (Docker Hub, GHCR, ECR) via `initrunner publish`, `initrunner pull`, and `initrunner install oci://...`
- **Role bundles**: deterministic `.tar.gz` archives containing role YAML, resolved skills, schema files, and explicit data files with SHA-256 integrity verification
- **OCI authentication**: `initrunner login` command with credential resolution chain (env vars → oci-auth.json → Docker config base64 auth)
- **Qualified install IDs**: manifest keys use `github:owner/repo/name` and `oci:registry/repo/name` to prevent name collisions across sources
- **Bundle metadata field**: optional `metadata.bundle.include` for explicit extra file globs in role YAML
- New CLI commands: `publish`, `pull`, `login`
- New modules: `initrunner/packaging/` (bundle, auth, oci), `initrunner/services/packaging.py`

### Changed
- `initrunner list` shows Source Type column (GITHUB/OCI)
- `initrunner info` supports OCI references (displays bundle manifest metadata)
- `initrunner update` supports OCI sources (compares manifest digests)
- `uninstall` handles directory-based OCI bundle installs
- Manifest keys migrated from bare names to qualified IDs on read (backward compatible)

### Documentation
- New: `docs/core/oci-distribution.md` — full guide for OCI publishing, authentication, bundle format, and commands
- Updated: README with OCI Registry Distribution section and documentation table entry

## [1.14.0] - 2026-03-03

### Added
- **Conversation history compaction** (`autonomy.compaction`): LLM-driven summarisation of older messages in long-running autonomous loops — keeps context manageable without silently dropping history. Configurable threshold, tail preservation, and optional cheap model override for summaries. Fail-open: compaction errors are logged, never crash the agent
- **Heartbeat trigger** (`triggers.heartbeat`): fixed-interval periodic trigger that reads a markdown checklist file and prompts the agent only when unchecked items remain. Supports timezone-aware active hours, 64 KB file size cap, and autonomous mode
- **Config hot-reload** (`daemon.hot_reload`): daemon mode watches role YAML and skill files for changes and reloads config without restart. Intelligent dispatcher restart (only when trigger config changes), thread-safe in-flight execution with snapshot semantics, fail-open on invalid config
- Example roles: `long-running-analyst.yaml` (compaction), `ops-heartbeat.yaml` + `ops-checklist.md` (heartbeat trigger), `reloadable-assistant.yaml` (hot-reload daemon)

### Changed
- `DaemonRunner` accepts `role_path` and `extra_skill_dirs` parameters for hot-reload support
- `AutonomyConfig` includes nested `CompactionConfig` with defaults (disabled, threshold=30, tail=6)
- Trigger dispatcher registers `HeartbeatTriggerConfig` builder
- CLI `daemon` command passes role path and skill dirs to runner

### Documentation
- Updated: `docs/core/triggers.md` — added heartbeat trigger section and hot-reload subsection
- Updated: `docs/orchestration/autonomy.md` — added compaction config reference and troubleshooting

## [1.13.0] - 2026-03-02

### Added
- **Docker container sandbox** (`security.docker`): opt-in kernel-level isolation for shell, Python, and script tool execution — network namespaces, cgroups, read-only rootfs, memory/CPU limits, bind mounts. Configured via `security.docker.enabled: true` in role YAML. Doctor command shows Docker availability status
- **Shared streaming module** (`api/_streaming.py`): SSE streaming, upload staging, and attachment resolution utilities extracted from chat_ui and quick_chat routes
- **MCP transport module** (`mcp/_transport.py`): unified MCP transport construction (stdio, SSE, streamable-http) with sandbox validation and env scrubbing
- **Async utility** (`_async.py`): `run_sync()` helper for running async coroutines from sync code with event loop reuse and thread fallback
- **Store factory helpers** (`stores/factory.py`): `managed_memory_store()` context manager for full memory store lifecycle (create → register → yield → unregister → close)
- **Domain filtering** (`agent/_urls.py`): `check_domain_filter()` for URL domain allow/block list validation
- **AgentSpec.features property** (`agent/schema/role.py`): lists enabled optional features (tools, triggers, ingest, memory, sinks, skills)
- **Provider helpers** (`services/providers.py`): `is_ollama_running()`, `list_ollama_models()`, `resolve_provider_and_model()` for consolidated provider/model detection
- Example role: `docker-sandbox.yaml`

### Changed
- **MCP toolkit refactored**: extracted tool implementations into shared helper functions; toolkit.py reduced from inlined logic to thin wrappers calling core functions in each tool module
- **Email tools**: extracted core IMAP/SMTP logic into standalone functions (`_do_search_inbox`, `_do_read_email`, `_do_send_email`, `_do_list_folders`), added `ImapParams` dataclass, added header/IMAP injection security guards
- **CSV analysis tools**: extracted `_load_csv`, `_do_inspect_csv`, `_do_summarize_csv`, `_do_query_csv` for MCP reuse
- **Search tools**: consolidated error handling and result formatting into `_do_search`
- **Audio tools**: extracted `_do_get_youtube_transcript` for MCP reuse
- **API routes**: `chat_ui.py` and `quick_chat.py` deduplicated ~200 lines via shared `_streaming` module
- **CLI commands**: migrated provider checks to `services.providers`, simplified memory lifecycle with `managed_memory_store()`
- **Store config**: `make_store_config()` helper replaces inline `_make_store_config()` in registry
- `check_tool_envs()` return type changed from `set` to `dict[str, list[str]]` for richer error messages

### Documentation
- New: `docs/security/docker-sandbox.md` — full Docker sandbox configuration reference
- Updated: `docs/security/security.md` — added Docker sandbox section
- Updated: `CLAUDE.md` — added Docker sandbox to documentation index

## [1.12.0] - 2026-03-02

### Added
- **Intent-driven setup wizard** (`initrunner setup`): redesigned from 5-step to 13-step flow — intent selection ("What do you want to build?"), tool picker with per-intent defaults, embedding config warnings, intent-specific prompts (bot tokens, doc sources, daemon triggers), and `chat.yaml` generation
- 8 intents: `chatbot`, `knowledge`, `memory`, `telegram-bot`, `discord-bot`, `api-agent`, `daemon`, `from-example` (bundled example browser)
- `--intent` flag on `setup` command (replaces `--template`, which is retained as deprecated)
- `--skip-chat-yaml` flag on `setup` command
- **xAI provider support**: detected by `needs_setup()`, listed in provider picker, uses OpenAI SDK
- **Bedrock provider support** in `_compat.py`: `require_provider("bedrock")` gives proper install hint (`pip install initrunner[all-models]`)
- `initrunner/services/setup.py` — shared setup business logic (CLI, API, TUI all use this): `SetupConfig` dataclass, `needs_setup()`, `detect_existing_provider()`, `validate_api_key()`, `generate_role_yaml()`, `generate_chat_yaml()`, `save_chat_yaml()`, `run_connectivity_test()`

### Fixed
- Ollama + non-chatbot intent no longer silently overrides the selected template — `generate_role_yaml()` derives template from intent, not provider
- xAI API key (`XAI_API_KEY`) now detected by `needs_setup()` so setup wizard doesn't re-prompt when already configured

### Documentation
- `docs/getting-started/setup.md` rewritten for 13-step intent-driven wizard
- `docs/interfaces/mcp-gateway.md` expanded with per-client config sections (Gemini CLI, Codex CLI, Windsurf)
- README install instructions updated for PEP 668: shell installer promoted as primary path, `uv`/`pipx` before bare `pip`

## [1.11.0] - 2026-03-01

### Added
- **MCP Toolkit** (`initrunner mcp toolkit`): expose InitRunner tools directly as an MCP server — no agent, no LLM, no API key required for default tools. Any MCP client (Claude Code, Cursor, Codex CLI, etc.) gets web search, page fetching, CSV analysis, and datetime tools instantly
- Default tools: `search` (web_search, news_search), `web_reader` (fetch_page), `csv_analysis` (inspect_csv, query_csv, summarize_csv), `datetime` (current_time, parse_date)
- Opt-in tools: `sql`, `http`, `email`, `audio` (YouTube transcripts) — configurable via `toolkit.yaml` or `--tools` flag
- `--config/-c` flag for YAML configuration with `${VAR}` env var interpolation
- `build_toolkit_sync()` service wrapper in `services/operations.py`
- MCP Toolkit documentation in `docs/interfaces/mcp-gateway.md`

### Documentation
- Updated README with MCP Toolkit section and test count

## [1.10.0] - 2026-03-01

### Added
- **Think tool** (`type: think`): zero-overhead reasoning scratchpad; thoughts preserved in tool call args for tracing, constant `"Thought recorded."` return; no API calls or subprocesses
- **Script tool** (`type: script`): define inline shell scripts in YAML as named agent tools; parameters injected as uppercase env vars; per-script interpreter override, `allowed_commands` validation, and configurable timeouts
- **MCP Gateway** (`initrunner mcp serve`): expose one or more agents as an MCP server over stdio, SSE, or streamable-http transport; compatible with Claude Desktop, Claude Code, and Cursor
- `--pass-through` flag for MCP gateway to also expose agents' own MCP sub-tools directly (with full sandbox checks)
- Example roles: `thinker.yaml`, `script-runner.yaml`
- MCP gateway documentation (`docs/interfaces/mcp-gateway.md`)

### Documentation
- Added think and script tools to builtin tools reference in `docs/agents/tools.md` and `docs/agents/tool_creation.md`
- Added think and script examples to `docs/agents/example_tools.md`
- Added `mcp serve` options to CLI reference (`docs/getting-started/cli.md`)
- Added MCP gateway to CLAUDE.md documentation index

## [1.9.0] - 2026-02-28

### Fixed
- `test --dry-run` no longer requires an API key — uses `TestModel` directly instead of building the real model
- Suppress `PytestCollectionWarning` for `TestCase` and `TestSuiteDefinition` schema classes

### Added
- **Agent evals**: LLM-as-judge (`llm_judge`), tool call verification (`tool_calls` with exact/subset/superset modes), token budget (`max_tokens`), and latency cap (`max_latency`) assertion types
- `EvalContext` dataclass for passing extended run metadata (tool calls, tokens, latency) to assertion evaluators
- `eval/judge.py`: thread-safe cached LLM judge with defensive JSON parsing
- Concurrent eval execution (`-j/--concurrency` flag) with deterministic result ordering via `ThreadPoolExecutor`
- Tag-based case filtering (`--tag` flag) for selective eval runs
- JSON result export (`-o/--output` flag) with stable schema for CI integration
- `SuiteResult.to_dict()` with summary stats (total tokens, duration)
- `tool_call_names` field on `RunResult` extracted from `ToolCallPart` messages
- `services/eval.py` thin services layer following existing CLI/API/TUI pattern
- `docs/core/evals.md` comprehensive documentation
- Example eval suites in `examples/evals/`

### Changed
- `evaluate_assertion()` signature changed from `(assertion, output: str)` to `(assertion, ctx: EvalContext)` (internal API)
- `_display_suite_result()` now shows Tokens column and summary stats line
- `TestCase` and `TestSuiteDefinition` list fields normalized to `Field(default_factory=list)`

## [1.8.1] - 2026-02-28

## [1.8.0] - 2026-02-28

### Added
- One-click cloud deploy templates for Railway (`railway.json`), Render (`render.yaml`), and Fly.io (`deploy/fly.toml`)
- Docker entrypoint script (`deploy/docker-entrypoint.sh`) that seeds 5 example roles on first boot when `/data/roles` is empty
- `full-tools-assistant.yaml` example role with all zero-config tools enabled (datetime, search, web_reader, web_scraper, filesystem, git, python, shell, csv_analysis, audio)
- Cloud deployment guide (`docs/getting-started/cloud-deploy.md`)

### Changed
- Dockerfile: `ENTRYPOINT` changed from `["initrunner"]` to `["docker-entrypoint.sh"]` with `CMD ["initrunner", "--help"]` to avoid double-prefix on cloud platforms
- `docker-compose.yml`: roles now served from `/data/roles` (was `/roles`); example roles seeded automatically; command includes `initrunner` prefix

### Documentation
- New Cloud Deploy section in README with Railway and Render deploy buttons
- Cloud deployment doc added to CLAUDE.md documentation index

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