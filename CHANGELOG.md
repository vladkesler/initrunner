# Changelog

## [2026.6.4] - 2026-06-15

### Added
- **More `spec.model` settings reach the provider.** `role.yaml` now exposes `top_p`, `top_k`, `seed`, `stop_sequences`, `parallel_tool_calls`, `presence_penalty`, `frequency_penalty`, `logit_bias`, `extra_headers`, and `extra_body`, passed straight through to PydanticAI's `ModelSettings`. The sampling knobs are dropped on OpenAI reasoning models, the same way `temperature` already was. See `docs/configuration/providers.md`.
- **Static `tool_choice` in `spec.model`.** `auto` (provider default) or `none` (text-only mode, tools disabled). `required` and tool-name lists are rejected at load with a message pointing to dynamic capabilities, because a static value there would force a tool call on every step and prevent a final response.
- **Provider-native prompt caching.** `spec.model.prompt_cache: true` (or a mapping with `instructions`, `tools`, `ttl`) caches the static request prefix on Anthropic and Bedrock, mapping to their `*_cache_instructions` / `*_cache_tool_definitions` settings. Rejected at load on other providers. Cuts input-token cost for daemons and triggers with large static prompts. See `docs/configuration/providers.md`.
- **`fallback_on` for multi-provider failover.** `spec.model.fallback_on` narrows or widens which exceptions trigger failover (`ModelAPIError`, `ModelHTTPError`, `UnexpectedModelBehavior`, `ContentFilterError`); the default stays `ModelAPIError`. Requires a `fallback` list.
- **Model-request concurrency limits.** `spec.model.concurrency` (`max_running`, `max_queued`, `share`) caps in-flight model requests via PydanticAI's `ConcurrencyLimitedModel`. A named `share` makes several agents in one process (compose services, team personas, flow nodes) coordinate against one provider budget. Distinct from `execution.max_concurrency`, which bounds tool execution. See `docs/configuration/providers.md`.
- **Tunable HTTP retries.** `spec.execution.http_retries` and `http_retry_max_wait` configure the new transport-level retry policy (see Changed).
- **`doctor` checks the model name.** With `--role`, `doctor` now flags a `provider:model` that is not in PydanticAI's known-model list and suggests the closest match on a likely typo (`gpt-4o-minii` warns "did you mean 'openai:gpt-4o-mini'?"). Advisory only, and custom endpoints are skipped. Backed by PydanticAI's `known_model_names()`. See `docs/operations/doctor.md`.
- **Native pydantic-evals report output.** `initrunner test --report` prints the native `EvaluationReport` (per-evaluator scores, averages, span analyses) and `--report-json` saves the full report; both imply `--pydantic-evals` and need the `observability` extra. See `docs/core/evals.md`.
- **AgentSpec metadata round-trips.** `metadata.tags`, `author`, `team`, and `version` now survive export to and import from PydanticAI Agent Spec instead of being dropped. See `docs/getting-started/agent-spec-import.md`.

### Changed
- **Bumped `pydantic-ai-slim` and `pydantic-evals` from 1.102.0 to 1.107.0.** Pulls in the upstream UI-adapter file-read security fix, Claude Opus 4.8 / Fable 5 / Mythos 5 and Grok 4.3 model support, `CachePoint` caching for OpenRouter, and `known_model_names()`. Adds the `retries` extra.
- **Model-call retries now live in the httpx transport.** Replaced the hand-rolled status-code backoff loop in `executor_retry.py` with PydanticAI's `AsyncTenacityTransport`, injected into each provider client at construction. Retries `{429, 500, 502, 503, 504}` with exponential backoff and `Retry-After` support, uniformly across one-shot, REPL, streaming, and daemon runs; permanent errors (401/403/404/422) surface immediately. Covers OpenAI, Anthropic, Google, Groq, Mistral, Cohere, and custom OpenAI-compatible endpoints; Bedrock and xAI keep their SDKs' native retries. As a side effect this fixed a latent bug where a custom `api_key_env` was ignored for standard providers (the key is now passed to the client explicitly). See `docs/configuration/providers.md`.
- **Human approval now uses PydanticAI's `ApprovalRequiredToolset`.** Replaced InitRunner's custom `ApprovalToolset` (which hand-marked tool definitions `kind="unapproved"`) with the native toolset and its `approval_required_func` callback. Same observable pause-and-resume behavior; the approval gate now sits outermost, so an approved call still descends through the policy and permission deny-rules at execution time.

### Security
- **Broadened SSRF blocklist and IPv6 coverage for URL-fetching tools.** Building on the IP-pinning transport, the blocklist now catches cloud metadata endpoints that no private range covers (Azure WireServer's public IP `168.63.129.16`, plus AWS ECS/EKS, Oracle, Scaleway, and IPv6 endpoints), decodes IPv6 transition forms that embed an IPv4 address (IPv4-mapped, IPv4-compatible, 6to4, NAT64, ISATAP, Teredo) so a blocked address cannot be smuggled as IPv6 (e.g. `2002:7f00:1::` is 6to4 for `127.0.0.1`), adds `224.0.0.0/4`, `100::/64`, `2001::/32`, and `ff00::/8`, and strips trailing-dot FQDNs (`blocked.com.`) so they cannot slip past exact-match allow/blocklists. See `docs/security/security.md`.

## [2026.6.3] - 2026-06-07

### Changed
- **Usage telemetry is now opt-in.** Anonymous telemetry no longer runs by default. The CLI asks once, on the first interactive run (a real subcommand with a terminal attached), and sends nothing until you accept; non-interactive runs, pipes, daemons, `--help`, completion, and the `telemetry` subcommands never prompt and never send. The dashboard defers `posthog-js` until you accept a consent banner (Enable / No thanks). Manage it anytime with `initrunner telemetry enable`/`disable`, `DO_NOT_TRACK=1`, or `INITRUNNER_TELEMETRY=off`. On upgrade, an explicit prior `initrunner telemetry disable` is preserved; any other prior state is reset to undecided so you are asked once under the new default. The persisted state file moves to schema v2 (a tri-state `consent` value), migrated in place. See `docs/operations/telemetry.md`.

## [2026.6.2] - 2026-06-07

### Added
- **Anonymous, opt-out usage telemetry (PostHog).** InitRunner now reports anonymous usage so the maintainers can see whether and how it is used. Per CLI command it sends the command name (from a known list, never arguments), the outcome and exception class (never the message), a coarse duration bucket, OS, Python version, and InitRunner version, tied to a random install id, not to you. No prompts, file contents, paths, arguments, or API keys are sent, and events are anonymous (no PostHog person profiles, and `$ip` is overridden to `0.0.0.0` so the real source IP is never stored). It is shipped in core with a tiny dependency-free sender that never blocks process exit, and a one-time notice prints before the first send. Turn it off with `initrunner telemetry disable`, `DO_NOT_TRACK=1`, or `INITRUNNER_TELEMETRY=off`; it is off by default in CI. New `initrunner telemetry status|enable|disable|reset`, a status line in `initrunner doctor`, and `INITRUNNER_TELEMETRY_DEBUG=1` to print events without sending. The dashboard adds the same opt-out posture via `posthog-js` (no autocapture or session recording, honors Do Not Track). See `docs/operations/telemetry.md`.
- **Guided start menu for `initrunner new`.** Running `initrunner new` with no seed in a terminal now shows a numbered picker (describe / template / example / build offline / import), each annotated with whether it needs an API key. Piped or non-TTY input keeps the previous LLM-conversation fallback. See `docs/agents/role_generation.md`.
- **Offline role builder.** New `initrunner new --offline` (and menu option 4) builds a valid `role.yaml` through a deterministic structured form (name, system prompt, provider/model, tool multi-select, memory/ingest/trigger toggles) with no LLM or network call. Entered tool-field values are parsed through YAML so numbers, booleans, and lists keep their types. Backed by a new pure `services/wizard.py`.
- **Credential preflight.** Before an AI-backed seed, the builder resolves the API key through the vault and environment, prints `Using <provider>:<model>`, and on a missing key (in a terminal) offers to enter a key inline, switch provider, or build offline, instead of failing with a 401 mid-generation. Custom-endpoint presets (`base_url`, `api_key_env`) are carried through a provider switch.
- **Refinement-loop commands.** The refine step accepts `:` commands (`:help` / `?`, `:yaml`, `:validate`, `:explain`, `:tools`, `:diff`, `:model`, `:undo`, `:save`, `:quit`). `:model` changes the model and `:undo` reverts the last change, both deterministically with no LLM call; each AI refinement prints a `+adds -removes` change summary. When no API key is configured, plain-text refinement is replaced by a hint, so template, example, and offline roles can still be edited and saved.
- **First-run offline path.** Bare `initrunner` with no provider configured now offers to build an agent offline, instead of only printing the setup hint.

### Fixed
- **Invalid sidecar module names from awkward role filenames.** A stem starting with a digit or containing dots (e.g. `2fa-bot.yaml`) produced an unimportable Python sidecar module for imported custom tools; stems are now sanitized to a valid identifier. The same sanitizer is reused by `initrunner new --template tool`.
- **Consistent validation display in `initrunner new`.** Post-save warnings now render through the shared validation panel (severity labels, line and column, fix hints) instead of ad-hoc lines.

### Security
- **Bump `aiohttp` 3.13.4 to 3.14.0.** Closes two moderate advisories fixed in 3.14.0: cross-origin redirect leaking per-request cookies (`GHSA-hg6j-4rv6-33pg`, CVE-2026-47265) and deserialization of untrusted data (`GHSA-jg22-mg44-37j8`, CVE-2026-34993). `aiohttp` is a transitive dependency of the optional `discord-py` and `xai-sdk` packages. (#146)

## [2026.6.1] - 2026-06-02

### Security
- **Critical: gate bundle-shipped custom-tool code execution.** Loading a `custom` tool imported a module by name, which runs that module's top-level code in the InitRunner process; the AST import scan was never a real boundary. A role installed from InitHub or an OCI registry could ship a tool module that ran arbitrary code on `initrunner run`. Importing a module that ships inside an installed role (directories named `hub__*`/`oci__*`, or containing a bundle `manifest.json`) is now refused unless the operator sets `INITRUNNER_ALLOW_TOOL_CODE=1` -- an environment variable, never a role-YAML field, so a malicious bundle cannot self-grant trust. Locally-authored roles load their own tool modules unchanged, and `initrunner install` previews now flag bundles that declare code-executing tools. See `docs/security/security.md`. (#144)
- **Fail closed on network-exposed servers.** Authentication was opt-in: with no API key the dashboard, MCP gateway (sse/streamable-http), and A2A server served every endpoint unauthenticated, and `--expose` only printed a warning. Binding a non-loopback host without a key now generates and prints a one-time key instead of serving open, across all three. The MCP gateway gains `--api-key` (env `INITRUNNER_MCP_API_KEY`) on `serve`/`toolkit`/`browser`. Loopback binds may still run keyless for local dev. (#139)
- **Block DNS-rebinding of the localhost dashboard.** Added Starlette `TrustedHostMiddleware` so the dashboard rejects requests whose `Host` header is not `localhost`/`127.0.0.1`, preventing a malicious page from driving the local dashboard through a rebinding hostname. The session cookie's `Secure` flag now derives from the connection scheme rather than the spoofable `X-Forwarded-Proto` header. (#139)
- **Pin the validated IP to defeat SSRF DNS rebinding.** `SSRFSafeTransport` validated the URL and then let httpx re-resolve and connect, so a rebinding resolver could pass validation and connect to `169.254.169.254`/`127.0.0.1`. It now resolves once, validates every returned address, and connects to the pinned IP while preserving the Host header and TLS SNI, for both the sync and async transports and every redirect hop. The blocklist gains `100.64.0.0/10` (CGNAT, including the Alibaba metadata endpoint `100.100.100.200`), `192.0.0.0/24`, `192.0.2.0/24`, `198.18.0.0/15`, `198.51.100.0/24`, `203.0.113.0/24`, `240.0.0.0/4`, and IPv6 `::/128` and `2001:db8::/32`. (#140)
- **Close audit-hook sandbox bypasses.** `_check_open` now decodes write intent from `os.open()` integer flags, not just the `open()` mode string (an `os.open(path, O_WRONLY|O_CREAT)` previously skipped the `allowed_write_paths` check), and the subprocess block covers `os.posix_spawn`, `os.exec*`, `os.fork`, and `os.forkpty` in addition to `subprocess.Popen`/`os.system`. Sandbox violations are now recorded to the audit chain, and the docs no longer claim the in-process hook contains a determined adversary. (#141)
- **Confine dashboard builder reads to the bundled starters directory.** The builder's starter-seed path and `resolve_starter_path` joined a request-supplied slug onto a filesystem path with only an `is_file()` check, so a slug like `../../../etc/passwd` read arbitrary `.yaml` files. Both now confine every candidate to `STARTERS_DIR` (rejecting `..`, absolute, and symlink escapes), alongside the builder save-path containment on the same change. (#138)
- **Bump `pyjwt` 2.12.1 to 2.13.0.** Closes PYSEC-2026-175, PYSEC-2026-177, PYSEC-2026-178, and PYSEC-2026-179, four advisories fixed in 2.13.0. `pyjwt[crypto]` is a transitive dependency.
- **Broaden subprocess environment scrubbing.** The name denylist missed `AWS_ACCESS_KEY_ID`, `GITHUB_PAT`, `SECRET_KEY_BASE`, and `*_DSN`, leaking them into tool subprocess environments. It now strips whole-provider prefixes (`AWS_`, `AZURE_`, `OPENAI_`, ...) and more secret-shaped suffixes (`_PAT`, `_DSN`, `_KEY_BASE`, `_CONNECTION_STRING`, ...). Tools inherit almost no environment, so dropping a non-secret like `AWS_REGION` is harmless. (#143)
- **Cap chunked request bodies; stop trusting client-set audit identity.** The body-size limit only checked `Content-Length`, which a chunked `Transfer-Encoding` request omits, allowing an unbounded body to buffer into memory. A streaming bounded read now caps both the OpenAI-compatible server and the webhook trigger regardless of headers. The webhook no longer copies the client `X-Principal-Id` header into the HMAC-chained audit trail as the run's actor; it records the claim as untrusted metadata instead. (#143)

### Changed
- **`security.sandbox.docker.extra_args` is now an allowlist.** The exact-string denylist missed `-v`/`--volume`/`--mount`, the space-separated `--pid host` form, `--gpus`, `--cgroup-parent`, and others, each of which escapes the container. Only resource and label flags are permitted now; mounts, host namespaces, capabilities, devices, and runtime overrides are rejected at load. Configs relying on those flags will fail validation. (#141)
- **Writable bind mounts of host system roots are refused.** `SandboxConfig` rejects `allowed_write_paths` entries or writable `bind_mounts` whose source is a host system root (`/`, `/etc`, `/usr`, `/home`, ...); read-only binds are unaffected. (#141)
- **Exec tools warn when unsandboxed.** `shell`, `python`, and `script` log a warning when built with `security.sandbox.backend: none` (host execution), and `shell` warns on an empty `allowed_commands` list (every binary, including interpreters, is permitted). (#141)

### Fixed
- **Test isolation: clear the `get_home_dir()` cache around every test.** The `@lru_cache`d home resolver retained a temp path set by an env-var monkeypatch, so later tests that relied on the real home failed depending on collection order. An autouse `conftest` fixture now clears the cache before and after each test. (#142)

### Dependencies
- Bump dashboard `svelte` 5.55.9 to 5.56.0 (svelte group). (#135)
- Bump dashboard `js-yaml` 4.1.1 to 4.2.0. (#136)
- Bump dashboard `vite` 8.0.14 to 8.0.16. (#137)

## [2026.5.5] - 2026-05-29

### Added
- **Native extended-thinking effort.** New `model.thinking` field (`false | minimal | low | medium | high | xhigh`) populates PydanticAI's `ModelSettings["thinking"]` at agent-build time, validated at load against reasoning-model support, with per-flow-agent and per-persona overrides. Thinking-token usage is read from the model usage details and recorded on `RunResult` and in the audit trail. See `docs/core/reasoning.md`.
- **Per-role output modes.** New `output.mode` (`auto | tool | native | prompted | text`, default `auto`) wraps the resolved output type in the matching PydanticAI wrapper (`ToolOutput` / `NativeOutput` / `PromptedOutput` / `TextOutput`); `auto` defers to PydanticAI's native model-profile detection. See `docs/core/structured-output.md`.
- **Verified reflexion.** `ReflexionStrategy` can bind the LLM judge as a verification gate: after each critique round it scores output against the role's success criteria, short-circuits once all criteria pass, and otherwise feeds the per-criterion failure reasons into the next continuation prompt. Verdicts are audited, turning "reflect N times" into "reflect until verified, max N". See `docs/core/reasoning.md`.
- **Hybrid retrieval.** New `retrieval` strategy (`vector | hybrid | hybrid_rerank`, default `vector`) on the document store. `hybrid` adds a BM25 full-text index alongside the vector column and fuses results with reciprocal rank fusion; `hybrid_rerank` adds an optional cross-encoder stage that degrades to plain RRF when `sentence-transformers` is absent. New `hybrid_search` method on the `DocumentStore` ABC. See `docs/core/rag-guide.md`.
- **Durable, resumable flows.** New `durability` block on `FlowSpec` with an audit-backed checkpoint journal (`flow/checkpoint.py`) keyed by `flow_run_id`. Completed delegation envelopes are recorded through the HMAC audit chain and replayed on `initrunner flow resume <id>` instead of re-running. `backend` is `none | journal` (default `none`), so single-shot and REPL runs are unaffected. See `docs/orchestration/durability.md`.
- **Ensemble voting.** New `ensemble` delegate-sink and team strategy plus a SpawnPool-backed fan-out that runs the same prompt K times. A reducer selects the winner by `majority`, `weighted` (per-target YAML weight), or `judge` (the LLM judge), and emits the winning envelope and full vote trace to the audit chain. See `docs/orchestration/flow.md`.
- **First-class evaluation on pydantic-evals.** The YAML `TestSuite` schema is unchanged, but cases now run through a pydantic-evals `Dataset` of evaluators producing an `EvaluationReport`. Adds span-based assertions over OpenTelemetry spans and the structured run-event timeline, and reuses the existing LLM judge as a custom evaluator so local, no-Logfire setups still work. See `docs/operations/testing.md`.
- **Cyclic loop-back routing.** New bounded `loop_back` edge (`{target, max_iterations, until}`) on the delegate sink enables writer/critic refine loops. Cycle detection in `initrunner/_graph.py` now permits only explicitly-marked loop-back edges; every other cycle is still rejected. See `docs/orchestration/flow.md`.
- **Structured blackboard shared-state.** A typed `Blackboard` is now the flow graph's run state, exposed to agents through a run-scoped `blackboard` tool (`post` / `read` / `claim` / `list`). Fan-in joins read attributed entries instead of only concatenating prompt strings, and the final board is persisted to the audit chain. See `docs/orchestration/blackboard.md`.
- **In-process local embeddings.** New `provider: local` embeds documents in-process via `fastembed` (the `local-embeddings` extra), distinct from the HTTP-backed `ollama` provider, so no endpoint is required and no document text leaves the process. See `docs/configuration/providers.md`.
- **Dashboard surfacing for the new capabilities.** The audit table and cost views now show thinking and reasoning token counts; the audit detail drawer renders a per-run event timeline (tool calls, tool results, thinking) and verified-reflexion judge verdicts via a new `GET /api/audit/{run_id}` endpoint; and the agent builder exposes a thinking-effort selector backed by the valid config enums from the builder options endpoint.

### Changed
- **Full streaming-event consumption.** The streaming executor now branches on `ThinkingPartDelta`, `FunctionToolCallEvent`, and `FunctionToolResultEvent` in addition to text deltas, persists a redacted structured event timeline to the append-only audit log, attributes reasoning tokens separately, and treats the native typed events as the source of truth over the legacy ContextVar tool-event path. Events are forwarded to the display and SSE consumers.
- **Audit schema.** `AuditRecord` gains `thinking_tokens`, a structured run-event timeline, and judge-verdict fields; the HMAC chain covers the new fields and an idempotent migration backfills existing databases (legacy rows verify and default to 0 or empty).
- **Store context managers.** `DocumentStore.__enter__` and `MemoryStoreBase.__enter__` now return `Self`, preserving the concrete store type inside `with` blocks.

### Fixed
- **Durable daemon flows no longer prune checkpoints after a failed run.** The trigger-driven flow daemon (`initrunner flow up`) pruned the checkpoint journal after any `graph.run()` that did not raise, so a run where a sub-agent returned `RunResult(success=False)` still had its checkpoints deleted. `initrunner flow resume <id>` then found zero completed services and re-ran the flow from the start, defeating resume-after-failure. The daemon now gates the prune on overall-run success (a per-run flag set false when any completed sub-agent reports `success=False`), mirroring the orchestrator's `run_once` path. Failed runs keep their checkpoints so resume replays the completed services and re-runs the failed one; fully successful runs still prune.
- **`initrunner run` now persists the structured run-event timeline.** The run-event timeline (tool calls, tool results, thinking deltas) was only built and stored when a live `on_event` consumer was wired, so every CLI `run` (buffered and streaming) wrote `event_timeline_json = NULL` to the audit database. The timeline is now reconstructed from the run's final message history whenever the run is audited, independent of any live UI consumer, reusing the existing redacted entry shapes and length bounds. Capture is gated on audit being enabled, so `--no-audit` runs add no overhead, and the live `on_event` path is unchanged.
- **`ensure_private_dir` no longer crashes on a parent directory it does not own.** Pointing `--audit-db` (or a store path) at a file inside a shared directory such as `/tmp` previously raised `PermissionError` because the helper unconditionally `chmod`ed the parent to `0o700`. It now tightens permissions only on a directory it just created or already owns, and otherwise leaves the directory untouched. Data privacy is unaffected: the audit database and store files are still locked to `0o600`.

### Dependencies
- Add `pydantic-evals` to the `observability` optional-dependencies extra.
- Wire the `local-embeddings` extra (`fastembed`) into the embedding factory.
- Bump dashboard `vite` 8.0.13 to 8.0.14 (#132).
- Bump dashboard svelte group with 2 updates (#131).

## [2026.5.4] - 2026-05-24

### Security
- Bump `idna` from 3.11 to 3.16. Closes CVE-2026-45409, an incomplete-fix bypass of the earlier CVE-2024-3651 quadratic-time DoS in `idna.encode()` (Dependabot #49).
- Bump `pydantic-ai-slim` from 1.71.0 to 1.102.0. Closes GHSA-cqp8-fcvh-x7r3 (fixed in 1.99) and GHSA-cg7w-rg45-pc59 (fixed in 1.102). Both are SSRF cloud-metadata blocklist bypasses via IPv4-mapped IPv6 and NAT64/ISATAP transition forms in URL validation (Dependabot #50).
- Bump `starlette` from 0.52.1 to 1.1.0. Closes PYSEC-2026-161.

### Changed
- **Migrate off pydantic-ai deprecations queued for v2.0.** Sweep accumulated 1.71 to 1.102 deprecations so the codebase emits zero `PydanticAIDeprecationWarning`s.
  - The `Agent(output_retries=)` kwarg is gone; we now pass a `retries={"tools": N, "output": M}` dict matching the `AgentRetries` TypedDict. The YAML-facing `execution.output_retries` field is unchanged.
  - The `Agent(history_processors=)` kwarg is gone; the token-budget history processor is appended to `capabilities` as a `ProcessHistory(fn)` instance.
  - The `Agent(prepare_tools=)` kwarg is gone; tool-search filtering is wired via `capabilities=[PrepareTools(fn)]`. The callback in `agent/tools/tool_search.py` is unchanged.
  - `FastMCPToolset` has been replaced by `pydantic_ai.mcp.MCPToolset`. The deferred-MCP wrapper picks up MCPToolset's direct `list_tools()` method (dropping the `.client.list_tools()` hop). The direct `fastmcp>=3.2.0` dependency is retained because `mcp/gateway.py`, `mcp/browser.py`, `mcp/_transport.py`, and `services/mcp_hub.py` continue to import `fastmcp.FastMCP`, `fastmcp.server.create_proxy`, and `fastmcp.client.transports.*` independently.
  - `pydantic_graph.beta.{GraphBuilder, StepContext, id_types, join}` has moved to the stable `pydantic_graph` paths. Touches `flow/graph.py` and `team/graph.py`; no call-site changes.
  - `AgentRunResult.usage()` and `StreamedResponse.usage()` (method-style, deprecated in 1.96 and 1.100 respectively) are now property access. Touches `executor.py`, `executor_output.py`, and seven test fixtures.

### Fixed
- Test `tests/test_execution_config.py::test_overrides_applied` was asserting on `agent._max_result_retries`; pydantic-ai 1.92 renamed that internal attribute to `_max_output_retries`. Fixed.

## [2026.5.3] - 2026-05-18

### Security
- Bump `urllib3` 2.6.3 to 2.7.0. Fixes decompression-bomb safeguard bypass in the streaming API and sensitive headers forwarded across origins in proxied low-level redirects (Dependabot #41, #42). (#126)
- Bump `python-multipart` 0.0.26 to 0.0.29. Fixes DoS via unbounded multipart part headers (Dependabot #40). (#126)
- Bump `authlib` 1.6.11 to 1.7.2. Fixes OIDC implicit/hybrid open redirect (Dependabot #43). Pulls in `joserfc` as a new transitive. (#126)
- Bump dashboard `svelte` 5.55.5 to 5.55.7 (svelte group). Fixes SSR XSS via insecure promise serialization in `hydratable`, XSS via DOM clobbering of internal framework state, SSR XSS via spread attributes, and ReDoS in `<svelte:element>` tag validation (Dependabot #45 through #48). Also bumps `@sveltejs/kit` 2.59.0 to 2.60.1 and `@sveltejs/vite-plugin-svelte` 7.0.0 to 7.1.2. (#125)
- Bump dashboard `devalue` 5.7.1 to 5.8.1. Fixes DoS via sparse array deserialization (Dependabot #44). (#123)

### Dependencies
- Bump dashboard `vite` 8.0.10 to 8.0.13. (#120)
- Bump dashboard `@tailwindcss/vite` 4.2.4 to 4.3.0, `tailwindcss` 4.2.4 to 4.3.0, `tailwind-merge` 3.5.0 to 3.6.0 (tailwind group). (#119)

## [2026.5.2] - 2026-05-06

### Added
- **Hardened Docker runtime support.** New `security.sandbox.docker.runtime` field accepts `runc | runsc | kata-runtime | kata-qemu | kata-fc | kata-clh`. When set, `_build_docker_cmd` emits `--runtime <name>`. Preflight verifies the runtime is registered via `docker info` (parsed defensively, never leaks raw JSON) **before** image pull, so a misconfigured runtime cannot trigger a multi-GB download on a doomed run. Per-runtime install hints surface through `SandboxUnavailableError`. New comparison doc `docs/security/sandbox-comparison.md` separates container, userspace-kernel, and microVM isolation classes; new example role `examples/roles/docker-sandbox-hardened.yaml`. (#112)

### Changed
- **Async-first executor.** The sync orchestration skeleton left over from the pydantic-graph migration is gone. `_execute_orchestrated` and the duplicated resume body now live as a single async implementation; `execute_run`, `execute_run_resume`, and `execute_run_stream` become `run_sync` wrappers. Five tool modules (`http`, `web_reader`, `web_scraper`, `search`, `image_gen`) lose their parallel `_do_X` / `_do_X_async` impls and register async-only. `ToolBuildContext.prefer_async` plumbing through `build_toolsets` and `build_agent` is removed. `executor.py`: 731 to 423 lines, net -828/+361 across 21 files. (#115)
- **`RunConfig` lives at `initrunner/run_config.py`.** Moved from `initrunner/cli/run_config.py` so `agent/loader.py` (and other non-CLI consumers like `services/setup.py` and `dashboard/routers/system.py`) no longer import from `cli/`. Seven import sites updated; no compatibility shim. (#114)
- **`_DOCKER_BLOCKED_ARGS` matches the doc.** `--runtime`, `--device`, `--volume-driver`, `--uts=host` were claimed blocked in `docs/security/docker-sandbox.md` but were not. With `--runtime` promoted to a first-class schema field, both `extra_args: [--runtime, runsc]` and `[--runtime=runsc]` are rejected at load time. (#112)

### Docs
- **"Five commands you'll actually use" callout** at the top of `docs/getting-started/cli.md`. `initrunner new` / `run` / `setup` / `doctor` / `install` with one-liners taken verbatim from each command's `--help`. The 57-row table is unchanged, just relabeled "The full surface area, when you need it." Linked from the README quickstart so newcomers land directly on it. (#113)

### Chore
- Remove stray `role.yaml` / `role2.yaml` files accidentally committed at repo root. (#109)

### Dependencies
- Bump dashboard `@sveltejs/kit` 2.58.0 to 2.59.0 (svelte group) (#110)
- Bump dashboard `bits-ui` 2.18.0 to 2.18.1 (#111)

## [2026.5.1] - 2026-05-01

### Added
- **SSH execution backend for remote tool runs.** New `backend: ssh` option for `security.sandbox` runs `shell`, `python`, and `script` tools on a remote host over OpenSSH (ControlMaster-multiplexed, auth via `~/.ssh/config` + ssh-agent). Slots into the existing `SandboxBackend` Protocol next to `bwrap`, `docker`, and `none`. SSH is remote execution, not isolation, so the schema rejects `bind_mounts`, `allowed_read_paths` / `allowed_write_paths`, and `network: bridge` at load time with explicit migration messages; `python_exec` reports the unsupported `extra_mounts` case to the model instead of crashing the run. See `docs/security/ssh-sandbox.md`.
- **Per-run token budget for one-shot CLI mode.** New `guardrails.run_token_budget` schema field and `--token-budget N` CLI flag cap cumulative token usage across a single `initrunner run` invocation. The tracker is shared via `ContextVar` so it propagates through the timeout thread-pool to delegate tools fired during the parent's model call, meaning inline-delegated sub-agents count against the parent's budget. See `docs/configuration/guardrails.md` and `docs/getting-started/cli.md`.

### Fixed
- **`initrunner new` dispatch missing `token_budget` kwarg.** The token-budget feature added a required keyword to `_run_agent` but the call site in `cli/new_cmd.py` (used after `initrunner new ... --run`) wasn't updated. Now passes `token_budget=None`.

### Dependencies
- Bump `aquasecurity/trivy-action` 0.35.0 to 0.36.0 (#104)
- Bump dashboard `@sveltejs/kit` 2.57.1 to 2.58.0 and `svelte` (#105)
- Bump dashboard `@tailwindcss/vite` 4.2.2 to 4.2.4 and `tailwindcss` (#106)
- Bump dashboard `vite` 8.0.9 to 8.0.10 (#107)

## [2026.4.18] - 2026-04-24

### Fixed
- **Docker image builds on linux/arm64 again.** The builder stage now installs `gcc` and `libc6-dev` so Python extensions that lack a prebuilt aarch64 wheel (notably `fastavro`, pulled in transitively via `pydantic-ai-slim[cohere]` to `cohere`) compile from sdist instead of failing with `gcc: No such file or directory`. No code change; PyPI wheel is byte-identical to 2026.4.17.

## [2026.4.17] - 2026-04-24

### Added
- **`spec.model.fallback`** accepts a list of `provider:model` strings (or aliases). When set, `_build_model` wraps the primary and fallbacks in pydantic-ai's `FallbackModel` so runs survive single-provider outages (5xx, 429, auth, connection resets) without call-site changes. Each entry is resolved and validated at load time; Ollama and custom-`base_url` providers are rejected in the fallback chain because aliases cannot carry a `base_url`. The executor catches `FallbackExceptionGroup` on both sync and async paths and classifies by the last inner exception, emitting an error string that lists every provider's failure. See `examples/roles/fallback-demo.yaml` and `docs/configuration/providers.md`.
- **Human-in-the-loop approval.** Mark any tool config with `approval: required` and runs pause whenever the model wants to call it, using PydanticAI's native `DeferredToolRequests` / `DeferredToolResults` contract so each runner mode resumes without re-prompting or losing message history.
  - `RunResult` gains `status` and `pending_approvals`; executor exposes `execute_run_resume` and `execute_run_resume_async`.
  - New `pending_approvals` audit table persists the message history so another process can resume.
  - REPL prompts y/N inline; single-shot exits 2 with a CLI resume hint; daemon persists and keeps serving other triggers; API returns `finish_reason: tool_calls_pending_approval` and exposes `POST /v1/approvals/{run_id}`.
  - CLI: `initrunner pending`, `initrunner approve RUN_ID [--all|--tool-call-id] [--deny]`. Docs: `docs/security/approvals.md`.
- **Dashboard approval queue.** `/approvals` queue route with keyboard navigation and bulk actions; inline `ApprovalCardGroup` in `RunPanel`; `ApprovalDrawer` for multi-call detail; `ShortcutOverlay` (`?`). Sidebar Approvals entry under Operate with a count badge (tabular-nums, polling every 20s + SSE bump). New router `routers/approvals.py` (`GET /api/approvals/pending`, `GET /api/approvals/{run_id}`, `POST /api/approvals/{run_id}`) calls `services.execution.resume_run_sync` in-process. Streaming layer fires a new `approval_required` SSE event when the executor pauses and carries `status` + `pending_approvals` in the result payload.
- **Streaming structured output.** Structured-output roles now stream progressively-validated partials via `StreamedRunResultSync.stream_output()` (the previous hard forbid on `output.type != "text"` is gone). Sync and async streaming paths accept an `on_partial` callback; the async path additionally accepts an `on_event` callback that yields typed `AgentStreamEvent` instances via `run_stream_events()`. Dashboard emits `partial_output` SSE frames for structured roles instead of falling back to non-streaming.
- **`spec.execution` block** for agent-level execution semantics (`retries`, `output_retries`, `end_strategy`, `tool_timeout_seconds`), distinct from `guardrails` budgets.
- **`spec.execution.max_concurrency`** (`{max_running, max_queued}`) wires `pydantic_ai.ConcurrencyLimit` on Agent for per-agent backpressure. `max_running` is required when the block is present.
- **`spec.deps_schema` with `{{var}}` templating.** Flat-scalar interpolation into `spec.role` and related fields, rendered through a local hook (no `pydantic-handlebars` dep). `initrunner run --var KEY=VALUE` threads values into single-shot runs. See `docs/getting-started/agent-spec-import.md`.
- **Agent Spec import/export.** `initrunner run --agent-spec <file>` imports a PydanticAI Agent Spec (JSON or YAML) as a transient role; `initrunner export agent-spec <role.yaml>` emits the reverse mapping. `retries`, `output_retries`, `end_strategy`, and `tool_timeout` round-trip through `spec.execution`.
- **Run identifiers in PydanticAI `metadata=`.** `agent.run(metadata=...)` now carries `initrunner.run_id`, `initrunner.agent_name`, and `initrunner.trigger_type` (when set) alongside the existing `input_validated` flag, so Logfire and equivalent backends surface them on PydanticAI's emitted spans without scraping InitRunner's parent span attributes.

### Changed
- **Agents now receive their static directive via PydanticAI's `instructions=` kwarg** instead of `system_prompt=`. The composed `spec.role` + skill prompts + auto-skill catalog + tool-search hint flow to `instructions=`; the two dynamic `@agent.system_prompt` decorators (procedural memory, resume context) stay as-is. Matches PydanticAI 1.71+ guidance. No role YAML change.
- **`stores/_helpers._filter_system_prompts`** rewritten. Preserves `ModelRequest.timestamp`, `run_id`, and `metadata` through filtering (previously dropped by bare `ModelRequest(parts=...)` reconstruction). Also normalizes `ModelRequest.instructions` by retaining it only on the newest two retained requests, matching PydanticAI's `_get_instructions` resolver fallback.
- **Five internal helper agents** (`eval/judge`, `agent/policies` classifier, three `services/agent_builder` wizard/import agents) migrated to `instructions=` for consistency.
- **`_validate_provider`** iterates the full model + fallback chain so a missing provider SDK fails fast at load time, not at failover time.

### Fixed
- **Race on shared run-scoped state.** `todo`, `think`, `spawn`, and `clarify` toolsets now build with `FunctionToolset(sequential=True)`. PydanticAI's default tool-execution mode is `parallel`; if the model emitted two calls to the same toolset in one turn, they could race on `ReflectionState.todo` or `SpawnPool` internals.

### Removed
- **`FlowOrchestrator.max_agent_workers`** parameter. Non-functional since the pydantic-graph async migration; no callers referenced it outside its declaration line.

## [2026.4.16] - 2026-04-18

### Breaking
- **`security.docker` config block removed.** Replaced by `security.sandbox` with `backend: auto | bwrap | docker | none` and a nested `docker` sub-config. Roles using the legacy key fail schema validation at load time with a migration error pointing at the new format. See `docs/security/sandbox.md` for the before/after.

### Added
- **Runtime sandbox with pluggable backends.** New `initrunner/agent/runtime_sandbox/` package defines a uniform `SandboxBackend` protocol with three implementations: `BwrapBackend` (Linux user namespaces, no daemon), `DockerBackend` (cross-platform containers), and `NullBackend` (no isolation; translates sandbox paths to host paths so unified tool argv still works). `shell`, `python`, and `script` tools execute through a single `backend.run(argv, stdin, env, cwd, timeout, extra_mounts, net, memory_limit, cpu_limit)` primitive instead of three separate Docker/non-Docker branches.
- **`backend: auto` with silent fallback.** Picks `bwrap` on Linux and falls through to `docker` when bwrap's functional probe fails (e.g. Ubuntu 24+ AppArmor block). Never falls to `none`. Logs the fallback at info level.
- **Adaptive preflight remediation.** When bwrap's probe fails, `SandboxUnavailableError.remediation` reads `/proc/sys/kernel/unprivileged_userns_clone` and `/proc/sys/kernel/apparmor_restrict_unprivileged_userns` and emits the specific fix -- sysctl, AppArmor profile reinstall, or switch to `backend: docker`.
- **`initrunner audit security-events` subcommand.** Queries the `security_events` audit table by `--event-type`, `--agent`, and `--limit`. Renders as a Rich table.
- **`sandbox.exec` audit event.** Every sandboxed tool call logs backend, `argv0`, returncode, and `duration_ms` to the HMAC-signed audit chain, attributed to the role's agent name.
- **Bundle sandbox metadata.** `BundleManifest.supported_sandbox_backends` declares which backends a published bundle needs. `initrunner install` warns on hosts missing a matching backend.
- **Three new docs:** `docs/security/sandbox.md` (cross-backend config reference + migration guide), `docs/security/bubblewrap.md` (bwrap-specific with the Ubuntu 24+ AppArmor fix), `docs/security/docker-sandbox.md` (Docker-specific with `extra_args` blocklist and DinD guidance).

### Changed
- **`ToolBuildContext` gains `sandbox_backend`.** Tool builders capture `ctx.sandbox_backend` in their closure and drive execution through it. Tool-internal mounts (e.g. `python_exec`'s `/work/_run.py` tempfile) pass through without validation; user-configured mounts (`allowed_read_paths`, `allowed_write_paths`, `bind_mounts`) are validated at load time.
- **`initrunner doctor --role`** now renders a sandbox row showing the resolved backend and readiness (Docker daemon reachable, bwrap probe passing, image pulled) in place of the old Docker-only row.
- **`SandboxUnavailableError` rendering.** The CLI catches this error during `build_agent` and renders a clean Rich panel with reason + remediation. Exit code 1.
- **Audit wire-up.** `create_audit_logger()` now runs before `build_agent()` in both `command_context` and `ephemeral_command_context`, and the audit logger is registered as the runtime-sandbox default so backends pick it up automatically. Backends receive the role's `agent_name` for event attribution.
- **`docs/security/security.md`, the three READMEs (en/ja/zh-CN), `docs/getting-started/docker.md`, and the CLAUDE.md docs index** rewritten to reference the new backends, prefer active voice, and drop AI puffery. The stale `WASM isolation is recommended` note was replaced with a runtime-sandbox link.

### Fixed
- **`python_exec` path mismatch inside sandboxes.** The tool was passing the host's `sys.executable` path into sandboxed subprocesses, where that path didn't exist. It now uses `python3` (PATH-resolved) inside sandboxes and `sys.executable` only on the null backend.
- **Missing audit events for sandboxed executions.** The audit logger was constructed after `build_agent`, so resolved backends had a `NullAuditLogger` when they called `log_security_event`. Fixed by introducing a module-level default audit logger that `resolve_backend` picks up lazily, and reordering CLI setup so the real logger is registered first.
- **`initrunner doctor` reference to the removed `diag.docker` field.** Now renders `SandboxDiagnosis` via `diag.sandbox`.

### Removed
- **Legacy helpers `docker_run_command`, `docker_run_python`, `docker_run_script`** from `initrunner/agent/docker_sandbox.py`. Superseded by `DockerBackend.run()`. The remaining helpers (`_build_docker_cmd`, `_generate_container_name`, `_kill_container`, `_resolve_mount_source`, `_format_oom_hint`, `ensure_image_available`) stay as implementation details of `DockerBackend`.

## [2026.4.15] - 2026-04-17

### Breaking
- **Starter slugs renamed to plain one-word names.** The bundled agent/team/flow starters now use short, human-readable names:

  | Old | New |
  |---|---|
  | `browser-agent` | `visitor` |
  | `codebase-analyst` | `reader` |
  | `code-review-team` | `reviewer` |
  | `debate-team` | `debate` |
  | `discord-assistant` | `discord` |
  | `email-agent` | `mail` |
  | `memory-assistant` | `memory` |
  | `plan-execute` | `planner` |
  | `project-monitor` | `watcher` |
  | `rag-agent` | `librarian` |
  | `telegram-assistant` | `telegram` |
  | `todo-planner` | `tasks` |
  | `web-researcher` | `scout` |
  | `ci-pipeline` | `pipeline` |
  | `content-pipeline` | `writer` |
  | `support-desk` | `triage` |

  `helpdesk` and `scholar` are unchanged. No alias layer — update scripts and bookmarks that reference old slugs.
- **Removed `deep-researcher` from the starter catalog.** The directory only contained a README; `STARTER_ORDER` referenced it but `list_starters()` silently skipped it. The broken entry is gone; `scholar` covers the same research-team use case.

### Added
- **Encrypted credential vault** -- new `initrunner vault` CLI (`init`/`set`/`get`/`list`/`rm`/`import`/`export`/`rotate`/`verify`/`cache`/`lock`/`status`) backed by Fernet + scrypt at `~/.initrunner/vault.enc`. Resolver chain checks env vars first, then the vault, so existing `api_key_env` / `token_env` / `${VAR}` placeholders keep working. Standard-provider keys resolved from the vault are injected into `os.environ` so SDK clients (OpenAI, Anthropic, Google) find them at construction. `_PASSPHRASE` added to the subprocess env scrub list so the unlock passphrase cannot leak to child processes. Optional extras: `initrunner[vault]`, `initrunner[vault-keyring]`. See `docs/security/vault.md`
- **HMAC-signed audit chain with `verify-chain` CLI** -- each audit record is HMAC-SHA256-signed over the previous record's hash, turning the SQLite log into a tamper-evident chain. Signing runs inside `BEGIN IMMEDIATE` so concurrent writers serialise through SQLite's RESERVED lock instead of forking the chain. Verification is full-chain, never auto-creates a key (a copied DB without the key fails cleanly), and treats id gaps from pruning as informational rather than breaks. See `docs/security/audit-chain.md`
- **Bidirectional Slack adapter (triggers)** -- new `SlackAdapter` implementing `ChannelAdapter` via `slack-sdk` Socket Mode (outbound WebSocket, no inbound ports). Subscribes to `app_mention` and `message.im`, threads replies off the triggering message by default, and encodes channel+thread in `channel_target` so each Slack thread gets its own `conversation_key`. The existing outbound webhook tool is unchanged. Includes schema entry, dispatcher registration, doctor/starter/role-generator integration, `initrunner[slack]` extra, and 28 new tests. See `docs/core/triggers.md`

### Dependencies
- authlib 1.6.9 -> 1.6.11 (security: CSRF in Starlette OAuth client when a `cache` is configured)
- python-multipart 0.0.22 -> 0.0.26 (security: CVE-2026-40347)

## [2026.4.14] - 2026-04-14

### Security
- **Dashboard `cookie` dep bumped from 0.6.0 to 1.1.1** -- patches GHSA advisory where malicious cookie `name`/`path`/`domain` values could inject other cookie fields. `cookie` is a transitive dep via `@sveltejs/kit`, `@sveltejs/adapter-static`, and `bits-ui`; none have bumped upstream, so we pin via `pnpm.overrides`

### Fixed
- **CI pnpm pinning** -- replaced `pnpm/action-setup@v6` with `corepack` across `security.yml`, `release.yml`, and `testpypi.yml`. The v6 action hardcodes pnpm 11 beta in its bootstrap lockfile and silently ignores both `version:` and `packageManager`, which broke every workflow that uses a pnpm 10 lockfile (`ERR_PNPM_BROKEN_LOCKFILE`). Corepack reads `packageManager` from `dashboard/package.json` directly

### Changed
- **Dashboard `packageManager` field** -- `dashboard/package.json` now pins `pnpm@10.32.1` as the canonical dev/CI version. Contributors can run `corepack enable` once to auto-pin

## [2026.4.13] - 2026-04-14

### Added
- **Docker sandbox: container cleanup on timeout** -- timed-out containers are now killed via `docker rm -f` instead of leaking. Each container gets a unique name (`initrunner-{uuid}`) and `initrunner.managed=true` label for identification
- **Docker sandbox: image pre-pull at startup** -- `ensure_image_available()` checks and pulls the configured image before the first tool call, with logging and clear error messages for private/offline images. Also reported in `initrunner doctor --deep`
- **Docker sandbox: `--user` flag** -- new `user` field (`"auto" | "<uid>:<gid>" | null`, default `"auto"`) runs containers as the current user when writable mounts exist, preventing root-owned output files
- **Docker sandbox: `--init` flag** -- tini is now always used to reap zombie processes
- **Docker sandbox: OOM detection** -- exit code 137 now appends a clear message suggesting to increase `memory_limit`
- **Docker sandbox: bind mount validation** -- missing source paths raise an error at container start instead of Docker silently creating empty root-owned directories
- **Docker CLI in published image** -- the container image now includes the Docker CLI for socket-passthrough sandbox support. Docker Compose file includes a commented socket mount with security warning
- **Multi-platform Docker image** -- CI now builds `linux/amd64` and `linux/arm64` images via QEMU

### Changed
- **Docker sandbox: script tool no longer leaks host environment** -- when Docker is enabled, only script parameter values are passed into the container. `env_passthrough` in the Docker config handles explicit host vars
- **Docker sandbox: Python tool always mounts a working directory** -- when `working_dir` is not set, a temp dir is created, mounted at `/work`, and cleaned up after execution
- **Example role `docker-sandbox.yaml` uses model auto-detection** -- removed hardcoded `provider: openai` / `name: gpt-4.1-mini`

### Fixed
- **16 `ty` type errors in `test_doctor.py` and `test_a2a.py`** -- added missing `None` guards and type-ignore annotations for external SDK types
- **CI: pnpm version 9 -> 10** -- matches local dev toolchain, fixes `ERR_PNPM_LOCKFILE_CONFIG_MISMATCH` in release/testpypi/security workflows

## [2026.4.12] - 2026-04-14

### Added
- **Security presets** -- four built-in profiles (`public`, `internal`, `sandbox`, `development`) configure content filtering, rate limits, tool restrictions, and sandbox settings in one line (`security: { preset: public }`). `--explain-profiles` flag dumps the effective tool/trigger/sandbox config for any preset
- **Extended doctor diagnostics** -- `initrunner doctor --role` now checks MCP server health, skill resolution, custom tool imports, memory store accessibility, and trigger validity. Static checks run by default; `--deep` enables active checks (MCP connectivity, full imports, DB open). New `--flow` flag validates flow topology and runs per-agent diagnostics on all referenced roles. Dashboard exposes per-agent diagnostics via `GET /api/agents/{id}/doctor`
- **Actionable error hints** -- CLI errors now include fix suggestions (e.g. "Run `initrunner setup` to configure a provider" instead of a raw traceback). Deprecation auto-fix offers to patch stale fields in-place
- **Per-tool cost attribution** -- audit trail and dashboard track USD cost per tool call, not just per run. New `ToolCostTable` dashboard component shows cost breakdown by tool type

### Fixed
- **Run flag interactions validated** -- `RunMode` enum resolves mode conflicts explicitly. `--confirm-role`/`--role-dir` without `--sense`, `--api-key` without `--serve`, and `--allowed-users` without `--bot` now produce clear error messages naming the conflicting flags

### Dependencies
- pillow 12.1.1 -> 12.2.0 (security: GZIP decompression bomb)
- pytest 9.0.2 -> 9.0.3 (security: tmpdir vulnerability)
- softprops/action-gh-release 2 -> 3
- pnpm/action-setup 5 -> 6
- svelte group update

## [2026.4.11] - 2026-04-12

### Added
- **A2A server** -- expose any agent as an A2A (agent-to-agent protocol) server via `initrunner a2a serve role.yaml`. `InitRunnerWorker` routes through the executor so audit logging, retries, budget enforcement, and output processing all work. Multi-turn context is preserved across requests via task storage. Outbound delegation uses the new `A2AInvoker` (JSON-RPC `message/send` with polling, timeout, env-based header resolution, and policy checks). Delegate tools gain `mode: "a2a"` alongside the existing `inline` and `mcp` modes. New `[a2a]` install extra (`fasta2a`, `uvicorn`, `starlette`)
- **Daemon retry policy** -- triggers can retry failed runs with exponential backoff. Configure via `spec.guardrails.retry_policy: { max_attempts: 3, backoff_seconds: 5 }`. Per-attempt usage is recorded; one audit record per trigger fire. Structured error classification (`ErrorCategory` enum) drives retry-vs-fail decisions
- **Circuit breaker** -- daemon triggers trip a circuit breaker when the provider is unhealthy. Configure via `spec.guardrails.circuit_breaker: { failure_threshold: 5, reset_timeout_seconds: 300 }`. Thread-safe state machine (closed/open/half-open) with audit events on state transitions
- **Persistent budget counters** -- daemon daily and weekly token/cost counters now survive restarts. On startup, the daemon queries the audit log for spend since the last reset boundary and restores the counters. `BudgetSnapshot` dataclass carries the serialized state
- **Real-time cost visibility** -- daemon run output now shows USD cost alongside token counts. Dashboard agent detail page includes a `BudgetProgressBar` component. SSE `usage` events carry cost for flows and teams
- **Timezone-aware budget resets** -- `budget_timezone` guardrail (default `"UTC"`) controls when daily/weekly cost counters reset. Uses `ZoneInfo` for correct DST handling

### Changed
- **README redesigned** -- opening paragraph and structure rewritten to lead with the execution story (chat -> autonomous -> daemon -> autopilot) instead of "YAML-first AI agent platform." New sections: "One file, four modes," "Agents that learn" (consolidation story), "Security is config, not plumbing" (structured around *why* each layer exists), "Cost control" (USD budgets). Removed "Why InitRunner" section and feature-count marketing copy. zh-CN and ja translations updated to match
- **`cli/run_cmd.py` split into `cli/run_cmd/` package** -- `_command.py` (main run command), `_dispatch.py` (mode dispatch), `_sensing.py` (intent sensing), `_starters.py` (starter catalog), `_validate.py` (pre-flight validation). No public API changes
- **`cli/_helpers.py` split into `cli/_helpers/` package** -- `_context.py`, `_display.py`, `_resolve.py`, `_console.py`. No public API changes
- **`dashboard/schemas.py` split into `dashboard/schemas/` package** -- per-domain modules (`agents.py`, `audit.py`, `builder.py`, `cost.py`, `flow.py`, `ingest.py`, `mcp.py`, `memory.py`, `skills.py`, `system.py`, `team.py`). Re-exports preserved in `__init__.py`

### Fixed
- **`test_flow_stream_passes_audit_logger` failed without dashboard extras** -- added `pytest.importorskip("fastapi")` guard to `TestDashboardAuditWiring`
- **`test_reply_fn_called_with_output` failed after timezone support** -- all `DaemonRunner` test mocks now set `budget_timezone = "UTC"` on guardrails
- **`tests/test_run_dispatch.py` lint failure** -- reformatted line exceeding 100-char limit

## [2026.4.10] - 2026-04-07

### Behavior changes
- **`ingest.auto: true` is now the default; auto-ingest refreshes stale indices.** Roles with an `ingest:` block now auto-index on every `initrunner run` if any source files have been added, modified, or removed since the last indexing pass. The previous behavior (auto-ingest only on the first run, opt-in via `ingest.auto: true`) is gone. To preserve the old manual workflow, set `ingest.auto: false` in the role YAML. The cheap stale check uses an mtime fast-path (heuristic; defeated by timestamp-preserving copies like `cp -p` -- run `initrunner ingest <role> --force` for an authoritative rebuild). Existing URLs are not re-fetched on auto runs to avoid per-run network traffic; new URLs added to the YAML are picked up automatically; `initrunner ingest <role>` (manual) still refreshes URL contents

### Fixed (alongside the auto-ingest default flip)
- **URLs were re-fetched on every `run_ingest` call** -- `_classify_urls` now accepts a `skip_existing_urls` flag (set by the auto-ingest path) so URLs already in the store are not re-fetched. The manual `initrunner ingest` path keeps the old refresh behavior
- **Deleting the last source file did not purge it** -- `_execute_ingest_core` now runs the purge step unconditionally when `purge_resolved_sources` is provided, even if the resolved file list is empty. Previously the early return at the top of the function bypassed `_purge_deleted` entirely, leaving orphaned chunks in the store
- **Embedding-model changes were invisible when no source files changed** -- the new `compute_stale_ingest_plan` reads the stored `embedding_model` identity in the same lock-free pass it uses for file metadata, so an `embeddings.model` swap with otherwise-unchanged sources now triggers the same `EmbeddingModelChangedError` + `--force` hint as a manual run. Legacy stores from before identity tracking are detected and self-heal on the next `initrunner run`

### Added
- **Inline API key prompt on first run** -- `initrunner run` now detects a missing provider API key and prompts for one inline (in interactive terminals only) instead of forcing a round-trip through `initrunner setup`. The key is persisted to `~/.initrunner/.env` (mode `0600`) and set in the running process so the same command continues without restarting. Non-interactive sessions (CI, piped stdin, redirected stdout) keep the original `API key not found` error and exit code 1, so scripted callers fail fast. New `MissingApiKeyError(RoleLoadError)` carries the env var and provider so the CLI catches it specifically; every existing `except RoleLoadError` site is unchanged
- **Pre-flight YAML validation on every run** -- `initrunner run`, `flow up`, and `flow install` now validate role/team/flow YAML against the schema before any skill resolution, model resolution, or API call. Errors render as a Rich panel showing per-field paths (e.g. `spec.model.provider`), 1-based line/column for syntax errors, and inline fix suggestions derived from Pydantic's stable error type API. Warning-level issues stay silent on the run path so successful runs are uncluttered
- **Recursive flow validation** -- `flow up`, `flow install`, and `flow validate` now walk every role file referenced by a flow's `spec.agents` and validate each one. Issues from a referenced role surface with `agents.<name>.` field prefixes so you can tell which referenced file is broken
- **`services/yaml_validation.py`** -- single CLI-facing entry point `validate_yaml_file(path)` that detects kind, dispatches to the right per-kind validator, and returns `(definition, kind, issues)`. Pure: never prints, never exits

### Fixed
- **Latent dashboard bug: schema errors collapsed to a single `field="schema"` issue** -- the editor's `_validate_yaml` was catching `ValueError` from `validate_role_dict` (which wraps Pydantic's `ValidationError`) and bucketing all schema errors into one issue. Now follows `__cause__` via the new `unwrap_pydantic_error` helper so per-field issues reach both the dashboard editor and the CLI panel. Fix applies to role, team, and flow validators
- **`initrunner validate` matched the old plain-text error format** -- now produces the same Rich panel as the run pre-flight, with severity labels, field paths, and fix hints. The success-table path is unchanged
- **PyYAML mark line/column was 0-based on display** -- syntax errors now show 1-based line/column matching editor and traceback conventions

### Changed
- **`detect_yaml_kind` moved from `cli/_helpers.py` to `services/yaml_validation.py`** -- the CLI helper is now a thin wrapper that catches `InvalidComposeKindError` and converts to a printed exit. Backward-compatible re-export preserved
- **Flow validation moved from `dashboard/validation.py` to `services/flow_validation.py`** -- the dashboard module is now a 4-line shim that converts service `ValidationIssue` to the API's `ValidationIssueResponse`. Routers untouched

## [2026.4.9] - 2026-04-07

### Fixed
- **`init new` ignores saved provider config** -- now respects `run.yaml` via the canonical precedence (`INITRUNNER_MODEL` > `run.yaml` > env auto-detect > fallback). Previously picked Anthropic if `ANTHROPIC_API_KEY` existed, even with a stale key
- **Custom endpoints broken in CLI builder** -- `base_url` and `api_key_env` from `run.yaml` are now threaded through the builder and injected into generated YAML, fixing OpenRouter and other custom-endpoint setups
- **401 errors show raw tracebacks** -- authentication failures now print actionable guidance (`initrunner setup` or `--provider`) instead of a PydanticAI stack trace
- **Missing SDK shows `pip` instructions** -- provider SDK check now runs early in `init new` with `uv`-friendly install message
- **Builder emits empty optional sections** -- `memory: {}`, `ingest: {}`, etc. when asked to add features. Schema reference now includes field-level details for all optional sections (memory, ingest, reasoning, autonomy, security, observability)
- **Builder confuses RAG with memory** -- prompt now distinguishes RAG (`ingest` with `sources`) from memory (cross-session agent state) and guides the LLM accordingly
- **Broad exception catch skips refinement** -- narrowed seed-phase error handler to `ModelHTTPError` only, fixing a regression where any exception silently exited before the refinement loop
- **Budget daily reset test timezone bug** -- test used `date.today()` (local time) but tracker uses UTC; fails when local date is ahead of UTC

### Changed
- **`rewrite_model_block` extracted to shared module** -- moved from `dashboard/routers/builder.py` to `services/agent_builder.py` for reuse by CLI builder

## [2026.4.8] - 2026-04-06

### Added
- **Cost tracking and budget enforcement** -- per-run USD cost estimation using `genai-prices`, `max_cost_usd` budget guardrail that halts runs exceeding threshold, cost column in audit records
- **Cost analytics page** -- dedicated `/cost` dashboard page with sortable tables for per-agent, per-model, and per-day cost breakdowns
- **Unified bottom panel with cost** -- agent, flow, and team run views share one bottom panel showing token counts, cost, and tool activity
- **Usage SSE event for flow/team streams** -- `usage` event emitted on stream completion with token counts and cost, matching the agent stream contract
- **Real-time tool event visibility for flows and teams** -- tool call start/complete events streamed via SSE for flow and team runs, not just standalone agents

### Fixed
- **Tool activity sidebar layout** -- flow and team panels now use CSS grid with bounded max-height to prevent overflow

## [2026.4.7] - 2026-04-05

### Added
- **Live tool activity panel** -- agent Run tab now shows a split view with real-time tool call events streamed via SSE alongside token output. Each tool call shows start/complete lifecycle with status dots, tool names, durations, and error summaries. Exception-safe: a start event always gets a matching complete event, even if the tool raises
- **Token/cost meter** -- horizontal bar below the tool activity panel showing budget frame before streaming, exact token counts and USD cost estimate (via genai-prices) on completion. Budget progress bar when guardrails set a token limit
- **Timeline view** -- Gantt-style chart on a new Timeline tab showing runs over the last 24 hours. Available on agents (with triggers), flows, and teams. Swim lanes dynamically assigned from overlap detection, bars color-coded by outcome, hover tooltips with trigger type/duration/tokens/cost. Stats strip with run count, success rate, and total cost. Auto-refreshes every 30s. Cost derived per-row from stored audit model/provider (hidden for multi-model flows/teams). New endpoints: `GET /api/agents/{id}/timeline`, `GET /api/flows/{id}/timeline`, `GET /api/teams/{id}/timeline`
- **Quick-run drawer** -- Play button on agent list rows and flow canvas nodes opens a slide-over drawer for running agents without leaving the list page
- **Cost estimation** (`initrunner/dashboard/pricing.py`) -- uses PydanticAI's `RequestUsage` with `genai-prices.calc_price()` for per-run cost estimation across 10 providers

## [2026.4.6] - 2026-04-05

### Added
- **Deferred MCP tool loading** -- `defer: true` on MCP tool config defers server connections until first tool call, serving cached schemas in the meantime. Schema cache in `~/.initrunner/cache/mcp/` with atomic writes, drift detection, and auto-warnings. Dashboard shows deferred badges and cache age with cache invalidation endpoint

### Changed
- **Unified sync-to-async bridge** -- replaced 8 scattered `asyncio.run()`/`anyio.run()` call sites with the single `run_sync()` helper backed by `anyio.run()`. Safe inside compose/daemon mode (detects running event loops, offloads to worker threads). `anyio>=4` added as explicit dependency
- **Decomposed oversized functions** -- split `build_flow_graph()` (197->15 lines), `build_agent()` (172->40 lines), and `_execute_ingest_core()` (185->45 lines) into focused helpers with explicit data flow via frozen dataclasses
- **Extracted SSE pump and shared AST helpers** -- common SSE heartbeat/drain/error logic consolidated into `_sse_pump()` async generator. 5 duplicated AST helpers moved to `services/_sidecar_common.py`

### Fixed
- **PDF resource leak** -- `pymupdf` document wrapped in `try/finally` so `doc.close()` runs even when page/metadata access raises
- **Delegation response parsing** -- response JSON and structure validated before accessing nested keys; specific error messages instead of misleading "Failed to reach agent"
- **Spawn timeout hang** -- `await_any` uses deadline + `concurrent.futures.wait`; returns `None` immediately for unknown task IDs instead of looping forever
- **Trigger send race** -- Telegram/Discord `send()` gated on `threading.Event` set only when bot is fully operational, closing the race where `send()` hit a half-initialized loop

## [2026.4.5] - 2026-04-04

### Added
- **MCP Hub dashboard page** (`/mcp`) -- visual management center for MCP servers with four tabs: Servers (aggregated view with health dots, lazy tool introspection), Discover (curated registry of 12 popular MCP servers with YAML copy), Playground (execute any tool in isolation with auto-generated forms and history), Canvas (@xyflow topology of server-agent relationships). Sidebar health badge polls every 30s, Launchpad shows MCP health widget
- **MCP Hub backend** -- server aggregation service with identity hashing and deduplication, health checks with 30s TTL cache, single-tool playground execution. 6 API endpoints under `/api/mcp/`. Sandbox enforcement (command allowlist, env scrubbing) flows through all operations
- **Browser agent starter** -- `browser-agent.yaml` template with `initrunner-browser-mcp` and `@modelcontextprotocol/server-filesystem` MCP servers, giving new users a working MCP setup out of the box
- **Browser MCP auto-sandbox workaround** -- `initrunner-browser-mcp` auto-retries with `--no-sandbox` when Chrome fails due to AppArmor/unprivileged user namespace restrictions (Ubuntu 23.10+, containers, VMs)

### Changed
- **Compose renamed to Flow** -- `kind: Compose` is now `kind: Flow`, `services:` is now `agents:`, `depends_on:` is now `needs:`. Old compose files get a clear error with exact field renames. 131 files changed across schema, CLI, dashboard, docs, and tests
- **Dashboard visual redesign** (Electric Charcoal v2) -- deeper surface scale, desaturated accent tokens, sans-serif section labels, left-edge nav indicators, unified metrics strips, HeaderBar with breadcrumbs and Cmd+K trigger, ternary border-radius system (0px/2px/pill). Removed: noise grain, glow effects, lime top-edge card borders, monospace section labels, pill-shaped CTAs
- **Dashboard screenshot updated** for v2 redesign
- **Example role versions bumped** for flow rename republish

## [2026.4.4] - 2026-04-03

### Added
- **`--autopilot` flag** -- daemon mode where every trigger runs the full autonomous loop instead of single-shot. Messaging triggers (Telegram, Discord) now support multi-step reasoning with all existing guardrails (spin guard, token budget, iteration limits, finish_task). Individual triggers can opt in via `autonomous: true` without enabling it globally

### Changed
- **README restructured** -- security section promoted after autonomy, "Why InitRunner" replaces comparison grid, humanized section headers, docs table split for scannability. Chinese and Japanese translations synced with the revamped English version

## [2026.4.3] - 2026-04-02

### Added
- **Autonomous execution in README** -- new "Autonomous execution" subsection in "What You Get", comparison table row, `-a` flag in modes list. Applied to English, Chinese, and Japanese READMEs
- **Chinese and Japanese READMEs** -- full translations at `README.zh-CN.md` and `README.ja.md` with language selector in the header and maintenance note in CONTRIBUTING.md
- **Compose/team runs in dashboard Launchpad** -- one-shot compose and team runs now log a top-level aggregate audit row (`trigger_type: compose_run` / `team_run`) so they appear in the Launchpad recent activity feed. Dashboard stream routes now wire `audit_logger`. Backend `exclude_trigger_types` filter hides internal compose/delegate/team rows from Launchpad while keeping them in the full audit view
- **Compose run correlation** -- `compose_run_id` propagated through `ComposeGraphDeps` into child service `trigger_metadata` for parent-child linking
- **Dimension-specific reflexion** -- `reflection_dimensions` config with per-dimension evaluation rubrics and structured scoring. Dashboard CognitionPanel and ConfigPanel updated
- **Budget-aware continuation prompts** -- autonomous continuation prompts now surface remaining iteration/token/time budget so the agent can plan accordingly
- **Explicit finalize_plan() tool** -- replaces the plan-execute phase heuristic; agent calls `finalize_plan()` to transition from planning to execution. New `plan-execute` and `todo-planner` starters

### Changed
- **Launchpad redesigned** -- Electric Charcoal design system applied to the dashboard home page

### Fixed
- **MCP gateway migrated to fastmcp 3.x** -- replaced deprecated `.filtered()`, `.prefixed()`, and `FastMCP.as_proxy()` with Visibility transforms and `create_proxy`. Fixes CVE-2025-64340, CVE-2026-27124, CVE-2026-32871. Version floor set to `fastmcp>=3.2.0`
- Type errors and formatting issues across audit, compose, team, and test modules

### Dependencies
- anthropic 0.86.0 -> 0.87.0
- aiohttp 3.13.3 -> 3.13.4

## [2026.4.2] - 2026-04-01

### Added
- **PydanticAI agent import** -- `initrunner new --pydantic-ai <file>` converts PydanticAI scripts to role.yaml via CLI or dashboard. AST extraction of `Agent()` model config, `system_prompt`/`instructions`, `@agent.tool`/`@agent.tool_plain`/`FunctionToolset` tools, `output_type` (including `NativeOutput`/`ToolOutput`/`PromptedOutput` unwrapping), `ModelSettings`, `UsageLimits`. Sidecar module with `RunContext` parameter stripping and body-reference TODO insertion. Warns on `pydantic_graph`, `logfire`, MCP servers, `builtin_tools`, `@agent.output_validator`
- **Dashboard Import mode redesign** -- single "Import" card with pill toggle for LangChain/PydanticAI framework selection. Separate source buffers per framework
- **Dashboard structured output fallback** -- SSE streaming auto-falls back to non-streaming execution for `output.type: json_schema` roles instead of crashing
- **Shared sidecar validation** -- `_sidecar_common.py` extracts blocked-module validation used by both LangChain and PydanticAI importers
- **PydanticAI import documentation** -- `docs/getting-started/pydanticai-import.md` with real before/after example

### Fixed
- **Provider auto-detection crashes on missing SDK** -- `detect_provider_and_model()` and `list_available_providers()` now skip providers whose Python SDK is not installed, falling through to the next available provider
- **Async tool RunContext stripping** -- regex patterns now handle `async def` functions
- **Dashboard starter override** -- manual mode selection clears `pendingStarter` so `?starter=` URL params don't override user choice

## [2026.4.1] - 2026-04-01

### Added
- **LangChain agent import** -- convert LangChain Python agents to InitRunner role.yaml via CLI (`initrunner new --langchain <file>`) or dashboard ("Import" mode card). AST-based extraction of model config, system prompt, `@tool` functions, known tool class mapping, structured output, and guardrails, with LLM normalization to produce minimal valid YAML
- **Sidecar tool module generation** -- custom `@tool` functions are extracted into a sibling Python module with decorator stripped, non-LangChain imports preserved, and sandbox import validation. Module name derived from YAML filename with hyphens sanitized to underscores
- **Import warnings** -- unsupported LangChain features (LCEL pipelines, LangGraph, memory, retrievers, callbacks, human-in-the-loop) produce explicit warnings with actionable InitRunner alternatives. Surfaced in CLI output and dashboard editor
- **Model selector hint** -- dashboard builder shows context-sensitive hint below the "Model" heading explaining what the model selection does
- **LangChain import documentation** -- migration guide at `docs/getting-started/langchain-import.md` covering CLI, dashboard, tool mapping, warnings, and scope

### Fixed
- Rich markup swallowing `[extra]` brackets in `MissingExtraError` messages -- `initrunner desktop` showed `uv pip install initrunner` instead of `uv pip install initrunner[desktop]`. Same fix applied to bot SDK checks in `_ephemeral.py`

## [2026.3.9] - 2026-03-31

### Changed
- **Split executor.py** -- extracted `executor_auth.py`, `executor_models.py`, `executor_output.py`, and `executor_retry.py` from the 478-line executor module into focused submodules
- **Split schema/tools.py** -- converted the 557-line tool config module into `initrunner/agent/schema/tools/` package with domain-grouped submodules (`_base`, `_comms`, `_exec`, `_integration`, `_io`, `_media`, `_reasoning`, `_web`). API surface regression test added
- **Split registry.py** -- converted the 789-line role registry module into `initrunner/registry/` package with focused submodules (`_exceptions`, `_types`, `_manifest`, `_overrides`, `_resolve`, `_preview`, `_install`, `_manage`, `_update`). All existing imports preserved via `__init__.py` re-exports. Pinned 25-name API surface regression test added
- **Clean up team/compose orchestration** -- extracted `team/prompts.py`, `team/results.py`, `team/roles.py`, `team/runtime.py` from the 445-line team runner. Expanded `team/stores.py` for shared state management
- **Centralized provider detection** -- moved `PROVIDER_KEY_ENVS_DICT` to `providers.py` as the canonical dict form. Migrated all 12 consumers from the `loader.py` re-export chain to direct `providers.py` imports. `ALL_PROVIDERS` in `setup.py` derived from canonical source with a drift-catching assertion
- **Consolidated optional dependency handling** -- added `MissingExtraError`, `require_extra()`, and `is_extra_available()` to `_compat.py`. Migrated 12 ad-hoc `try/except ImportError` blocks across 8 files to use the new helpers with consistent error messages. Deduplicated HTML processing in `_html.py`

### Fixed
- `test_run_format_json_no_footer` mock leaked into content validation and JSON serialization
- `require_provider` tests failed when optional extras (boto3, groq) were installed

### Dependencies
- Bump pygments 2.19.2 to 2.20.0

## [2026.3.8] - 2026-03-30

### Added
- **Debate strategy for teams** -- multi-round concurrent argumentation with configurable rounds and synthesis. Three personas argue from different angles, refine positions across rounds, and a final synthesis consolidates the outcome. Dashboard visualizes the debate pipeline with round nodes, persona cards, and synthesis step
- **Debate team starter** -- `debate-team` starter pack with optimist/skeptic/pragmatist personas, available from the launchpad and teams tab
- **Starters across all builders** -- starter packs now work in agent, team, and compose builders through a unified `mode: "starter"` seed flow. Team and compose zero states show relevant starter cards. StarterCard routes to the correct builder based on kind
- **Embedding warning banner** -- agent builder editor warns when the generated YAML needs embeddings but the effective provider is unusable. Shows selectable provider chips (openai/google/ollama) with inline key configuration or one-click provider switching via `POST /api/builder/set-embedding-provider`
- **Clustered avatars for teams** -- debate rounds show clustered spinning avatar spheres for all concurrent personas instead of a single avatar. Compose runs show a pipeline stepper with spinning service avatars replacing the static avatar row
- **Team detail tabs** -- memory and ingest tabs on the team detail page

### Changed
- **Pydantic-graph execution** -- compose and team runners now use pydantic-graph for orchestration instead of thread-per-service. Fan-out, routing, and delegation run as graph steps with native async agent execution
- **Dashboard session security** -- session cookie stores an HMAC-derived token instead of the raw API key. `secure` flag set automatically when behind HTTPS. Unhandled exception handler returns generic "Internal server error" instead of leaking `str(exc)`

### Fixed
- Debate avatar flashing between rounds
- Fan-out terminal join and routing transform in compose graphs
- Compose stream awaits and team pipeline visual alignment

## [2026.3.7] - 2026-03-30

### Changed
- Replace mascot with new InitRunner logo in README (light/dark theme support)
- Add logo and favicon to dashboard sidebar

## [2026.3.6] - 2026-03-29

### Changed
- **Embedded policy engine** -- replaced Cerbos PDP sidecar with embedded [initguard](https://github.com/initrunner/initguard) policy engine. No sidecar container, no network round-trips, sub-millisecond evaluation. `INITRUNNER_POLICY_DIR` replaces five `INITRUNNER_CERBOS_*` env vars. `initguard` is now a core dependency (no `authz` extra). Policy loading fails fast when configured
- **PolicyToolset** -- renamed `CerbosToolset` to `PolicyToolset`. Deny messages now include `decision.reason` and `decision.advice` from the policy engine

### Removed
- `docker-compose.cerbos.yml` -- no sidecar needed
- `authz` optional extra -- initguard ships with core install
- All `INITRUNNER_CERBOS_*` environment variables

### Fixed
- Dashboard test collection failures when `fastapi` extra not installed
- Desktop test (`test_worker_failure`) mock triggering fastapi import

## [2026.3.5] - 2026-03-29

### Added
- **Model auto-detection** -- the `model:` section in role and team YAML is now optional. When omitted, the provider and model are auto-detected from (in priority order): `INITRUNNER_MODEL` env var, `run.yaml` from `initrunner setup`, or API key env vars. Roles can keep a partial `model:` block with only tuning fields (temperature, max_tokens) and the provider/name are filled in at runtime. All 73 bundled starters no longer hardcode `openai:gpt-5-mini` -- they work with whatever provider the user configured
- **`PartialModelConfig` schema type** -- new YAML-facing model config with optional provider/name. Runtime `ModelConfig` stays concrete. `resolve_role_model()` central helper converts partial to concrete before any execution, ingestion, or provider check
- **Dashboard default model setting** -- new "Default Model" section on the System page. Pick provider/model from the browser, saves to `run.yaml`. Shows provenance (env var, run.yaml, auto-detected). Reset button returns to auto-detect. Preset names (OpenRouter) are normalized to canonical runtime fields before saving
- **Auto-detect badge on agent cards** -- agents without a pinned model show a subtle `auto` pill badge in card, list, and flow canvas views instead of "no model"

### Fixed
- **Docker command drift** -- Docker docs, Dockerfile, compose files, and cloud deploy configs all referenced stale CLI commands (`chat`, `serve`, `ui`) that were removed in v1.45. Updated to use the current surface: `run` (with `--serve`, `-i`, `--bot`), `dashboard`, and `ingest`
- **Container default CMD** -- Dockerfile now launches the dashboard (`dashboard --expose --no-open`) instead of printing `--help` and exiting. `docker compose up` immediately starts a useful service
- **Dashboard port exposure** -- Dockerfile exposes port 8100 (dashboard default) alongside 8000 (API server). Compose files standardized to 8100
- **`INITRUNNER_DASHBOARD_API_KEY` env var** -- the env var was referenced in docker-compose.cerbos.yml and render.yaml but had no effect. `--api-key` now reads `INITRUNNER_DASHBOARD_API_KEY` when the flag is omitted (explicit `--api-key` still wins)
- **Stale deploy configs** -- `render.yaml` and `deploy/fly.toml` updated from dead `ui`/`--help` commands to `dashboard --expose --no-open`
- **Helpdesk starter comment** -- usage comment updated from `initrunner serve` to `initrunner run --serve`

## [2026.3.3] - 2026-03-28

### Added
- **Sense routing in compose builder** -- Route pattern now exposes routing strategy (Broadcast / Keyword / Sense) as inline controls in the dashboard compose builder. Variable service count (3-10) with semantic specialist names (researcher, responder, escalator, analyst, etc.). Collapsible scoring detail shows tag/name/description weights and per-slot quality indicators. Events tab gains a Routing column showing method and score for each delegation event
- **Tool search in Cognition panel** -- Tool search is now configurable in the dashboard agent creation wizard via the Cognition panel. Function-name picker (resolved from `tool_func_map` in builder options), auto-pins common functions on first enable, collapsible tuning section. Always visible in the panel (previously gated behind 10+ tools). Info banner appears for agents with 10+ tools suggesting enablement
- **Tool search in agent detail** -- `tool_search` exposed in agent detail API response and Config tab. Agent cards and flow nodes show a cyan `search` badge when tool search is enabled. `tool_search` added to the `features` property on `AgentSpec`
- **Cognition panel tooltips** -- Every section in the Cognition panel (Pattern, Autonomy, Think, Todo, Tool Search, Guardrails) now has descriptive tooltips. Individual pattern buttons show what each reasoning strategy does
- **README Intelligence section** -- New top-level section showcasing reasoning patterns, sense routing, and tool search with concrete YAML examples and dashboard references

### Changed
- **Route pattern flexible topology** -- Route pattern is no longer fixed at 4 services. Supports 3-10 services with semantic specialist names from a curated pool. Defaults to 3 (intake + researcher + responder). `routing_strategy` parameter added to `build_compose()` and `ComposeSeedRequest`
- **Pattern card descriptions** -- Updated compose builder pattern descriptions: chain -> "Linear A -> B -> C pipeline", fan-out -> "Dispatch to all workers simultaneously", route -> "Route to the best specialist automatically" with lime `sense` badge
- **README hero trimmed** -- Hero command block reduced from 7 to 3 examples to avoid duplication with the starter table below

### Fixed
- **Autonomy arrow UX** -- Autonomy section in Cognition panel no longer shows a misleading expand arrow when disabled. When unchecked, displays as a flat label + checkbox (matching Think/Todo pattern). Arrow appears only when enabled and sub-settings are expandable
- **CognitionPanel toolFuncMap prop** -- `toolFuncMap` prop was declared in the type signature but not destructured in `EditorScreen.svelte`, causing the variable to be unbound. Added default value `{}` in the destructuring

## [2026.3.2] - 2026-03-28

### Added
- **Dashboard API key auth** -- `--api-key` flag protects the dashboard with a login page and cookie-based session. Supports header, cookie, and form-based authentication

### Fixed
- **Memory template canonicalization** -- `canonicalize_role_yaml()` no longer drops explicitly present optional spec sections (`memory`, `autonomy`, `reasoning`, `observability`) when all sub-fields match defaults. Agents created from the memory template now correctly retain their `memory:` config and get memory tools wired at runtime
- **Memory tab auto-refresh** -- dashboard memory tab now refreshes automatically when a run completes, matching the existing history tab behavior
- **Dashboard type narrowing** -- fixed `ty` type errors for `hmac.compare_digest` and `set_cookie` calls in dashboard auth flow

## [2026.3.1] - 2026-03-27

### Changed
- **CalVer versioning** -- switched from SemVer (1.x.y) to CalVer (YYYY.M.PATCH). Version numbers now reflect release date, not feature cadence. PATCH resets each month. Prereleases use PEP 440 suffixes (rc, a, b, dev). v1.46.0 is the final SemVer release.

## [1.46.0] - 2026-03-27

### Added
- **ChannelAdapter protocol** -- `ChannelAdapter` ABC unifies inbound and outbound messaging for Telegram and Discord with `channel_target` per-conversation routing
- **`doctor --fix` auto-repair** -- auto-installs missing pip extras, offers API key setup, repairs config, bumps spec_version with surgical text edits. `--fix --yes` for non-interactive CI
- **`validate --explain`** -- prints plain-language explanations of each role config section (role, model, tools, memory, autonomy, triggers, sinks, output, security) without LLM calls
- **Rich progress bars** -- auto-ingest and autonomous runs show real-time progress with spinners and file/chunk counts
- **4 new starters** -- `rag-agent` (document Q&A), `email-agent` (inbox monitoring + triage), `ci-pipeline` (webhook receiver + build analyzer + Slack notifier), `support-desk` (sense-routed intake/researcher/responder/escalator)
- **Source code extraction** -- ingestion handles 25+ file extensions (.py, .js, .ts, .go, .rs, etc.) with shared SKIP_DIRS filtering
- **DiceBear avatars** -- deterministic identity avatars (Rings style) in dashboard conversation threads with spinning indicator during streaming
- **Auto-detect provider in setup** -- setup wizard detects provider from existing API key environment variables
- **No-arg CLI menu** -- `initrunner` with no arguments shows an interactive menu of common starters
- **OpenRouter preset** -- preset provider configuration for OpenRouter
- **Post-command suggestions** -- CLI prints 2-3 copy-paste next-steps after successful commands, actionable error hints with `Hint:` lines (suppressed in non-TTY/JSON)
- **Orchestration Patterns guide** -- comprehensive documentation with decision tree, YAML examples, and competitive comparison

### Changed
- **Non-destructive spec_version bump** -- replaces YAML round-trip with regex-based in-place editing that preserves comments, block scalars, and flow-style lists

## [1.45.1] - 2026-03-27

### Changed
- **Streamlined setup wizard** -- setup now configures provider, API key, and model only. Role/tool/intent configuration moved to the dashboard, which is offered at the end of setup
- **Starters use configured provider** -- `initrunner run helpdesk -i` and other starters pick up the provider/model from `run.yaml` instead of hardcoding openai
- **Better setup UX** -- provider list with descriptions and cloud/local grouping, numeric input for provider and intent, condensed security notice, step progress indicator `[1/3]...[3/3]`
- **Model descriptions** -- model selection shows capability tier (Frontier/Balanced/Lightweight) instead of vague labels

### Fixed
- **`examples copy` shows correct next-steps** -- multi-file examples now reference the primary role file in next-steps commands, not the first file alphabetically

## [1.45.0] - 2026-03-27

### Added
- **Unified `run` command** -- `chat` merged into `run` as ephemeral mode. `run` with no args starts an ephemeral REPL; `--list` shows starter agents. New flags: `--provider`, `--tool-profile`, `--tools`, `--memory`, `--ingest`, `--save`
- **Starter agents** -- `helpdesk`, `code-review-team`, `memory-assistant`, `web-researcher` ship built-in. Prerequisite checks auto-detect provider/model and guide setup. `--save` copies a starter locally for customization
- **`[recommended]` extras bundle** -- `pip install "initrunner[recommended]"` installs dashboard, common providers, and ingestion. Install script defaults to `[recommended]`
- **Dashboard prompt after setup** -- `initrunner setup` offers to open the dashboard in your browser after configuration. Shown when dashboard extras are installed and stdin is a TTY
- **Choosing Features guide** -- new `docs/getting-started/choosing-features.md` maps goals to YAML config fields

### Removed
- **`chat` command** -- merged into `run`. Running `initrunner chat` shows a migration message

### Changed
- `install.sh` defaults to `initrunner[recommended]` instead of bare `initrunner`
- Setup wizard `run.yaml` renamed from `chat_config` to `run_config`
- Dashboard builder uses starter service layer instead of inline templates

## [1.44.0] - 2026-03-26

### Added
- **Clarify tool** -- agent-initiated `clarify()` asks the user a question mid-run and blocks until answered. Works in REPL, bot, daemon, and autonomous modes. Add `{ type: clarify }` to your role's tools list.
- **Context budget guard** -- PydanticAI history processor that truncates oversized parts and drops oldest message pairs when estimated tokens exceed the budget. Runs as a pre-request history processor and between autonomous/daemon iterations.
- **`model.context_window` field** -- explicit context window override in `spec.model`; auto-detected per provider when omitted (200k Anthropic, 128k OpenAI/Gemini, etc.)
- **Dashboard trigger visibility panel** -- agent detail page shows trigger configuration, fire counts, and next-run times
- **Dashboard toast notification system** -- global toast store with auto-dismiss; load-error recovery across all pages
- **Dashboard agent wizard refactor** -- creation wizard extracted into composable screen components (ConfigureScreen, EditorScreen, HubSearchPanel, SuccessScreen)
- **Dashboard skills management** -- browse, search, create, and edit skills from the dashboard. Path-based skill discovery, scope badges, requirement indicators, config panel, and editor tab. Full CRUD API via `/api/skills/` endpoints.
- **Skill service layer** -- `SkillService` with path-based discovery, SKILL.md parsing, validation, and CRUD operations (`initrunner/services/skill_service.py`)
- **Agent skills sidebar** -- agent config panel shows attached skills with scope and requirement badges
- **Trigger stats API** -- `GET /api/agents/{name}/trigger-stats` endpoint with fire counts and schedule info
- **Context-aware-scraper example** -- autonomous web scraper demonstrating the context budget guard with history summarization
- **Clarify-researcher example** -- research assistant demonstrating human-in-the-loop clarify tool before acting

### Removed
- **`kind: Pipeline` orchestration** -- removed in favor of Team for one-shot multi-agent workflows and Compose for long-running services. For complex DAG workflows, use pydantic-graph directly. Running a Pipeline YAML now shows a migration message.
- **`--var` flag** from `initrunner run` (was Pipeline-only)
- Pipeline executor, schema, loader, and tests (`initrunner/pipeline/`)

### Changed
- **Compose scaffold pattern renamed** -- `--pattern pipeline` is now `--pattern chain`. Default for `initrunner compose new` updated accordingly.
- Dashboard compose UI no longer labels runs or deletions as "pipeline"

## [1.43.0] - 2026-03-25

### Added
- **PydanticAI capabilities in role YAML** -- `spec.capabilities` accepts native NamedSpec entries (Thinking, WebSearch, WebFetch, ImageGeneration, MCP) with bare-string, single-value-dict, or kwargs-dict syntax
- **InputGuardCapability** -- content policy enforcement via `security.content_policy`; blocks harmful/off-topic prompts before they reach the model
- **Capability/tool conflict validation** -- rejects configs declaring both a capability and its equivalent tool (WebSearch+search, WebFetch+web_reader, ImageGeneration+image_gen)
- **WebFetch local fallback** -- auto-injects SSRF-protected URL fetcher as local implementation
- **OpenAI Responses API auto-switch** -- OpenAI provider uses `openai-responses:` prefix for builtin capability support
- **Tool call limit headroom** -- builtin capabilities increase `tool_calls_limit` by 20
- **Dashboard provider warnings** -- agent detail shows banner when provider SDK missing or API key not set
- **Dashboard SSE error handling** -- `stream_run_sse` catches build failures; client detects premature close
- **Dashboard capabilities UI** -- capability filter chip, config panel section, glyph badges
- **YAML canonicalizer** -- `canonicalize_role_yaml()` serializes to minimal YAML, omitting defaults

### Changed
- Builder system prompt refined with capability vs tool guidance
- Builder tool summary delegates to shared `role_generator.build_tool_summary()`
- PydanticAI bumped from >=1.70.0 to >=1.71.0
- Dashboard fastapi imports annotated with `# type: ignore[import-not-found]` for ty compatibility

### Removed
- Custom pack-local capability loading (`capabilities/loader.py`, `CustomCapabilityConfig`)
- `custom-capability-demo` example

## [1.42.0] - 2026-03-25

### Added
- **Dashboard provider setup** -- configure API keys directly from the dashboard. Inline key entry form on the launchpad zero-state, agent creation page, and System page.
- **Provider management (System page)** -- full-mode provider banner shows configured providers with status dots and an "Add provider" form. Replaces the static table.
- **`GET /api/providers/status`** -- all providers (standard + OpenRouter + Ollama) with config flags and detected provider/model.
- **`POST /api/providers/save-key`** -- save keys for standard providers and OpenRouter. Optional key validation for OpenAI/Anthropic.
- **CLI dashboard hint** -- "Setup Required" panel mentions `initrunner dashboard` as alternative.

### Changed
- `save-key` moved from `/api/builder/` to `/api/providers/`. All builder callers updated.
- Provider status includes OpenRouter alongside standard providers.
- Error messages use `uv pip install` instead of `pip install`.
- Starter template model names updated.

### Infra
- Dashboard upgraded to Vite 8, lucide-svelte 1.0.
- CI actions bumped to latest.

## [1.41.0] - 2026-03-25

### Added
- **Dashboard onboarding** -- redesigned zero-state launchpad with provider status banner, starter template cards (helpdesk, rag-agent, memory-assistant, telegram, discord, email), capability chips, and quickstart links
- **Starter templates API** -- `GET /api/builder/starters` returns curated Agent starters with derived feature labels
- **Starter seed mode** -- `POST /api/builder/seed` accepts `mode: "starter"` to load and customize starter YAMLs
- **Provider status** -- `BuilderOptionsResponse` includes `provider_status` with per-provider configuration state
- **`?starter=` URL param** -- `/agents/new?starter={slug}` auto-loads starter into editor when a provider is detected
- **Provider warning** -- agent creation shows setup links when no providers are configured

### Changed
- Zero-state condition checks agents, composes, and teams (not just agents)
- "Run Doctor" replaced with "Read the Quickstart" on zero-state launchpad

### Fixed
- CI: updated trivy-action to v0.35.0 (0.28.0 tag no longer resolvable)
- CI: pip-audit ignores CVE-2025-69872 (diskcache) and CVE-2026-4539 (pygments) pending upstream fixes

### Security
- Bumped security dependencies (uv.lock refresh)

## [1.40.4] - 2026-03-25

### Fixed
- Dashboard returns 404 after install from PyPI -- static assets were excluded from wheel due to gitignore. Added hatch `artifacts` config and dashboard build step to CI

## [1.40.3] - 2026-03-25

## [1.40.2] - 2026-03-25

## [1.40.1] - 2026-03-25

## [1.40.0] - 2026-03-25

### Removed
- **Textual TUI** (`initrunner/tui/`) -- k9s-style terminal UI with screens for roles, runs, audit, memory, daemon, ingest. Removed `tui` optional dependency
- **Jinja2/HTMX web dashboard** (`initrunner/api/`) -- server-rendered HTML dashboard with DaisyUI, HTMX, templates, static assets, FaceHash avatars, chat UI

### Added
- **SvelteKit + FastAPI dashboard** -- complete rewrite from scratch. SvelteKit TypeScript frontend with Tailwind CSS, ShadcN Svelte components, and 12 FastAPI backend routers. Pages for agents, compose, teams, audit, system, and builder wizards
- **"Electric Charcoal" design system** -- dark-only mission control aesthetic with OKLCH color system, Space Grotesk / IBM Plex Mono typography, lime accent (#c8ff00), and binary border radius pattern
- **Desktop command** (`initrunner desktop`) -- launches dashboard in a native pywebview window (1280x800) with embedded FastAPI backend, health polling, GTK/WebKit detection on Linux. New `desktop` optional extra
- **SvelteFlow canvas view** -- agents page with draggable node graph, auto-categorization (Reactive, Intelligence, Connected, Skilled, Cognitive, Equipped), auto-layout, localStorage position persistence, minimap, search with `/` shortcut, and capability filters (tools, triggers, ingest, memory, sinks, skills, reasoning, autonomy). Auto-switches to list view on mobile
- **Compose visual editor** -- SvelteFlow graph for compose pipelines with service nodes, visual connections, and pattern templates (pipeline, fan-out, route). Tabbed detail view with YAML editor, events stream, and config panel
- **Team builder** -- structured persona configuration with SvelteFlow pipeline visualization, run panel with streaming output, shared `AgentPicker` component for compose and team builders
- **Agent builder** -- multi-turn LLM-powered wizard for drafting and refining agent roles via dashboard
- **Dashboard ingestion management** -- `IngestTab` with document lifecycle: upload files, add URLs, re-ingest with SSE progress streaming, per-document delete. Summary cards showing document count, chunk count, last ingested timestamp
- **Ingestion manifest system** (`initrunner/ingestion/manifest.py`) -- persistent tracking of dashboard-added sources in document store metadata. Managed sources survive re-ingestion (not purged by glob resolution) and survive store wipes (saved before wipe, restored after)
- **Ingestion service layer** (`initrunner/services/ingestion.py`) and REST API (`/api/agents/{id}/ingest/*`) -- endpoints for document listing, summary, upload, URL addition, re-ingestion (SSE), and deletion
- **Delete endpoints** -- `DELETE /api/agents/{id}`, `DELETE /api/teams/{id}`, `DELETE /api/compose/{id}` with cache eviction. New `ConfirmDeleteDialog` component with type-to-confirm pattern
- **ModelCombobox component** -- enhanced model selector with search filtering, keyboard navigation (arrows, Enter, Escape), custom model entry mode, and provider-specific presets
- **`list_all_file_metadata()`** on `FileMetadataStore` and LanceDB implementation -- returns source, hash, modified, ingested_at, chunk_count for document listing
- **Embedding provider health checks** -- system doctor page and `/api/system/doctor` report embedding provider API key status alongside model providers
- **Centralized deprecation system** (`initrunner/deprecations.py`) -- registry of deprecation rules (DEP001-DEP005) with `spec_version` field, auto-migration callbacks, severity levels, and `validate_role_dict()` enforcement. Doctor command validates spec version and deprecations
- **Dashboard validation module** (`initrunner/dashboard/validation.py`) -- shared compose YAML validation with structured error reporting
- **Dashboard caching layer** -- `RoleCache`, `ComposeCache`, `TeamCache` with factory pattern dependency injection and `evict()` for deletion support
- **Bundled starter examples** -- 9 curated examples (helpdesk, email-agent, rag-agent, memory-assistant, telegram, discord, code-review team, support-desk compose, ci-pipeline compose) shipped with the package and visible in the dashboard on fresh installs
- **Zero ty type checking errors** -- resolved all 73 pre-existing diagnostics across source and test files
- 200+ new tests across dashboard routers, deprecation system, doctor command, ingestion manifest, managed pipeline, safe_substitute, ingestion service, store metadata

### Changed
- **CLI refactored** -- split 952-line `run_cmd.py` into mode-specific modules: `_run_agent.py` (single-shot/REPL/daemon), `_run_pipeline.py` (compose), `_run_team.py` (team mode)
- **Ingestion pipeline refactored** -- extracted `_execute_ingest_core()` shared between `run_ingest()` (glob-based with purge) and `run_ingest_managed()` (explicit files/URLs, no purge)
- **`safe_substitute()` extracted to `initrunner/_text.py`** -- replaces `str.format()` in triggers (Discord, Telegram, file watcher) and API tool to prevent template injection
- **Model lists updated to March 2026** -- GPT-5.4, GPT-5-mini, GPT-5-nano, o4-mini, o3, Claude Sonnet 4.6, Claude Opus 4.6, Claude Haiku 4.5, Gemini 2.5 Flash/Pro/Flash-Lite, Grok 4, Llama 4 Scout, Devstral, Command-A, Qwen 2.5
- **Agent builder accepts `name` parameter** -- `SeedRequest` schema gains required `name` field, auto-generates filename from name
- **`DoctorResponse` schema** gains `embedding_checks` field
- **Providers endpoint** includes custom presets (OpenRouter etc.) when their API key env var is set
- **README** -- new "User Interfaces" section with dashboard and desktop command documentation, updated screenshot
- **`dashboard` optional extra** updated from Jinja2/HTMX stack to FastAPI + uvicorn for API-only backend

## [1.39.2] - 2026-03-23

## [1.39.1] - 2026-03-23

### Changed
- Switched from MIT-only to dual license (MIT OR Apache-2.0)
- Adopted PEP 639 license metadata (`license-files`, removed Trove classifier, hatchling>=1.27)
- Removed root LICENSE pointer file so GitHub detects both licenses correctly

## [1.39.0] - 2026-03-23

### Changed
- Migrated 6 legacy tool modules from `agent/` to `agent/tools/` (git, python, sql, shell, slack, api) -- now auto-discovered via `pkgutil`, removed hardcoded `_LEGACY_TOOL_MODULES` list (renamed to `_EXTERNAL_TOOL_MODULES` with only `mcp/server` remaining)
- Broke up 335-line `run()` god-function in `cli/run_cmd.py` into 5 focused helpers: `_validate_flags`, `_resolve_via_sensing`, `_resolve_output_format`, `_build_user_prompt`, `_run_agent`
- Completed services layer enforcement: `server/app.py`, `cli/run_cmd.py`, `cli/doctor_cmd.py`, `tui/screens/daemon.py` now route execution through `services/execution.py` instead of importing `agent.executor` directly
- Extended `services/execution.py` wrappers with `skip_input_validation`, `trigger_type`, `trigger_metadata`, `model_override` parameters
- `cli/_helpers.py:load_and_build_or_exit` delegates to `services.execution.build_agent_sync`

### Added
- `tests/test_authz.py` -- 47 unit tests for Cerbos authorization module (config parsing, env vars, ContextVars, SDK mocking, health checks)
- `tests/test_middleware.py` -- 44 unit tests for security middleware (predicates, auth dispatch, rate limiting, body size, HTTPS enforcement, security headers)

### Fixed
- `ty check` errors in `test_middleware.py` (Response body type) and `test_reasoning_strategies.py` (UserPrompt type narrowing, AgentSpec kwargs)

## [1.38.0] - 2026-03-22

### Added
- **Reasoning primitives** -- structured agent cognition with three tool types and four execution strategies
  - **Think tool** (enhanced) -- accumulated reasoning chain with ring buffer and optional self-critique every 5th thought. Config: `critique`, `max_thoughts`
  - **Todo tool** -- priority-aware task management (critical/high/medium/low) with dependency resolution via Kahn's algorithm, batch creation, auto-completion when all items terminal. Config: `max_items`, `shared`, `shared_path`
  - **Spawn tool** -- non-blocking parallel agent execution. Private asyncio event loop in daemon thread, `spawn_agent`/`poll_tasks`/`await_tasks`/`await_any`/`cancel_task`. Config: `agents`, `max_concurrent`, `timeout_seconds`
- **Reasoning strategies** (`spec.reasoning`) -- execution-layer orchestration across autonomous turns
  - `react` (default): standard ReAct, no extra orchestration
  - `todo_driven`: plan-first with auto-plan prompt prefix, todo-oriented continuation
  - `plan_execute`: two-phase (planning then execution) with automatic phase transition
  - `reflexion`: post-completion self-critique rounds (`reflection_rounds: 1-3`)
  - Conservative auto-detection: infers pattern from tool/autonomy config
- **Run-scoped tool architecture** -- `@register_tool(..., run_scoped=True)` for tools with per-run state. Registry skips them at agent build time; runners build fresh per-run
- **Loader validation** -- `todo_driven`/`plan_execute` without todo tool, `reflexion` with `reflection_rounds == 0` caught at load time
- **Wizard schema reference** -- `initrunner new` generates roles with `spec.reasoning`, `spec.autonomy`, and `spec.autonomy.compaction` when users describe autonomous or planning agents
- **6 example packs** published to InitHub: `reasoning-planner`, `research-team`, `self-correcting-writer`, `long-running-analyst` (v2), `deployment-checker` (v2), `thinker` (v2)
- **Multi-agent decision guide** (`docs/orchestration/multi-agent-guide.md`) -- task-driven chooser for team vs pipeline vs compose vs spawn vs delegate
- **Reasoning primitives docs** (`docs/core/reasoning.md`) -- full guide with config tables, YAML examples, composition patterns
- 85+ new tests across 7 test files

### Changed
- `ReflectionState` rewritten: `PlanStep`/`steps` removed, replaced with `TodoList` component (composition)
- `build_reflection_toolset` removed (absorbed by todo tool + `finish_task` in runner)
- Think tool now always accumulates (old "Thought recorded." behavior removed)
- `ThinkToolConfig` gains `critique: bool` and `max_thoughts: int`
- Autonomous runner delegates prompt construction and completion detection to `ReasoningStrategy`
- Single-shot runner injects run-scoped toolsets via `extra_toolsets`
- `build_toolsets()` skips `is_run_scoped()` tools automatically
- Example roles converted from single-file to pack directories with READMEs

### Removed
- `PlanStep` dataclass
- `update_plan` tool
- `initrunner/agent/tools/reflection.py`

## [1.37.0] - 2026-03-21

### Added
- **`initrunner configure` command** -- switch the LLM provider/model for any role without editing YAML. Interactive mode shows available providers and model picker; non-interactive via `--provider`/`--model` flags. `--reset` reverts to original
- **Post-install provider adaptation** -- after `initrunner install`, detects if the user lacks the role's required API key and offers one-step adaptation to a configured provider. Lists all available providers. Non-interactive (`--yes`) auto-adapts
- **Registry override layer** -- provider overrides stored in `registry.json` alongside installed role metadata. Overrides survive hub updates, reinstalls, and `--force` re-installs. Installed YAML stays pristine
- **Provider compatibility checking** -- `check_role_provider_compatibility()` inspects LLM provider key, effective embedding provider (respects `ingest.embeddings` and `memory.embeddings` overrides, falls back to defaults from `ingestion/embeddings.py`)
- `list_available_providers()` returns all providers the user has API keys for, not just the first match
- 28 new tests across `test_registry_overrides.py`, `test_providers_compat.py`, `test_configure_cmd.py`

### Changed
- PydanticAI minimum version bumped to 1.70.0
- `_update_role_yaml` preserves `base_url` and `api_key_env` when the provider stays the same (fixes OpenRouter model switching)
- Loader applies registry overrides before building agent (`--model` CLI override takes higher priority)

## [1.36.0] - 2026-03-21

### Added
- **Calculator tool** -- safe AST-based math expression evaluator with trig, log, and utility functions. No `eval()`. Configurable expression length and complexity limits
- **Image generation tool** -- dual-provider support (OpenAI DALL-E 3, Stability AI). `generate_image()` and `edit_image()` tools with async/sync variants
- **PDF extraction tool** -- `extract_pdf_text()` (markdown output) and `extract_pdf_metadata()` with page range selection, path sandboxing, and size limits
- **Browser MCP server** -- FastMCP wrapper around `agent-browser` CLI with 12 tools (navigate, click, fill, screenshot, etc.), SSRF protection, domain filtering. Console script: `initrunner-browser-mcp`
- **4 new example roles**: `creative-studio` (image generation), `math-assistant` (calculator), `pdf-analyst` (document analysis), `web-researcher` (browser-based research)
- Skill design documentation: methodology-only vs tool-providing skill patterns
- 1,287 lines of new test coverage across 4 test files

### Changed
- Tool schema union updated with `CalculatorToolConfig`, `PdfExtractToolConfig`, `ImageGenToolConfig`
- `docs/agents/tools.md` and `docs/agents/tool_creation.md` updated with new tool references

## [1.35.1] - 2026-03-21

## [1.35.0] - 2026-03-21

### Added
- **Tool event observability** -- `ObservableToolset` wraps all toolsets with ContextVar-based callbacks that emit `ToolEvent` (tool name, status, error summary, duration). Zero overhead when no callback is set. Error detection identifies common failure patterns (HTTP errors, SSRF blocks, timeouts, non-zero exits). Live tool status displayed during single-shot, autonomous, and daemon runs
- **Compose project scaffolding** -- `initrunner compose new <name>` generates a complete multi-agent project with role files and `compose.yaml`. Three patterns: `pipeline` (linear chain, configurable service count), `fan-out` (dispatcher + parallel workers), `route` (intake with sense-based routing to researcher/responder/escalator). Options: `--pattern`, `--services`, `--shared-memory`, `--provider`, `--model`
- **Output format control** -- `--format` flag on `run` with four modes: `auto` (stream on TTY, plain text when piped), `json` (structured envelope with token counts and timing), `text` (stdout-only, stats to stderr), `rich` (buffered Markdown panel). Replaces `--no-stream` (now deprecated and hidden)
- `--list-templates` flag on `initrunner new` shows available role templates (basic, rag, daemon, memory, ollama, api, telegram, discord)
- `--list-patterns` flag on `initrunner compose new` shows available composition patterns
- Improved `--help` across CLI: `plugins` command shows docs link and install pattern, `chat` shows tip about `initrunner new` for custom tools
- 40+ new tests: tool events, compose scaffolding (pipeline/fan-out/route), plugin listing, output format dispatch

### Changed
- All toolsets wrapped with `ObservableToolset` as outermost layer (after permission checks)
- `chat` command help updated to reference `run <role> -i` for role-backed chat
- Test assertions updated to account for `ObservableToolset` wrapper layer

## [1.34.0] - 2026-03-21

### Changed
- **Unified `run` command**: `run` now auto-detects YAML kind (Agent, Team, Compose, Pipeline) and dispatches accordingly. One command replaces `daemon`, `serve`, and `pipeline`
- `run` gains `--daemon`, `--serve`, `--bot`, `--var`, `--host`, `--port`, `--api-key`, `--cors-origin`, `--allowed-users`, `--allowed-user-ids` flags with grouped help panels
- `chat` is now ephemeral-only (no role-file argument); use `run <role>` for role-backed execution
- Trigger hint shown when entering REPL for roles with configured triggers

### Added
- `runner/bot.py`: dedicated bot runner that starts Telegram/Discord event loops directly without going through DaemonRunner
- `runner/_conversations.py`: extracted `ConversationStore` for shared use between daemon and bot runners
- `resolve_run_target()` in CLI helpers for unified target resolution with kind detection
- 21 new tests for dispatch, kind/mode validation, mutual exclusivity, and old command removal

### Removed
- `initrunner daemon` top-level command (use `initrunner run <role> --daemon`)
- `initrunner serve` top-level command (use `initrunner run <role> --serve`)
- `initrunner pipeline` top-level command (use `initrunner run <file>` with Pipeline YAML)
- `initrunner chat <role>` mode (use `initrunner run <role>`)

## [1.33.2] - 2026-03-19

### Added
- **New example roles**: `api-monitor`, `email-agent`, `integration-tester`, `security-scanner`, `slack-digest`, `unit-tester` (each with `role.yaml`, `README.md`, and optional `skills/`)
- **Upgraded to directory format**: `discord-assistant`, `telegram-assistant` (were single `.yaml` files, now directories with READMEs)
- **New compose example**: `examples/compose/test-pipeline/` -- multi-agent test pipeline with change-detector, unit-runner, and integration-runner
- **New team config**: `examples/teams/test-review.yaml`
- **Updated examples catalog** (`initrunner/_examples_catalog.json`)

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
- **BREAKING: Rename `timeout` to `timeout_seconds`** on `McpToolConfig`, `ApiEndpoint`, `ToolkitWebReaderConfig`, `ToolkitHttpConfig` — aligns with all other tool configs
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
- **`prefer_async` tool build flag**: `ToolBuildContext.prefer_async` propagates through `build_agent to build_toolsets to tool builders`, letting I/O-bound tools register async closures
- **Async tool variants**: `http`, `web_reader`, `web_scraper` (concurrent embeddings via `asyncio.gather`), and `search` tools provide native async closures when `prefer_async=True`
- **Async signal handler**: `install_async_shutdown_handler()` in `_signal.py` with double-Ctrl-C force-exit pattern for asyncio event loops
- **Queue bridge pattern**: sync `queue.Queue` to `asyncio.Queue` bridge inside `ComposeService` preserves `DelegateSink` sync contract while enabling async service loops
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
- **OCI authentication**: `initrunner login` command with credential resolution chain (env vars to oci-auth.json to Docker config base64 auth)
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
- **Store factory helpers** (`stores/factory.py`): `managed_memory_store()` context manager for full memory store lifecycle (create to register to yield to unregister to close)
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
- Default `StoreBackend` enum value: `SQLITE_VEC` to `ZVEC` across all config schemas (IngestConfig, MemoryConfig, SharedMemoryConfig, StoreConfig)
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
- Provider auto-detection service (`services/providers.py`) — priority-ordered key detection (Anthropic to OpenAI to Google to Groq to Mistral to Cohere to Ollama)
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
  `max_tool_calls` bumped from 10 to 15, `timeout_seconds` bumped from 60 to 120

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
- **ux:** `setup` "Next steps" panel restructured into three sections (Create your agent / Or run the scaffold / Interfaces); examples discovery (`examples list` to `examples copy` to `run`) replaces the broken `init --template rag` hint

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
- update memory tools section in `docs/agents/tools.md` (3 to 5 tools)
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