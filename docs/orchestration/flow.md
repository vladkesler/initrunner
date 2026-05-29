# Flow Orchestration -- Multi-Agent Flows

Flow orchestration lets you define multiple agents in a single `flow.yaml` file, wire them together with delegation edges, and run them all with one command. The agent topology is compiled into a [pydantic-graph](https://ai.pydantic.dev/graph/beta/parallel/) execution graph. Fan-out patterns (one agent delegating to multiple targets) run in parallel via Fork/Join; routing strategies (keyword/sense) use Decision nodes. Both one-shot and daemon execution use the same graph engine.

## Quick Start

Create a minimal two-agent flow file where a producer delegates its output to a consumer:

```yaml
# flow.yaml
apiVersion: initrunner/v1
kind: Flow
metadata:
  name: my-pipeline
  description: Simple producer-consumer pipeline
spec:
  agents:
    producer:
      role: roles/producer.yaml
      sink:
        type: delegate
        target: consumer
    consumer:
      role: roles/consumer.yaml
      needs:
        - producer
```

Validate the definition:

```bash
initrunner flow validate flow.yaml
```

Start the orchestration (foreground, Ctrl+C to stop):

```bash
initrunner flow up flow.yaml
```

## Scaffold with `flow new`

Instead of writing YAML by hand, scaffold a project directory:

```bash
initrunner flow new my-pipeline                            # 3-agent linear pipeline
initrunner flow new desk --pattern route --shared-memory   # support-desk with intent routing
initrunner flow new spread --pattern fan-out --agents 5    # 1 dispatcher + 4 workers
```

This creates a directory with `flow.yaml` and `roles/*.yaml` files, all pre-validated. Run `initrunner flow new --list-patterns` to see available patterns.

## Flow Definition

The top-level structure follows the same `apiVersion`/`kind`/`metadata`/`spec` pattern as role definitions.

```yaml
apiVersion: initrunner/v1      # required
kind: Flow                      # required, must be "Flow"
metadata:
  name: my-pipeline             # required
  description: A pipeline       # optional
spec:
  agents:                       # required, at least one agent
    agent-a:
      role: roles/a.yaml
      # ... agent config
    agent-b:
      role: roles/b.yaml
      # ... agent config
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
| `kind` | `"Flow"` | *(required)* | Must be `Flow`. |
| `metadata.name` | `str` | *(required)* | Name of the flow definition. |
| `metadata.description` | `str` | `""` | Human-readable description. |
| `spec.agents` | `dict[str, AgentConfig]` | *(required)* | Map of agent name to configuration. Must contain at least one agent. |
| `spec.shared_memory` | `SharedMemoryConfig` | disabled | Shared memory configuration across agents. |
| `spec.shared_memory.enabled` | `bool` | `false` | Enable shared memory across all agents. |
| `spec.shared_memory.store_path` | `str \| null` | `null` | Path to the shared memory store. Default: `~/.initrunner/memory/{name}-shared.lance`. |
| `spec.shared_memory.max_memories` | `int` | `1000` | Maximum number of memories in the shared store. |
| `spec.shared_memory.store_backend` | `str` | `"lancedb"` | Store backend. Uses LanceDB, an in-process vector database. |
| `spec.shared_documents` | `SharedDocumentsConfig` | disabled | Shared document store configuration across agents. See [Shared Documents](#shared-documents). |
| `spec.shared_documents.enabled` | `bool` | `false` | Enable a shared document store across all agents. |
| `spec.shared_documents.store_path` | `str \| null` | `null` | Path to the shared document store. Default: `~/.initrunner/stores/{name}-shared.lance`. |
| `spec.shared_documents.store_backend` | `str` | `"lancedb"` | Store backend. |
| `spec.shared_documents.embeddings.provider` | `str` | *(required when enabled)* | Embedding provider. Must be set explicitly when `enabled: true`. |
| `spec.shared_documents.embeddings.model` | `str` | *(required when enabled)* | Embedding model. Must be set explicitly when `enabled: true`. |

## Agent Configuration

Each entry in `spec.agents` configures one agent.

```yaml
agents:
  my-agent:
    role: roles/my-role.yaml        # required
    trigger: null                   # optional, override trigger config
    sink:                           # optional, delegate sink config
      type: delegate
      target: other-agent
    needs:                          # optional, startup ordering
      - dependency-agent
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
| `role` | `str` | *(required)* | Path to the role YAML file, relative to the flow file. |
| `trigger` | `dict \| null` | `null` | Override trigger configuration (reserved). |
| `sink` | `DelegateSinkConfig \| null` | `null` | Delegate sink for routing output to other agents. |
| `needs` | `list[str]` | `[]` | Agents that must start before this one. |
| `health_check` | `HealthCheckConfig` | *(see below)* | Health check parameters. |
| `restart` | `RestartPolicy` | *(see below)* | Restart policy for the agent. |
| `environment` | `dict[str, str]` | `{}` | Additional environment variables for the agent. |

## Delegate Sink

Delegate sinks route an agent's output to one or more other agents. The upstream agent's output becomes the downstream agent's input prompt. Each delegation edge carries an immutable `DelegationEnvelope` with the prompt, trace chain, and metadata.

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
| `target` | `str \| list[str]` | *(required)* | Target agent name(s) to route output to. |
| `strategy` | `"all" \| "keyword" \| "sense" \| "ensemble"` | `"all"` | Routing strategy for multi-target delegates. See [Routing Strategy](#routing-strategy) and [Ensemble Voting](#ensemble-voting). |
| `ensemble` | `EnsembleConfig \| None` | `None` | Voting config. Required when `strategy: ensemble`, rejected otherwise. See [Ensemble Voting](#ensemble-voting). |
| `loop_back` | `LoopBackConfig \| None` | `None` | Bounded loop-back edge for critic/refine patterns. See [Loop-Back Routing](#loop-back-routing). |
| `keep_existing_sinks` | `bool` | `false` | When `true`, the agent's role-level sinks (webhook, file, custom) are also activated alongside the delegate. When `false`, only the delegate sink is used. |
| `queue_size` | `int` | `100` | Daemon ingress queue capacity (bounded backpressure for trigger-driven runs). |
| `timeout_seconds` | `int` | `60` | Reserved (kept for schema compatibility). |

### Routing Strategy

When a delegate sink has multiple targets, the `strategy` field controls how messages are routed.

| Strategy | Behavior | API calls |
|----------|----------|-----------|
| `all` | Fan-out -- every target receives every message (default, backward compatible) | None |
| `keyword` | [Intent Sensing](../core/intent_sensing.md) keyword scoring picks the best target | None |
| `sense` | Keyword scoring first; LLM tiebreaker when ambiguous | 0 or 1 per message |
| `ensemble` | Fan-out to every target, then vote on the answers and keep one winner | 0 (majority/weighted) or 1 per candidate (judge) |

The `keyword` and `sense` strategies use the same two-pass [Intent Sensing](../core/intent_sensing.md) logic used by `--sense` in the CLI. They score the agent's output text against each target agent's `metadata.name`, `metadata.description`, and `metadata.tags` from its role definition.

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

Routing diagnostics are injected into the payload's trigger metadata as `_flow_route_reason` for audit visibility.

#### Optimizing roles for routing

The same tips from [Intent Sensing -- Optimizing Roles](../core/intent_sensing.md#optimizing-roles-for-sensing) apply. Each target agent's role should have specific, non-overlapping tags and a clear description:

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

#### Dashboard configuration

The [dashboard flow builder](../interfaces/dashboard.md) exposes routing strategy visually when creating a flow with the **Route** pattern. Three pill buttons (Broadcast / Keyword / Sense) appear below the slot picker with a "Recommended" badge on Sense. A collapsible detail section shows scoring weights (tags 3x, name 2x, description 1.5x) and per-slot quality indicators. The Route pattern supports variable agent counts (3-10) with semantic specialist names that directly feed into name-match scoring. The selected strategy is written into the generated `flow.yaml`.

#### Single target behavior

When only one target is specified, `strategy` has no effect -- the message always goes to that target regardless of the strategy setting.

### Ensemble Voting

The `ensemble` strategy fans the same prompt out to every target (like `all`), then a reducer picks a single winning answer instead of concatenating them. Use it when you want several agents (or several models) to answer the same question and keep the best or most-agreed-upon response.

```yaml
router:
  role: roles/router.yaml
  sink:
    type: delegate
    strategy: ensemble
    target: [gpt-answerer, claude-answerer, llama-answerer]
    ensemble:
      mode: majority          # majority | weighted | judge
```

`ensemble` requires at least two targets and an `ensemble:` block. The block is rejected for any other strategy.

#### EnsembleConfig options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | `"majority" \| "weighted" \| "judge"` | `"majority"` | How the winner is chosen. |
| `judge_model` | `str` | `"openai:gpt-4o-mini"` | Model used to score candidates when `mode: judge`. |
| `judge_criteria` | `list[str]` | `[]` | Criteria the judge checks. Defaults to `clarity, completeness, accuracy` when empty. |
| `weights` | `dict[str, float] \| None` | `None` | Per-target weight for `mode: weighted`. Keys must be target names. |

#### Modes

- **majority** -- normalized vote on identical answers. The most frequent answer wins; ties break on the lowest topology index, so the result is deterministic. No extra API calls.
- **weighted** -- each target carries a weight; the answer from the highest-weight target wins. Requires a non-empty `weights` map whose keys are all targets. No extra API calls.
- **judge** -- an LLM judge (reusing [`eval/judge.py`](../operations/testing.md)) scores every candidate against `judge_criteria` and the highest-scoring answer wins. Costs one judge call per candidate, so a three-way ensemble in judge mode adds three judge calls per round.

```yaml
# weighted: trust the specialist model more
sink:
  type: delegate
  strategy: ensemble
  target: [fast-model, strong-model]
  ensemble:
    mode: weighted
    weights:
      fast-model: 0.2
      strong-model: 0.8

# judge: let an LLM pick the clearest, most complete answer
sink:
  type: delegate
  strategy: ensemble
  target: [draft-a, draft-b, draft-c]
  ensemble:
    mode: judge
    judge_model: openai:gpt-4o-mini
    judge_criteria: [clarity, completeness, correctness]
```

The winning answer flows downstream as a single `DelegationEnvelope`, exactly like the output of any other agent, so ensemble targets can be terminal (the winner becomes the flow output) or feed a downstream agent.

#### Audit trail

Every ensemble vote is recorded on the signed audit chain as a row with `trigger_type: ensemble_vote`. The row stores the winning answer (truncated) and a `vote_trace` in its trigger metadata: the candidate answers, the per-mode tally (vote counts, weights, or judge scores), and the winning source. Each candidate string is capped at 1000 characters with a `[truncated]` marker so a wide fan-in cannot bloat the chain. Inspect them with `initrunner audit export --trigger-type ensemble_vote`.

### Loop-Back Routing

A `loop_back` edge turns a normal forward delegation into a bounded refine loop: an agent delegates forward (for example, a writer hands a draft to a critic), and the critic's output is routed back to an upstream agent for another pass. This is the classic critic/refine supervisor pattern. Flow graphs are otherwise acyclic, and every unmarked cycle is still rejected at validation time; only an explicitly-marked `loop_back` edge is permitted to close a cycle.

```yaml
writer:
  role: ./roles/writer.yaml
  sink:
    type: delegate
    target: critic            # forward edge: writer -> critic
    loop_back:
      type: loop-back
      target: writer          # back edge: critic output returns to writer
      max_iterations: 4       # always stop after 4 rounds
      until:
        output: "contains:APPROVED"   # exit early when the critic approves
critic:
  role: ./roles/critic.yaml
```

The flow runs `writer -> critic -> writer -> critic -> ...` until one of the two bounds is hit, then the last output becomes the flow result. The loop target is usually the loop source itself (`writer`), but it can be any upstream agent on the path.

#### LoopBackConfig options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `"loop-back"` | *(required)* | Discriminator. Must be `loop-back`. |
| `target` | `str` | *(required)* | The agent the loop returns to. Must be a known agent and must not be one of the sink's own forward `target`s. |
| `max_iterations` | `int` | `3` | Hard cap on loop rounds. Bounded to `1..20`. The loop always stops once this many rounds complete. |
| `until` | `dict[str, str] \| None` | `None` | Optional early-exit predicate evaluated against the latest agent output. When omitted, only `max_iterations` bounds the loop. |

#### The `until` predicate

`until` is a small map keyed by the output field to inspect. Only `output` (the latest agent text flowing back along the loop) is supported. The value is one of:

- `contains:<text>` -- exit when the output contains `<text>` (case-insensitive). Use this with a critic that emits a sentinel like `APPROVED` once it is satisfied.
- `<op><number>` where `<op>` is `>`, `>=`, `<`, `<=`, or `==` -- exit when the first number parsed from the output satisfies the comparison. For example `">0.8"` exits when a critic reports a confidence score above 0.8.

Because `until` is keyed by field name and `output` is the only supported field, a single condition string applies per loop-back edge. Validation rejects any other key with `loop_back until only supports the 'output' field`. The predicate evaluates that one condition against the latest output, so pick the single most reliable exit signal: an approval token via `contains:`, or a numeric threshold such as `">0.8"`.

#### Bounding and safety

The loop is bounded two independent ways. `max_iterations` is the hard ceiling, and `until` is the optional early exit. Each round carries an immutable per-edge `DelegationEnvelope` whose `loop_back_iteration` counter is incremented by a decider step, so concurrent branches never share or corrupt the count. The flow [depth limit](#depth-limit) remains in force as a final backstop, so a misconfigured loop can never run unbounded.

#### Validation

`initrunner flow validate` shows the loop-back in the sink column:

```bash
$ initrunner flow validate flow.yaml
```

```
                               Flow: refine-loop
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┓
┃ Agent  ┃ Role                ┃ Sink                       ┃ Needs  ┃ Restart ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━┩
│ writer │ ./roles/writer.yaml │ delegate: critic           │ (none) │ none    │
│        │                     │ (loop-back: writer x4)     │        │         │
│ critic │ ./roles/critic.yaml │ (none)                     │ (none) │ none    │
└────────┴─────────────────────┴────────────────────────────┴────────┴─────────┘
Valid
```

### Fan-In Behavior

When multiple agents delegate to the same downstream target (diamond pattern: A->[B,C]->D), the downstream agent runs **once** with the combined output from all upstream branches. By default outputs are joined in YAML declaration order (topology order), separated by `---`. When the fan-in target is fed by the targets of a single `ensemble` source, the fan-in vote replaces concatenation and only the winning answer is passed downstream.

### Role Sink Interaction

By default, when a flow `sink:` is configured, the agent's role-level sinks (from `spec.sinks` in the role YAML) are **not** activated. This prevents duplicate output routing.

Set `keep_existing_sinks: true` to activate both the delegate sink and the role's own sinks. This is useful when you want to both forward output to another agent and log it to a file or webhook.

When no flow `sink:` is configured at all, the agent uses its role-level sinks as if running in standalone daemon mode.

### Failed Runs

Only successful runs are forwarded via delegate sinks. If an agent run fails (`success: false`), the delegate sink silently skips the event. This prevents error messages from cascading through the flow.

### Delegation Policy

Each delegation edge checks `check_delegation_policy()` before executing the target agent. If the policy engine denies the delegation (based on agent authorization rules), the target step produces empty output and the delegation chain stops for that branch. See [Agent Policy](../security/agent-policy.md).

### Depth Limit

Delegation chains are limited to 20 agents. If a chain exceeds this depth (e.g. due to misconfigured circular references that bypass cycle detection), the step produces empty output and logs a warning.

## Startup Order

Agents start in topological order based on `needs` declarations. Agents without dependencies start first, forming "tiers" of parallel startup.

### Example

Given this configuration:

```yaml
agents:
  inbox-watcher:
    role: roles/inbox-watcher.yaml
    sink:
      type: delegate
      target: triager
  triager:
    role: roles/triager.yaml
    needs: [inbox-watcher]
    sink:
      type: delegate
      target: [researcher, responder]
  researcher:
    role: roles/researcher.yaml
    needs: [triager]
  responder:
    role: roles/responder.yaml
    needs: [triager]
```

The startup order is:

```
Tier 0:  inbox-watcher          (no dependencies)
Tier 1:  triager                (depends on inbox-watcher)
Tier 2:  researcher, responder  (both depend on triager)
```

Agents within the same tier start concurrently. Shutdown happens in reverse topological order.

## Restart Policies

The `restart` block controls what happens when an agent thread exits unexpectedly.

```yaml
restart:
  condition: on-failure
  max_retries: 3
  delay_seconds: 5
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `condition` | `"none"` \| `"on-failure"` \| `"always"` | `"none"` | When to restart. `none` = never, `on-failure` = only if the agent recorded errors, `always` = restart regardless of exit reason. |
| `max_retries` | `int` | `3` | Maximum number of restart attempts. Once exceeded, the agent stays down. |
| `delay_seconds` | `int` | `5` | Seconds to wait before restarting the agent. |

### Restart Conditions

| Condition | Restart when... |
|-----------|----------------|
| `none` | Never restart. The agent stays down if its thread exits. |
| `on-failure` | Restart only if the agent has recorded at least one error (`error_count > 0`). |
| `always` | Restart whenever the agent thread is no longer alive, regardless of exit reason. |

### Health Reporting

Per-agent run and error counts are tracked and available via `agent_health()`. In daemon mode, each trigger event spawns an independent graph run; failed runs increment the agent's error counter. The `restart` configuration fields are reserved for future use with daemon-level retry policies.

## Health Checks

Health check configuration is available per-agent but is reserved for future use. The health monitor currently checks thread liveness rather than application-level health.

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

Flow agents are standard InitRunner roles. All role features carry over:

- **Triggers**: An agent's role-level triggers (cron, file_watch, webhook) fire normally. The inbox-watcher example uses a cron trigger to poll for new emails.
- **Sinks**: Role-level sinks activate when no flow `sink:` is set, or when `keep_existing_sinks: true`. See [Sinks](sinks.md).
- **Tools**: All configured tools (built-in, custom, MCP) are available to the agent. See [Tools](../agents/tools.md).
- **Memory**: Memory-enabled roles persist and recall memories as usual. Session pruning runs after each trigger execution, matching standalone daemon behavior. Use `spec.shared_memory` to give all agents a common memory store -- see [Shared Memory](#shared-memory). See [Memory](../core/memory.md).
- **Documents**: Use `spec.shared_documents` to give all agents a common document store with flow-owned embedding config -- see [Shared Documents](#shared-documents). See [Ingestion](../core/ingestion.md).
- **Guardrails**: Timeout, token limits, and tool call limits from the role definition apply to each execution.
- **Skills**: Skills referenced in the role definition are loaded and available.

Agents without a flow `sink:` behave identically to running the role with `initrunner run <role> --daemon` -- triggers fire, sinks dispatch, and memory persists as configured.

## Runtime Architecture

### Graph Execution

The flow topology is compiled into a pydantic-graph `Graph` at runtime. Each agent becomes a `Step` node; fan-out delegation becomes `Fork(broadcast)`; fan-in becomes `Join` with topology-ordered concatenation; keyword/sense routing becomes `Decision` nodes.

```
flow.yaml
    ↓ build_flow_graph()
pydantic-graph Graph
    ↓ graph.run()
anyio task group (parallel branches via Fork/Join)
```

### One-Shot Mode

`run_once()` builds the graph and runs it synchronously via `anyio.run()`. The graph engine handles parallelism natively -- fan-out branches execute concurrently as anyio tasks. Each step calls `execute_run_async()` for native async agent execution.

### Real-time tool activity

Both one-shot and daemon modes stream live tool-call events. In the CLI, each tool event is printed with the agent name prefix (e.g. `[producer] tool search_web: ok (123ms)`). In the dashboard, `tool_event` SSE messages include an `agent_name` field and the Tool Activity panel renders them alongside the conversation. Fan-out branches can interleave tool events from multiple agents concurrently.

### Daemon Mode

`start()` spawns a background thread running an anyio event loop. Trigger events (cron, webhook, file watcher) are enqueued to a bounded `threading.Queue(maxsize=32)` -- trigger threads block when the queue is full, providing backpressure. A dispatcher task polls the ingress queue and spawns independent graph runs for each event.

```
Trigger threads → ingress Queue(32) → dispatcher task → graph.run() per event
```

Multiple graph runs execute concurrently. Each run is independent -- no shared mutable state between runs.

### DelegationEnvelope

Data flows between agents via immutable `DelegationEnvelope` objects. Each envelope carries the prompt, a trace chain (immutable tuple of agent names), the original prompt, and metadata. In fan-out, each branch gets its own copy -- no shared mutable state between parallel branches.

### Shutdown

1. First Ctrl+C (or SIGTERM) sets the shutdown event.
2. The dispatcher stops accepting new trigger events.
3. In-flight graph runs complete naturally.
4. The daemon thread joins (30s timeout).

A second Ctrl+C force-exits via `os._exit(1)`.

## Shared Memory

When `spec.shared_memory.enabled` is `true`, all agents in the flow share a single memory database. Any agent can call `remember()` to store information and any other agent can `recall()` it -- enabling cross-agent knowledge sharing without delegate sinks.

### Configuration

```yaml
spec:
  shared_memory:
    enabled: true
    store_path: ./shared-memory.lance   # optional, default: ~/.initrunner/memory/{name}-shared.lance
    max_memories: 500                # optional, default: 1000
  agents:
    researcher:
      role: roles/researcher.yaml
    writer:
      role: roles/writer.yaml
```

### Default Path

When `store_path` is not set, the shared database is created at:

```
~/.initrunner/memory/{flow-name}-shared.lance
```

Where `{flow-name}` comes from `metadata.name`.

### How It Works

At startup, `apply_shared_memory()` patches each agent's role definition:

- **Roles with `memory:` configured**: the existing `store_path` and `semantic.max_memories` are overridden with the shared values. All other memory settings (embeddings, max_sessions, etc.) are preserved.
- **Roles without `memory:`**: a `MemoryConfig` is injected with the shared path and `semantic.max_memories`, so `remember()`/`recall()`/`list_memories()` tools become available automatically.

### Embedding Consistency

All agents sharing a memory store must use compatible embedding models (same dimensions). If one agent embeds with a 1536-dimension model and another uses a 768-dimension model, the second agent will raise a `DimensionMismatchError` on first use. The store also tracks the embedding model identity, so switching models is caught even when dimensions happen to match (raises `EmbeddingModelChangedError`). Keep `memory.embeddings` consistent across roles, or omit it to let all agents derive from their `spec.model.provider` defaults.

### Concurrency

LanceDB handles concurrent access from multiple agent threads via internal locking. No additional configuration is needed.

## Shared Documents

When `spec.shared_documents.enabled` is `true`, all agents in the flow share a single document store. This lets you ingest documents once (e.g. via one agent's `ingest` config) and have every agent's `search_documents` tool query the same store.

Unlike shared memory, shared documents requires **explicit embedding configuration** at the flow level. This prevents embedding model mismatches between roles querying the same store.

### Configuration

```yaml
spec:
  shared_documents:
    enabled: true
    store_path: ./shared-docs.lance   # optional, default: ~/.initrunner/stores/{name}-shared.lance
    embeddings:
      provider: openai                # required when enabled
      model: text-embedding-3-small   # required when enabled
  agents:
    researcher:
      role: roles/researcher.yaml     # has ingest config with sources
    writer:
      role: roles/writer.yaml         # no ingest config needed
```

### Default Path

When `store_path` is not set, the shared document store is created at:

```
~/.initrunner/stores/{flow-name}-shared.lance
```

Where `{flow-name}` comes from `metadata.name`.

### How It Works

At startup, `apply_shared_documents()` patches each agent's role definition:

- **Roles with `ingest:` configured**: the existing `store_path`, `store_backend`, and `embeddings` are overridden with the shared values. All other ingest settings (`sources`, `chunking`) are preserved.
- **Roles without `ingest:`**: a minimal `IngestConfig` is injected with empty `sources` and the shared store settings. This registers the `search_documents` retrieval tool so the role can query the shared store without needing its own ingest config.

Shared documents is a flow-time config patch only. It does not run ingestion automatically. Run `initrunner ingest` against the role that has `sources` configured to populate the shared store.

### Embedding Consistency

The flow definition **owns** the embedding configuration for the shared store. When `shared_documents.enabled` is `true`, both `embeddings.provider` and `embeddings.model` must be set explicitly. This is validated at parse time and prevents the situation where different roles derive different embedding models from their `spec.model.provider`.

### Usage Pattern

1. Configure one role (e.g. `researcher`) with `ingest.sources` pointing at your documents.
2. Enable `shared_documents` with the same embedding model the researcher would use.
3. Run `initrunner ingest roles/researcher.yaml` to populate the shared store.
4. Start the flow. All agents can now query the shared documents via `search_documents`.

## CLI Commands

### `flow validate`

Validates a flow definition file, checks that every referenced role file exists on disk, and recursively validates each referenced role against the agent schema.

```bash
initrunner flow validate flow.yaml
```

On a clean flow, displays a table of agents with their roles, sinks, dependencies, and restart policies. On any error (flow schema, missing role file, or invalid referenced role), exits with code 1 and renders a Rich panel showing each issue. Issues from nested role files surface with `agents.<name>.` field prefixes so you can tell which referenced file is broken without opening each one. The same recursive pre-flight runs automatically before `flow up` and `flow install` -- see [Pre-flight YAML validation](../getting-started/cli.md#pre-flight-yaml-validation).

### `flow up`

Starts a flow orchestration in the foreground. Press Ctrl+C to stop.

```bash
initrunner flow up flow.yaml
initrunner flow up flow.yaml --audit-db ./custom-audit.db
initrunner flow up flow.yaml --no-audit
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `flow_file` | `Path` | *(required)* | Path to the flow YAML file. |
| `--audit-db` | `Path` | `~/.initrunner/audit.db` | Path to audit database. |
| `--no-audit` | `bool` | `false` | Disable audit logging. |

On startup, `flow up` prints a summary table of all agents and then starts them in topological order. It installs signal handlers for `SIGINT` and `SIGTERM` for clean shutdown.

### `flow install`

Installs a systemd user unit file for background operation. The service runs `flow up` under systemd, with proper logging via journald and restart-on-failure.

```bash
initrunner flow install flow.yaml
initrunner flow install flow.yaml --force
initrunner flow install flow.yaml --env-file /path/to/.env
initrunner flow install flow.yaml --generate-env
```

#### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `flow_file` | `Path` | *(required)* | Path to the flow YAML file. |
| `--force` / `-f` | `bool` | `false` | Overwrite an existing unit file. |
| `--env-file` | `Path` | `null` | Additional `EnvironmentFile` directive for the unit. |
| `--generate-env` | `bool` | `false` | Generate a template `.env` file in the flow directory. |

Environment variables from your shell (e.g., exports in `.bashrc`) are **not** inherited by systemd services. Use `--env-file` or place a `.env` file in the flow directory to provide secrets like `OPENAI_API_KEY`.

If user lingering is not enabled, a warning is printed. See [User Lingering](#user-lingering) below.

### `flow uninstall`

Stops, disables, and removes the systemd user unit for a flow project.

```bash
initrunner flow uninstall my-pipeline
initrunner flow uninstall flow.yaml
```

Accepts either the flow `metadata.name` or a path to the flow YAML file.

### `flow start`

Starts the systemd service for a flow project.

```bash
initrunner flow start my-pipeline
initrunner flow start flow.yaml
```

Accepts either the flow `metadata.name` or a path to the flow YAML file.

### `flow stop`

Stops the systemd service for a flow project.

```bash
initrunner flow stop my-pipeline
initrunner flow stop flow.yaml
```

Accepts either the flow `metadata.name` or a path to the flow YAML file.

### `flow restart`

Restarts the systemd service for a flow project.

```bash
initrunner flow restart my-pipeline
initrunner flow restart flow.yaml
```

Accepts either the flow `metadata.name` or a path to the flow YAML file.

### `flow status`

Shows the `systemctl status` output for a flow service.

```bash
initrunner flow status my-pipeline
initrunner flow status flow.yaml
```

Accepts either the flow `metadata.name` or a path to the flow YAML file.

### `flow logs`

Shows journald logs for a flow service.

```bash
initrunner flow logs my-pipeline
initrunner flow logs my-pipeline -f
initrunner flow logs my-pipeline -n 100
```

#### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `name_or_file` | `str` | *(required)* | Flow name or path to flow YAML. |
| `--follow` / `-f` | `bool` | `false` | Follow log output (like `tail -f`). |
| `--lines` / `-n` | `int` | `50` | Number of lines to show. |

## Systemd Deployment

### Overview

Systemd integration lets you run flow pipelines as background services with proper process management. Benefits over running `flow up` in a terminal or tmux session:

- **Logging**: stdout/stderr go to journald, queryable with `journalctl`.
- **Restart policies**: systemd restarts the process on failure automatically.
- **Boot persistence**: enable the unit to start on boot (with user lingering).
- **Clean shutdown**: `KillSignal=SIGTERM` with a 30-second timeout.

### Workflow

```bash
# 1. Validate the flow definition
initrunner flow validate flow.yaml

# 2. Install the systemd unit
initrunner flow install flow.yaml

# 3. Start the service
initrunner flow start my-pipeline

# 4. Enable on boot (optional)
systemctl --user enable initrunner-my-pipeline.service

# 5. Monitor
initrunner flow status my-pipeline
initrunner flow logs my-pipeline -f
```

### Environment Variables

Systemd services run in a restricted environment -- shell variables from `.bashrc`, `.profile`, or `export` statements are **not** inherited. API keys and secrets must be provided via environment files.

The generated unit includes two `EnvironmentFile` directives (with the `-` prefix, meaning "don't fail if missing"):

1. `{flow_dir}/.env` -- project-level secrets
2. `~/.initrunner/.env` -- user-level defaults

If you pass `--env-file /path/to/custom.env` during install, an additional `EnvironmentFile` directive is added.

Use `--generate-env` to create a template `.env` file in the flow directory with placeholder entries for common API keys:

```bash
initrunner flow install flow.yaml --generate-env
```

### User Lingering

By default, systemd user services stop when the user logs out. To keep services running after logout (and start them on boot), enable lingering:

```bash
loginctl enable-linger $USER
```

The `flow install` command checks for lingering and prints a warning if it is not enabled.

### Unit File Location

Unit files are written to:

```
~/.config/systemd/user/initrunner-{name}.service
```

Where `{name}` is derived from `metadata.name` in the flow definition, sanitized for systemd (non-alphanumeric characters replaced with dashes).

## Example: Email Pipeline

The `examples/flows/` directory contains a complete email processing pipeline with four agents.

### Data Flow

```
inbox-watcher ──> triager ──> researcher
                     │
                     └──────> responder
```

1. **inbox-watcher** -- Polls for new emails on a cron schedule (every 5 minutes) and summarizes them.
2. **triager** -- Analyzes each summary and decides whether it needs research or a direct response. Fans out to both downstream agents.
3. **researcher** -- Investigates technical questions and produces research summaries.
4. **responder** -- Drafts professional email replies for simple inquiries. Configured with `on-failure` restart.

### `flow.yaml`

```yaml
apiVersion: initrunner/v1
kind: Flow
metadata:
  name: email-pipeline
  description: Multi-agent email processing pipeline
spec:
  agents:
    inbox-watcher:
      role: roles/inbox-watcher.yaml
      sink:
        type: delegate
        target: triager
    triager:
      role: roles/triager.yaml
      needs:
        - inbox-watcher
      sink:
        type: delegate
        strategy: sense           # auto-route to the right target
        target:
          - researcher
          - responder
    researcher:
      role: roles/researcher.yaml
      needs:
        - triager
    responder:
      role: roles/responder.yaml
      needs:
        - triager
      restart:
        condition: on-failure
        max_retries: 3
        delay_seconds: 5
```

With `strategy: sense`, the triager's output is analyzed and sent to either the researcher or the responder -- not both. Use `strategy: all` (or omit) to fan out to every target.

### Role Files

Each role is a standard InitRunner role definition. For example, `roles/inbox-watcher.yaml`:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: inbox-watcher
  description: Monitors inbox and forwards new messages
  tags: [flow, email]
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

The `examples/flows/content-pipeline/` directory contains a file-driven content creation pipeline with four agents.

### Data Flow

```
content-watcher ──> researcher ──> writer
                        │
                        └──────> reviewer
```

1. **content-watcher** -- Watches `./drafts/` for new or existing markdown and text files. Uses `process_existing: true` to handle files already in the directory on startup, then monitors for live changes.
2. **researcher** -- Receives content briefs and produces research summaries. Fans out to both writer and reviewer via delegate sink.
3. **writer** -- Takes research output and produces polished content. Configured with `on-failure` restart.
4. **reviewer** -- Runs QA checks on the research output in parallel with the writer. Also configured with `on-failure` restart.

### `flow.yaml`

```yaml
apiVersion: initrunner/v1
kind: Flow
metadata:
  name: content-pipeline
  description: >
    Multi-agent content creation pipeline. A file watcher monitors ./drafts/
    for new markdown or text files, extracts the topic, and delegates to a
    researcher. The researcher fans out to a writer (polished output) and a
    reviewer (QA checks).
spec:
  agents:
    content-watcher:
      role: roles/content-watcher.yaml
      sink:
        type: delegate
        target: researcher

    researcher:
      role: roles/researcher.yaml
      needs:
        - content-watcher
      sink:
        type: delegate
        target:
          - writer
          - reviewer

    writer:
      role: roles/writer.yaml
      needs:
        - researcher
      restart:
        condition: on-failure
        max_retries: 3
        delay_seconds: 5

    reviewer:
      role: roles/reviewer.yaml
      needs:
        - researcher
      restart:
        condition: on-failure
        max_retries: 2
        delay_seconds: 5
```

Key patterns demonstrated:

- **`process_existing: true`** on the file watch trigger lets content-watcher pick up drafts already in the directory, not just new changes. See [Triggers: Startup Scan](../core/triggers.md#startup-scan).
- **Fan-out delegation** from researcher to both writer and reviewer runs the two downstream agents in parallel on the same input.

## Validation and Error Handling

### Schema Validation

Flow definitions are validated at load time with Pydantic. The following checks are performed:

- **At least one agent** must be defined in `spec.agents`.
- **Unknown agent references**: `needs` entries and delegate `target` values must reference agents defined in the same flow file.
- **Self-references**: An agent cannot depend on itself or delegate to itself.
- **Cycle detection**: Kahn's algorithm detects cycles in both the dependency graph (`needs`) and the delegate graph (`sink.target`). A cycle in either graph is a validation error.
- **Role file existence**: `flow validate`, `flow up`, and `flow install` all check that each agent's role file exists on disk.
- **Recursive role validation**: every referenced role YAML is loaded and validated against the agent schema. Per-field errors from a nested role surface with an `agents.<name>.` field prefix.

### Example Errors

```
Agent 'triager' depends on unknown agent 'missing'
Agent 'responder' cannot delegate to itself
Flow contains a dependency cycle
Flow contains a delegate cycle
```

### Runtime Error Handling

During orchestration, errors are handled defensively:

- **Sink failures**: If a delegate sink or role-level sink fails, the error is logged to stderr. Other sinks continue to fire, and the agent keeps running.
- **Queue overflow**: When a downstream agent's inbox is full and the timeout expires, the message is dropped with a stderr warning. The upstream agent is not affected.
- **Circuit breaker**: When a delegate sink's circuit breaker is enabled and trips open after consecutive failures, all messages are rejected with `circuit_open` audit status until the reset timer allows a probe. See [Circuit Breaker](#circuit-breaker).
- **Agent execution errors**: Failed agent runs increment the agent's `error_count` but do not stop the agent thread. The error is included in audit logs if auditing is enabled.

## Coordinating with Shared State

Flow agents pass a prompt string along each edge, and a fan-in join concatenates those strings. When agents need to hand each other a named, structured value (a chosen plan, a budget, a claimed work item) rather than prose, add a per-run blackboard so an upstream agent can post a value that a downstream agent or fan-in join reads by key. See [Blackboard: shared state inside a flow run](blackboard.md).
