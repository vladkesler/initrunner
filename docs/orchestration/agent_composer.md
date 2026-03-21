# Agent Composer — Multi-Agent Orchestration

Agent Composer lets you define multiple agents as services in a single `compose.yaml` file, wire them together with delegate sinks, and run them all with one command. Each service runs as an asyncio task on a shared event loop, with agent executions dispatched to a thread pool. Delegate sinks route output from one service to another via in-memory queues.

## Quick Start

Create a minimal two-service compose file where a producer delegates its output to a consumer:

```yaml
# compose.yaml
apiVersion: initrunner/v1
kind: Compose
metadata:
  name: my-pipeline
  description: Simple producer-consumer pipeline
spec:
  services:
    producer:
      role: roles/producer.yaml
      sink:
        type: delegate
        target: consumer
    consumer:
      role: roles/consumer.yaml
      depends_on:
        - producer
```

Validate the definition:

```bash
initrunner compose validate compose.yaml
```

Start the orchestration (foreground, Ctrl+C to stop):

```bash
initrunner compose up compose.yaml
```

## Compose Definition

The top-level structure follows the same `apiVersion`/`kind`/`metadata`/`spec` pattern as role definitions.

```yaml
apiVersion: initrunner/v1      # required
kind: Compose                   # required, must be "Compose"
metadata:
  name: my-pipeline             # required
  description: A pipeline       # optional
spec:
  services:                     # required, at least one service
    service-a:
      role: roles/a.yaml
      # ... service config
    service-b:
      role: roles/b.yaml
      # ... service config
  shared_memory:                # optional
    enabled: false
    store_path: null
    max_memories: 1000
    store_backend: lancedb
  shared_documents:             # optional
    enabled: false
    store_path: null
    store_backend: lancedb
    embeddings:
      provider: ""
      model: ""
```

### Top-Level Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `apiVersion` | `str` | *(required)* | API version string (e.g. `initrunner/v1`). |
| `kind` | `"Compose"` | *(required)* | Must be `Compose`. |
| `metadata.name` | `str` | *(required)* | Name of the compose definition. |
| `metadata.description` | `str` | `""` | Human-readable description. |
| `spec.services` | `dict[str, ServiceConfig]` | *(required)* | Map of service name to configuration. Must contain at least one service. |
| `spec.shared_memory` | `SharedMemoryConfig` | disabled | Shared memory configuration across services. |
| `spec.shared_memory.enabled` | `bool` | `false` | Enable shared memory across all services. |
| `spec.shared_memory.store_path` | `str \| null` | `null` | Path to the shared memory store. Default: `~/.initrunner/memory/{name}-shared.lance`. |
| `spec.shared_memory.max_memories` | `int` | `1000` | Maximum number of memories in the shared store. |
| `spec.shared_memory.store_backend` | `str` | `"lancedb"` | Store backend. Uses LanceDB, an in-process vector database. |
| `spec.shared_documents` | `SharedDocumentsConfig` | disabled | Shared document store configuration across services. See [Shared Documents](#shared-documents). |
| `spec.shared_documents.enabled` | `bool` | `false` | Enable a shared document store across all services. |
| `spec.shared_documents.store_path` | `str \| null` | `null` | Path to the shared document store. Default: `~/.initrunner/stores/{name}-shared.lance`. |
| `spec.shared_documents.store_backend` | `str` | `"lancedb"` | Store backend. |
| `spec.shared_documents.embeddings.provider` | `str` | *(required when enabled)* | Embedding provider. Must be set explicitly when `enabled: true`. |
| `spec.shared_documents.embeddings.model` | `str` | *(required when enabled)* | Embedding model. Must be set explicitly when `enabled: true`. |

## Service Configuration

Each entry in `spec.services` configures one agent service.

```yaml
services:
  my-service:
    role: roles/my-role.yaml        # required
    trigger: null                   # optional, override trigger config
    sink:                           # optional, delegate sink config
      type: delegate
      target: other-service
    depends_on:                     # optional, startup ordering
      - dependency-service
    health_check:                   # optional
      interval_seconds: 30
      timeout_seconds: 10
      retries: 3
    restart:                        # optional
      condition: none
      max_retries: 3
      delay_seconds: 5
    environment: {}                 # optional, extra env vars
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `role` | `str` | *(required)* | Path to the role YAML file, relative to the compose file. |
| `trigger` | `dict \| null` | `null` | Override trigger configuration (reserved). |
| `sink` | `DelegateSinkConfig \| null` | `null` | Delegate sink for routing output to other services. |
| `depends_on` | `list[str]` | `[]` | Services that must start before this one. |
| `health_check` | `HealthCheckConfig` | *(see below)* | Health check parameters. |
| `restart` | `RestartPolicy` | *(see below)* | Restart policy for the service. |
| `environment` | `dict[str, str]` | `{}` | Additional environment variables for the service. |

## Delegate Sink

Delegate sinks route a service's output to one or more other services. The upstream service's agent output becomes the downstream service's input prompt. Routing is done via in-memory queues with blocking backpressure.

```yaml
sink:
  type: delegate
  target: consumer              # single target
  keep_existing_sinks: false
  queue_size: 100
  timeout_seconds: 60
  # circuit_breaker_threshold: 5       # optional: open after 5 consecutive failures
  # circuit_breaker_reset_seconds: 60  # optional: probe after 60s in open state
```

Or with multiple targets:

```yaml
sink:
  type: delegate
  target:                       # fan-out to multiple targets
    - researcher
    - responder
  keep_existing_sinks: true     # also fire role-level sinks
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `"delegate"` | *(required)* | Must be `delegate`. |
| `target` | `str \| list[str]` | *(required)* | Target service name(s) to route output to. |
| `strategy` | `"all" \| "keyword" \| "sense"` | `"all"` | Routing strategy for multi-target delegates. See [Routing Strategy](#routing-strategy). |
| `keep_existing_sinks` | `bool` | `false` | When `true`, the service's role-level sinks (webhook, file, custom) are also activated alongside the delegate. When `false`, only the delegate sink is used. |
| `queue_size` | `int` | `100` | Maximum number of events buffered in the target's inbox queue. |
| `timeout_seconds` | `int` | `60` | How long to block when the target queue is full before dropping the message. |
| `circuit_breaker_threshold` | `int \| null` | `null` | Number of consecutive delivery failures (drops + errors) before the circuit opens and rejects all messages. `null` disables the circuit breaker. |
| `circuit_breaker_reset_seconds` | `int` | `60` | Seconds to wait in open state before allowing a single probe message through (half-open). If the probe succeeds, the circuit closes; if it fails, it re-opens. |

### Routing Strategy

When a delegate sink has multiple targets, the `strategy` field controls how messages are routed.

| Strategy | Behavior | API calls |
|----------|----------|-----------|
| `all` | Fan-out — every target receives every message (default, backward compatible) | None |
| `keyword` | [Intent Sensing](../core/intent_sensing.md) keyword scoring picks the best target | None |
| `sense` | Keyword scoring first; LLM tiebreaker when ambiguous | 0 or 1 per message |

The `keyword` and `sense` strategies use the same two-pass [Intent Sensing](../core/intent_sensing.md) logic used by `--sense` in the CLI. They score the agent's output text against each target service's `metadata.name`, `metadata.description`, and `metadata.tags` from its role definition.

**Before (static fan-out):** every message goes to ALL targets:

```yaml
triager:
  role: roles/triager.yaml
  sink:
    type: delegate
    target: [researcher, responder, escalator]
```

**After (sense picks the right target):**

```yaml
triager:
  role: roles/triager.yaml
  sink:
    type: delegate
    strategy: sense              # ← one line added
    target: [researcher, responder, escalator]
```

#### How routing works

1. The upstream agent's output is scored against each target's role metadata (name, description, tags) using keyword matching.
2. If the output doesn't produce a confident match, the original user prompt (preserved from the head of the delegation chain) is also scored.
3. For `sense` strategy, if both attempts are inconclusive, an LLM tiebreaker call selects the best target.
4. The message is forwarded to the selected target only (not fanned out).

Routing diagnostics are injected into the payload's trigger metadata as `_compose_route_reason` for audit visibility.

#### Optimizing roles for routing

The same tips from [Intent Sensing — Optimizing Roles](../core/intent_sensing.md#optimizing-roles-for-sensing) apply. Each target service's role should have specific, non-overlapping tags and a clear description:

```yaml
# roles/researcher.yaml
metadata:
  name: researcher
  description: Researches topics in depth and gathers supporting evidence
  tags: [research, analysis, investigation, evidence]

# roles/responder.yaml
metadata:
  name: responder
  description: Responds directly to user queries with concise answers
  tags: [response, chat, answer, reply]

# roles/escalator.yaml
metadata:
  name: escalator
  description: Escalates complex issues to human operators
  tags: [escalation, support, human, complex]
```

#### Single target behavior

When only one target is specified, `strategy` has no effect — the message always goes to that target regardless of the strategy setting.

### Backpressure Behavior

Delegate sinks use `queue.Queue` with blocking puts. When the downstream service is processing slowly and its inbox fills up:

1. The upstream service blocks on `queue.put()` for up to `timeout_seconds`.
2. If the queue is still full after the timeout, the message is dropped with a warning to stderr.
3. The upstream service continues operating — a dropped delegate message never crashes the sender.

### Role Sink Interaction

By default, when a compose `sink:` is configured, the service's role-level sinks (from `spec.sinks` in the role YAML) are **not** activated. This prevents duplicate output routing.

Set `keep_existing_sinks: true` to activate both the delegate sink and the role's own sinks. This is useful when you want to both forward output to another service and log it to a file or webhook.

When no compose `sink:` is configured at all, the service uses its role-level sinks as if running in standalone daemon mode.

### Failed Runs

Only successful runs are forwarded via delegate sinks. If an agent run fails (`success: false`), the delegate sink silently skips the event. This prevents error messages from cascading through the pipeline.

### Circuit Breaker

When `circuit_breaker_threshold` is set, the delegate sink tracks consecutive delivery failures (drops and errors — `filtered` events don't count) and transitions through three states:

```
CLOSED ──(N consecutive failures)──> OPEN ──(reset timer expires)──> HALF_OPEN
  ^                                                                      │
  └──────────(probe succeeds)──────────────────────────────────────────────┘
                                      OPEN <──(probe fails)──────────────┘
```

- **Closed** (default): messages are delivered normally. The failure counter resets on each successful delivery.
- **Open**: all messages are immediately rejected with `circuit_open` audit status. No delivery is attempted. After `circuit_breaker_reset_seconds` elapses, the circuit moves to half-open.
- **Half-open**: a single probe message is allowed through. If it succeeds, the circuit closes and the failure counter resets. If it fails, the circuit re-opens for another reset interval.

The circuit breaker is disabled by default (`circuit_breaker_threshold: null`).

## Startup Order

Services start in topological order based on `depends_on` declarations. Services without dependencies start first, forming "tiers" of parallel startup.

### Example

Given this configuration:

```yaml
services:
  inbox-watcher:
    role: roles/inbox-watcher.yaml
    sink:
      type: delegate
      target: triager
  triager:
    role: roles/triager.yaml
    depends_on: [inbox-watcher]
    sink:
      type: delegate
      target: [researcher, responder]
  researcher:
    role: roles/researcher.yaml
    depends_on: [triager]
  responder:
    role: roles/responder.yaml
    depends_on: [triager]
```

The startup order is:

```
Tier 0:  inbox-watcher          (no dependencies)
Tier 1:  triager                (depends on inbox-watcher)
Tier 2:  researcher, responder  (both depend on triager)
```

Services within the same tier start concurrently. Shutdown happens in reverse topological order.

## Restart Policies

The `restart` block controls what happens when a service thread exits unexpectedly.

```yaml
restart:
  condition: on-failure
  max_retries: 3
  delay_seconds: 5
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `condition` | `"none"` \| `"on-failure"` \| `"always"` | `"none"` | When to restart. `none` = never, `on-failure` = only if the service recorded errors, `always` = restart regardless of exit reason. |
| `max_retries` | `int` | `3` | Maximum number of restart attempts. Once exceeded, the service stays down. |
| `delay_seconds` | `int` | `5` | Seconds to wait before restarting the service. |

### Restart Conditions

| Condition | Restart when... |
|-----------|----------------|
| `none` | Never restart. The service stays down if its thread exits. |
| `on-failure` | Restart only if the service has recorded at least one error (`error_count > 0`). |
| `always` | Restart whenever the service thread is no longer alive, regardless of exit reason. |

### Health Monitor

When any service has a non-`none` restart policy, a health monitor starts automatically. In compose mode, it runs as an asyncio task on the shared event loop; in standalone mode, it runs as a thread. It checks every 10 seconds whether each service is alive and applies the restart policy:

1. Skip services with `condition: none`.
2. For `on-failure`, skip if `error_count == 0`.
3. If `max_retries` has been reached, log a warning and stop attempting restarts.
4. Otherwise, wait `delay_seconds`, then restart the service.

## Health Checks

Health check configuration is available per-service but is reserved for future use. The health monitor currently checks thread liveness rather than application-level health.

```yaml
health_check:
  interval_seconds: 30
  timeout_seconds: 10
  retries: 3
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `interval_seconds` | `int` | `30` | Seconds between health checks. |
| `timeout_seconds` | `int` | `10` | Timeout for each health check. |
| `retries` | `int` | `3` | Number of consecutive failures before marking unhealthy. |

## Role Compatibility

Compose services are standard InitRunner roles. All role features carry over:

- **Triggers**: A service's role-level triggers (cron, file_watch, webhook) fire normally. The inbox-watcher example uses a cron trigger to poll for new emails.
- **Sinks**: Role-level sinks activate when no compose `sink:` is set, or when `keep_existing_sinks: true`. See [Sinks](sinks.md).
- **Tools**: All configured tools (built-in, custom, MCP) are available to the agent. See [Tools](../agents/tools.md).
- **Memory**: Memory-enabled roles persist and recall memories as usual. Session pruning runs after each trigger execution, matching standalone daemon behavior. Use `spec.shared_memory` to give all services a common memory store — see [Shared Memory](#shared-memory). See [Memory](../core/memory.md).
- **Documents**: Use `spec.shared_documents` to give all services a common document store with compose-owned embedding config — see [Shared Documents](#shared-documents). See [Ingestion](../core/ingestion.md).
- **Guardrails**: Timeout, token limits, and tool call limits from the role definition apply to each execution.
- **Skills**: Skills referenced in the role definition are loaded and available.

Services without a compose `sink:` behave identically to running the role with `initrunner run <role> --daemon` -- triggers fire, sinks dispatch, and memory persists as configured.

## Runtime Architecture

### Async Event Loop

The compose orchestrator runs a shared asyncio event loop in a dedicated daemon thread. Each service runs as an asyncio task on this loop, while agent executions (LLM calls) are dispatched to a `ThreadPoolExecutor`. This design enables efficient orchestration (queue polling, health checks, signal handling) without blocking on I/O.

```
Main thread (sync CLI)
  │
  └── Daemon thread: asyncio event loop
        ├── Task: service-a (_service_run_async)
        ├── Task: service-b (_service_run_async)
        ├── Task: health monitor
        └── ThreadPoolExecutor (agent runs)
```

The sync façade is preserved — `ComposeOrchestrator.start()`, `stop()`, and `run_compose()` remain sync methods. The async loop is an internal implementation detail.

### Async Tool Execution

Compose services build agents with `prefer_async=True`, which gives I/O-bound tools (HTTP, web scraper, search) async closures. When the agent runs via PydanticAI's async `agent.run()`, these tools execute natively on the event loop without thread-pool overhead. Sync tools are auto-wrapped by PydanticAI.

For async executor details, see `execute_run_async()` and `execute_run_stream_async()` in `agent/executor.py`.

### Queue Bridge

Delegate sinks use sync `queue.Queue` for compatibility. Each service runs an internal bridge coroutine that drains the sync queue into an `asyncio.Queue`:

```
DelegateSink.send()  →  queue.Queue.put()  →  _inbox_bridge()  →  asyncio.Queue  →  _service_run_async()
     (sync)                (sync)              (async bridge)        (async)            (async)
```

This keeps `DelegateSink` fully sync while letting the service loop use `await` on the async side.

### Shutdown Semantics

Shutdown follows a structured sequence:

1. First Ctrl+C (or SIGTERM) sets the stop event — services stop accepting new inbox events.
2. Each service waits for any in-flight agent run to complete (grace period, default 30s).
3. After the grace period, a warning is logged and the service detaches from the in-flight run.
4. Service tasks are cancelled on the shared loop.
5. The event loop thread joins.
6. The `ThreadPoolExecutor` shuts down with `wait=True` to let in-flight runs complete naturally.
7. Delegate sinks flush their audit threads.

A second Ctrl+C force-exits immediately via `os._exit(1)`.

### Executor Pool Sizing

The thread pool for agent runs is configurable via `max_agent_workers` on `ComposeOrchestrator`. Default: `min(32, len(services) + 4)`. This pool is separate from the global `_TIMEOUT_POOL` used by standalone `execute_run()` calls.

## Shared Memory

When `spec.shared_memory.enabled` is `true`, all services in the compose orchestration share a single memory database. Any service can call `remember()` to store information and any other service can `recall()` it — enabling cross-service knowledge sharing without delegate sinks.

### Configuration

```yaml
spec:
  shared_memory:
    enabled: true
    store_path: ./shared-memory.lance   # optional, default: ~/.initrunner/memory/{name}-shared.lance
    max_memories: 500                # optional, default: 1000
  services:
    researcher:
      role: roles/researcher.yaml
    writer:
      role: roles/writer.yaml
```

### Default Path

When `store_path` is not set, the shared database is created at:

```
~/.initrunner/memory/{compose-name}-shared.lance
```

Where `{compose-name}` comes from `metadata.name`.

### How It Works

At startup, `apply_shared_memory()` patches each service's role definition:

- **Roles with `memory:` configured**: the existing `store_path` and `semantic.max_memories` are overridden with the shared values. All other memory settings (embeddings, max_sessions, etc.) are preserved.
- **Roles without `memory:`**: a `MemoryConfig` is injected with the shared path and `semantic.max_memories`, so `remember()`/`recall()`/`list_memories()` tools become available automatically.

### Embedding Consistency

All services sharing a memory store must use compatible embedding models (same dimensions). If one service embeds with a 1536-dimension model and another uses a 768-dimension model, the second service will raise a `DimensionMismatchError` on first use. The store also tracks the embedding model identity, so switching models is caught even when dimensions happen to match (raises `EmbeddingModelChangedError`). Keep `memory.embeddings` consistent across roles, or omit it to let all services derive from their `spec.model.provider` defaults.

### Concurrency

LanceDB handles concurrent access from multiple service threads via internal locking. No additional configuration is needed.

## Shared Documents

When `spec.shared_documents.enabled` is `true`, all services in the compose orchestration share a single document store. This lets you ingest documents once (e.g. via one service's `ingest` config) and have every service's `search_documents` tool query the same store.

Unlike shared memory, shared documents requires **explicit embedding configuration** at the compose level. This prevents embedding model mismatches between roles querying the same store.

### Configuration

```yaml
spec:
  shared_documents:
    enabled: true
    store_path: ./shared-docs.lance   # optional, default: ~/.initrunner/stores/{name}-shared.lance
    embeddings:
      provider: openai                # required when enabled
      model: text-embedding-3-small   # required when enabled
  services:
    researcher:
      role: roles/researcher.yaml     # has ingest config with sources
    writer:
      role: roles/writer.yaml         # no ingest config needed
```

### Default Path

When `store_path` is not set, the shared document store is created at:

```
~/.initrunner/stores/{compose-name}-shared.lance
```

Where `{compose-name}` comes from `metadata.name`.

### How It Works

At startup, `apply_shared_documents()` patches each service's role definition:

- **Roles with `ingest:` configured**: the existing `store_path`, `store_backend`, and `embeddings` are overridden with the shared values. All other ingest settings (`sources`, `chunking`) are preserved.
- **Roles without `ingest:`**: a minimal `IngestConfig` is injected with empty `sources` and the shared store settings. This registers the `search_documents` retrieval tool so the role can query the shared store without needing its own ingest config.

Shared documents is a compose-time config patch only. It does not run ingestion automatically. Run `initrunner ingest` against the role that has `sources` configured to populate the shared store.

### Embedding Consistency

The compose definition **owns** the embedding configuration for the shared store. When `shared_documents.enabled` is `true`, both `embeddings.provider` and `embeddings.model` must be set explicitly. This is validated at parse time and prevents the situation where different roles derive different embedding models from their `spec.model.provider`.

### Usage Pattern

1. Configure one role (e.g. `researcher`) with `ingest.sources` pointing at your documents.
2. Enable `shared_documents` with the same embedding model the researcher would use.
3. Run `initrunner ingest roles/researcher.yaml` to populate the shared store.
4. Start the compose. All services can now query the shared documents via `search_documents`.

## CLI Commands

### `compose validate`

Validates a compose definition file and checks that all referenced role files exist.

```bash
initrunner compose validate compose.yaml
```

Displays a table of services with their roles, sinks, dependencies, and restart policies. Exits with code 1 if validation fails or any role file is missing.

### `compose up`

Starts a compose orchestration in the foreground. Press Ctrl+C to stop.

```bash
initrunner compose up compose.yaml
initrunner compose up compose.yaml --audit-db ./custom-audit.db
initrunner compose up compose.yaml --no-audit
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `compose_file` | `Path` | *(required)* | Path to the compose YAML file. |
| `--audit-db` | `Path` | `~/.initrunner/audit.db` | Path to audit database. |
| `--no-audit` | `bool` | `false` | Disable audit logging. |

On startup, `compose up` prints a summary table of all services and then starts them in topological order. It installs signal handlers for `SIGINT` and `SIGTERM` for clean shutdown.

### `compose install`

Installs a systemd user unit file for background operation. The service runs `compose up` under systemd, with proper logging via journald and restart-on-failure.

```bash
initrunner compose install compose.yaml
initrunner compose install compose.yaml --force
initrunner compose install compose.yaml --env-file /path/to/.env
initrunner compose install compose.yaml --generate-env
```

#### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `compose_file` | `Path` | *(required)* | Path to the compose YAML file. |
| `--force` / `-f` | `bool` | `false` | Overwrite an existing unit file. |
| `--env-file` | `Path` | `null` | Additional `EnvironmentFile` directive for the unit. |
| `--generate-env` | `bool` | `false` | Generate a template `.env` file in the compose directory. |

Environment variables from your shell (e.g., exports in `.bashrc`) are **not** inherited by systemd services. Use `--env-file` or place a `.env` file in the compose directory to provide secrets like `OPENAI_API_KEY`.

If user lingering is not enabled, a warning is printed. See [User Lingering](#user-lingering) below.

### `compose uninstall`

Stops, disables, and removes the systemd user unit for a compose project.

```bash
initrunner compose uninstall my-pipeline
initrunner compose uninstall compose.yaml
```

Accepts either the compose `metadata.name` or a path to the compose YAML file.

### `compose start`

Starts the systemd service for a compose project.

```bash
initrunner compose start my-pipeline
initrunner compose start compose.yaml
```

Accepts either the compose `metadata.name` or a path to the compose YAML file.

### `compose stop`

Stops the systemd service for a compose project.

```bash
initrunner compose stop my-pipeline
initrunner compose stop compose.yaml
```

Accepts either the compose `metadata.name` or a path to the compose YAML file.

### `compose restart`

Restarts the systemd service for a compose project.

```bash
initrunner compose restart my-pipeline
initrunner compose restart compose.yaml
```

Accepts either the compose `metadata.name` or a path to the compose YAML file.

### `compose status`

Shows the `systemctl status` output for a compose service.

```bash
initrunner compose status my-pipeline
initrunner compose status compose.yaml
```

Accepts either the compose `metadata.name` or a path to the compose YAML file.

### `compose logs`

Shows journald logs for a compose service.

```bash
initrunner compose logs my-pipeline
initrunner compose logs my-pipeline -f
initrunner compose logs my-pipeline -n 100
```

#### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `name_or_file` | `str` | *(required)* | Compose name or path to compose YAML. |
| `--follow` / `-f` | `bool` | `false` | Follow log output (like `tail -f`). |
| `--lines` / `-n` | `int` | `50` | Number of lines to show. |

## Systemd Deployment

### Overview

Systemd integration lets you run compose pipelines as background services with proper process management. Benefits over running `compose up` in a terminal or tmux session:

- **Logging**: stdout/stderr go to journald, queryable with `journalctl`.
- **Restart policies**: systemd restarts the process on failure automatically.
- **Boot persistence**: enable the unit to start on boot (with user lingering).
- **Clean shutdown**: `KillSignal=SIGTERM` with a 30-second timeout.

### Workflow

```bash
# 1. Validate the compose definition
initrunner compose validate compose.yaml

# 2. Install the systemd unit
initrunner compose install compose.yaml

# 3. Start the service
initrunner compose start my-pipeline

# 4. Enable on boot (optional)
systemctl --user enable initrunner-my-pipeline.service

# 5. Monitor
initrunner compose status my-pipeline
initrunner compose logs my-pipeline -f
```

### Environment Variables

Systemd services run in a restricted environment — shell variables from `.bashrc`, `.profile`, or `export` statements are **not** inherited. API keys and secrets must be provided via environment files.

The generated unit includes two `EnvironmentFile` directives (with the `-` prefix, meaning "don't fail if missing"):

1. `{compose_dir}/.env` — project-level secrets
2. `~/.initrunner/.env` — user-level defaults

If you pass `--env-file /path/to/custom.env` during install, an additional `EnvironmentFile` directive is added.

Use `--generate-env` to create a template `.env` file in the compose directory with placeholder entries for common API keys:

```bash
initrunner compose install compose.yaml --generate-env
```

### User Lingering

By default, systemd user services stop when the user logs out. To keep services running after logout (and start them on boot), enable lingering:

```bash
loginctl enable-linger $USER
```

The `compose install` command checks for lingering and prints a warning if it is not enabled.

### Unit File Location

Unit files are written to:

```
~/.config/systemd/user/initrunner-{name}.service
```

Where `{name}` is derived from `metadata.name` in the compose definition, sanitized for systemd (non-alphanumeric characters replaced with dashes).

## Example: Email Pipeline

The `examples/compose/` directory contains a complete email processing pipeline with four services.

### Data Flow

```
inbox-watcher ──> triager ──> researcher
                     │
                     └──────> responder
```

1. **inbox-watcher** — Polls for new emails on a cron schedule (every 5 minutes) and summarizes them.
2. **triager** — Analyzes each summary and decides whether it needs research or a direct response. Fans out to both downstream services.
3. **researcher** — Investigates technical questions and produces research summaries.
4. **responder** — Drafts professional email replies for simple inquiries. Configured with `on-failure` restart.

### `compose.yaml`

```yaml
apiVersion: initrunner/v1
kind: Compose
metadata:
  name: email-pipeline
  description: Multi-agent email processing pipeline
spec:
  services:
    inbox-watcher:
      role: roles/inbox-watcher.yaml
      sink:
        type: delegate
        target: triager
    triager:
      role: roles/triager.yaml
      depends_on:
        - inbox-watcher
      sink:
        type: delegate
        strategy: sense           # auto-route to the right target
        target:
          - researcher
          - responder
    researcher:
      role: roles/researcher.yaml
      depends_on:
        - triager
    responder:
      role: roles/responder.yaml
      depends_on:
        - triager
      restart:
        condition: on-failure
        max_retries: 3
        delay_seconds: 5
```

With `strategy: sense`, the triager's output is analyzed and sent to either the researcher or the responder — not both. Use `strategy: all` (or omit) to fan out to every target.

### Role Files

Each role is a standard InitRunner role definition. For example, `roles/inbox-watcher.yaml`:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: inbox-watcher
  description: Monitors inbox and forwards new messages
  tags: [compose, email]
spec:
  role: >
    You are an inbox monitor. When triggered, summarize the incoming
    email content and forward it for triage. Output a concise summary
    including sender, subject, and key points.
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.1
  triggers:
    - type: cron
      schedule: "*/5 * * * *"
      prompt: "Check for new emails and summarize any unread messages."
  guardrails:
    max_tokens_per_run: 2000
    timeout_seconds: 30
```

## Example: Content Pipeline

The `examples/compose/content-pipeline/` directory contains a file-driven content creation pipeline with four services.

### Data Flow

```
content-watcher ──> researcher ──> writer
                        │
                        └──────> reviewer
```

1. **content-watcher** — Watches `./drafts/` for new or existing markdown and text files. Uses `process_existing: true` to handle files already in the directory on startup, then monitors for live changes.
2. **researcher** — Receives content briefs and produces research summaries. Fans out to both writer and reviewer via delegate sink.
3. **writer** — Takes research output and produces polished content. Configured with `on-failure` restart.
4. **reviewer** — Runs QA checks on the research output in parallel with the writer. Also configured with `on-failure` restart.

### `compose.yaml`

```yaml
apiVersion: initrunner/v1
kind: Compose
metadata:
  name: content-pipeline
  description: >
    Multi-agent content creation pipeline. A file watcher monitors ./drafts/
    for new markdown or text files, extracts the topic, and delegates to a
    researcher. The researcher fans out to a writer (polished output) and a
    reviewer (QA checks).
spec:
  services:
    content-watcher:
      role: roles/content-watcher.yaml
      sink:
        type: delegate
        target: researcher

    researcher:
      role: roles/researcher.yaml
      depends_on:
        - content-watcher
      sink:
        type: delegate
        target:
          - writer
          - reviewer

    writer:
      role: roles/writer.yaml
      depends_on:
        - researcher
      restart:
        condition: on-failure
        max_retries: 3
        delay_seconds: 5

    reviewer:
      role: roles/reviewer.yaml
      depends_on:
        - researcher
      restart:
        condition: on-failure
        max_retries: 2
        delay_seconds: 5
```

Key patterns demonstrated:

- **`process_existing: true`** on the file watch trigger lets content-watcher pick up drafts already in the directory, not just new changes. See [Triggers: Startup Scan](../core/triggers.md#startup-scan).
- **Fan-out delegation** from researcher to both writer and reviewer runs the two downstream services in parallel on the same input.

## Validation and Error Handling

### Schema Validation

Compose definitions are validated at load time with Pydantic. The following checks are performed:

- **At least one service** must be defined in `spec.services`.
- **Unknown service references**: `depends_on` entries and delegate `target` values must reference services defined in the same compose file.
- **Self-references**: A service cannot depend on itself or delegate to itself.
- **Cycle detection**: Kahn's algorithm detects cycles in both the dependency graph (`depends_on`) and the delegate graph (`sink.target`). A cycle in either graph is a validation error.
- **Role file existence**: `compose validate` checks that each service's role file exists on disk.

### Example Errors

```
Service 'triager' depends on unknown service 'missing'
Service 'responder' cannot delegate to itself
Compose contains a dependency cycle
Compose contains a delegate cycle
```

### Runtime Error Handling

During orchestration, errors are handled defensively:

- **Sink failures**: If a delegate sink or role-level sink fails, the error is logged to stderr. Other sinks continue to fire, and the service keeps running.
- **Queue overflow**: When a downstream service's inbox is full and the timeout expires, the message is dropped with a stderr warning. The upstream service is not affected.
- **Circuit breaker**: When a delegate sink's circuit breaker is enabled and trips open after consecutive failures, all messages are rejected with `circuit_open` audit status until the reset timer allows a probe. See [Circuit Breaker](#circuit-breaker).
- **Agent execution errors**: Failed agent runs increment the service's `error_count` but do not stop the service thread. The error is included in audit logs if auditing is enabled.
