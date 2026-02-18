# Memory System

InitRunner's memory system gives agents three capabilities: **short-term session persistence** for resuming conversations, **long-term typed memory** (episodic, semantic, and procedural), and **automatic consolidation** that extracts durable facts from episodic records.

- **Semantic memory** — facts and knowledge (e.g. "the user prefers dark mode")
- **Episodic memory** — what happened during tasks (e.g. "deployed v2.1 to staging, rollback needed")
- **Procedural memory** — learned policies and patterns (e.g. "always run tests before deploying")

All memory types are backed by a single database per agent using a configurable store backend (default: `sqlite-vec` for vector similarity search). The store is dimension-agnostic — embedding dimensions are auto-detected on first use.

## Quick Start

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: assistant
  description: Agent with rich memory
spec:
  role: |
    You are a helpful assistant with long-term memory.
    Use the remember() tool to save important facts.
    Use the recall() tool to search your memories before answering.
    Use the learn_procedure() tool to record useful patterns.
  model:
    provider: openai
    name: gpt-5-mini
  memory:
    max_sessions: 10
    max_resume_messages: 20
    semantic:
      max_memories: 1000
    episodic:
      max_episodes: 500
    procedural:
      max_procedures: 100
    consolidation:
      enabled: true
      interval: after_session
```

Minimal backward-compatible config still works — a bare `memory:` section with just `max_memories` enables semantic memory with defaults for all other types:

```yaml
  memory:
    max_memories: 1000
```

```bash
# Interactive session (auto-saves history)
initrunner run role.yaml -i

# Resume where you left off
initrunner run role.yaml -i --resume

# Manage memory
initrunner memory list role.yaml
initrunner memory list role.yaml --type episodic
initrunner memory clear role.yaml
initrunner memory consolidate role.yaml
initrunner memory export role.yaml -o memories.json
```

## Memory Types

### Semantic

Facts and knowledge extracted from conversations or explicitly saved by the agent. This is the default memory type and the one used by the `remember()` tool.

Semantic memories are retrieved via `recall()` and are also the output of the consolidation process (extracting durable facts from episodic records).

### Episodic

Records of what happened during agent tasks — outcomes, decisions, errors, and events. Episodic memories are created in three ways:

1. The agent calls `record_episode()` explicitly.
2. Autonomous runs auto-capture an episode when `finish_task` is called (see [Episodic Auto-Capture](#episodic-auto-capture)).
3. Daemon trigger executions auto-capture an episode after each run.

Episodic memories serve as raw material for consolidation: the consolidation process reads unconsolidated episodes, extracts semantic facts via an LLM, and marks them as consolidated.

### Procedural

Learned policies, patterns, and best practices. Procedural memories are created via the `learn_procedure()` tool and are automatically injected into the system prompt on every agent run (see [Procedural Memory Injection](#procedural-memory-injection)).

Use procedural memory for instructions the agent should always follow, like "always confirm before deleting files" or "use snake_case for Python variables".

## Configuration

Memory is configured in the `spec.memory` section:

```yaml
spec:
  memory:
    max_sessions: 10              # default: 10
    max_memories: 1000            # deprecated — use semantic.max_memories
    max_resume_messages: 20       # default: 20
    store_backend: sqlite-vec     # default: "sqlite-vec"
    store_path: null              # default: ~/.initrunner/memory/<agent-name>.db
    embeddings:
      provider: ""                # default: "" (derives from spec.model.provider)
      model: ""                   # default: "" (uses provider default)
      base_url: ""                # default: "" (custom endpoint URL)
      api_key_env: ""             # default: "" (env var holding API key)
    episodic:
      enabled: true               # default: true
      max_episodes: 500           # default: 500
    semantic:
      enabled: true               # default: true
      max_memories: 1000          # default: 1000
    procedural:
      enabled: true               # default: true
      max_procedures: 100         # default: 100
    consolidation:
      enabled: true               # default: true
      interval: after_session     # default: "after_session"
      max_episodes_per_run: 20    # default: 20
      model_override: null        # default: null (uses agent's model)
```

### Top-Level Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_sessions` | `int` | `10` | Maximum number of sessions to keep. Oldest sessions are pruned on REPL exit. |
| `max_memories` | `int` | `1000` | **Deprecated.** Use `semantic.max_memories`. If set to a non-default value and `semantic.max_memories` is at default, the value is synced for backward compatibility. |
| `max_resume_messages` | `int` | `20` | Maximum number of messages loaded when using `--resume`. |
| `store_backend` | `str` | `"sqlite-vec"` | Memory store backend. Currently only `sqlite-vec` is supported. |
| `store_path` | `str \| null` | `null` | Custom path for the memory database. Default: `~/.initrunner/memory/<agent-name>.db`. |

### Embedding Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `embeddings.provider` | `str` | `""` | Embedding provider. Empty string derives from `spec.model.provider`. |
| `embeddings.model` | `str` | `""` | Embedding model name. Empty string uses the provider default. |
| `embeddings.base_url` | `str` | `""` | Custom endpoint URL. Triggers OpenAI-compatible mode. |
| `embeddings.api_key_env` | `str` | `""` | Env var name holding the embedding API key. Works for both standard providers and custom endpoints. When empty, the default key for the resolved provider is used (e.g. `OPENAI_API_KEY` for OpenAI/Anthropic, `GOOGLE_API_KEY` for Google). |

### Episodic Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `episodic.enabled` | `bool` | `true` | Enable episodic memory type and the `record_episode()` tool. |
| `episodic.max_episodes` | `int` | `500` | Maximum episodic memories to keep. Oldest are pruned when new ones are added. |

### Semantic Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `semantic.enabled` | `bool` | `true` | Enable semantic memory type and the `remember()` tool. |
| `semantic.max_memories` | `int` | `1000` | Maximum semantic memories to keep. Oldest are pruned when new ones are added. |

### Procedural Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `procedural.enabled` | `bool` | `true` | Enable procedural memory type and the `learn_procedure()` tool. |
| `procedural.max_procedures` | `int` | `100` | Maximum procedural memories to keep. Oldest are pruned when new ones are added. |

### Consolidation Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `consolidation.enabled` | `bool` | `true` | Enable automatic consolidation of episodic memories into semantic facts. |
| `consolidation.interval` | `str` | `"after_session"` | When to run consolidation: `after_session` (on REPL exit), `after_autonomous` (on autonomous loop exit), or `manual` (CLI only). |
| `consolidation.max_episodes_per_run` | `int` | `20` | Maximum unconsolidated episodes to process per consolidation run. |
| `consolidation.model_override` | `str \| null` | `null` | Model to use for consolidation LLM calls. Defaults to the agent's model. |

## Short-Term: Session Persistence

Session persistence saves REPL conversation history to SQLite after each turn, enabling the `--resume` flag.

### How It Works

1. During an interactive REPL session, the full PydanticAI message history is saved after every turn.
2. Each session gets a unique ID (random 12-character hex).
3. When `--resume` is used, the most recent session for the agent is loaded.
4. Only the last `max_resume_messages` messages are loaded to stay within context window limits.
5. If the loaded history starts with a `ModelResponse` (which is invalid), leading `ModelResponse` messages are skipped until a `ModelRequest` is found.

### Active Session History Limit

During an active REPL or TUI session, message history is trimmed to `max_resume_messages * 2` (default: 40 messages) after each turn. This prevents unbounded growth during long conversations. The trimming:

- Keeps the most recent messages (sliding window).
- Ensures the history starts with a `ModelRequest` (never a `ModelResponse`).
- Applies in both the CLI REPL (`initrunner run -i`) and the TUI chat screen.

### System Prompt Filtering

When saving sessions, all `SystemPromptPart` entries are stripped from `ModelRequest` messages. This ensures that:

- Stale system prompts from a previous `role.yaml` version don't persist.
- The current `spec.role` is always used when resuming.
- Session data is more compact.

### Session Pruning

Old sessions beyond `max_sessions` are deleted (oldest first). Pruning runs automatically:
- **REPL mode**: on session exit.
- **Daemon mode**: after each trigger execution (when memory is configured).

This keeps the memory database from growing indefinitely.

### Never-Raises Guarantee

Session saving follows a never-raises pattern: if writing to the database fails, the error is printed to stderr but the agent continues running. This prevents database issues from crashing interactive sessions.

## Long-Term: Memory Tools

When `spec.memory` is configured, up to five tools are auto-registered depending on which memory types are enabled.

### `remember(content: str, category: str = "general") -> str`

Stores a piece of information as a **semantic** memory with an embedding for later retrieval. Only registered when `semantic.enabled` is `true`.

- The `category` is sanitized: lowercased, non-alphanumeric characters replaced with underscores.
- An embedding is generated from the content using the configured embedding model.
- After storing, memories are pruned to `semantic.max_memories` (oldest removed).
- Returns a confirmation string with the memory ID and category.

### `recall(query: str, top_k: int = 5, memory_types: list[str] | None = None) -> str`

Searches all memory types by semantic similarity. Always registered when `spec.memory` is configured.

- Generates an embedding from the query.
- Finds the `top_k` most similar memories using vector search.
- Pass `memory_types` to filter by type (e.g. `["semantic", "procedural"]`).
- Returns results formatted as:

```
[Type: semantic | Category: preferences | Score: 0.912 | 2025-06-01T10:30:00+00:00]
The user prefers dark mode and vim keybindings.

---

[Type: episodic | Category: autonomous_run | Score: 0.845 | 2025-06-01T09:15:00+00:00]
Deployed v2.1 to staging. Tests passed but rollback was needed due to memory leak.
```

The score is `1 - distance` (higher is more similar).

### `list_memories(category: str | None = None, limit: int = 20, memory_type: str | None = None) -> str`

Lists recent memories, optionally filtered by category or type. Always registered when `spec.memory` is configured. Returns entries formatted as:

```
[semantic:preferences] (2025-06-01T10:30:00+00:00) The user prefers dark mode.
[episodic:autonomous_run] (2025-06-01T09:15:00+00:00) Deployed v2.1 to staging.
```

### `learn_procedure(content: str, category: str = "general") -> str`

Stores a learned procedure, policy, or pattern as a **procedural** memory. Only registered when `procedural.enabled` is `true`.

- The `category` is sanitized the same way as `remember()`.
- After storing, memories are pruned to `procedural.max_procedures` (oldest removed).
- Procedural memories are auto-injected into the system prompt on future runs (see [Procedural Memory Injection](#procedural-memory-injection)).

### `record_episode(content: str, category: str = "general") -> str`

Records an episode — what happened during a task or interaction. Only registered when `episodic.enabled` is `true`.

- The `category` is sanitized the same way as `remember()`.
- After storing, memories are pruned to `episodic.max_episodes` (oldest removed).
- Use this to capture outcomes, decisions made, errors encountered, or other events.

## Episodic Auto-Capture

In autonomous and daemon modes, episodic memories are captured automatically — the agent does not need to call `record_episode()` explicitly.

### Autonomous Mode

When `finish_task` is called with a summary, the summary is persisted as an episodic memory with category `autonomous_run`. This happens after each autonomous loop iteration that produces a result.

### Daemon Mode

After each trigger execution, the run result summary is captured as an episodic memory. The metadata includes the trigger type (e.g. `cron`, `file_watch`, `webhook`).

### Interactive Mode

Interactive REPL sessions do **not** auto-capture episodic memories. Use the `record_episode()` tool explicitly if needed.

### Never-Raises Guarantee

Episodic auto-capture follows a never-raises pattern: if embedding or storage fails, a warning is logged but the agent run is not affected.

## Consolidation

Consolidation is the process of extracting durable semantic facts from episodic memories using an LLM. It reads unconsolidated episodes, sends them to the model with a structured prompt, parses `CATEGORY: content` lines from the output, and stores each extracted fact as a new semantic memory.

### When It Runs

| `consolidation.interval` | Trigger |
|---------------------------|---------|
| `after_session` | On interactive REPL exit |
| `after_autonomous` | On autonomous loop exit |
| `manual` | Only via `initrunner memory consolidate` CLI |

Consolidation can always be triggered manually via the CLI regardless of the `interval` setting.

### How It Works

1. Fetch up to `max_episodes_per_run` unconsolidated episodic memories (oldest first).
2. Format them into a prompt and send to the consolidation model.
3. Parse `CATEGORY: content` lines from the LLM output.
4. Store each extracted fact as a semantic memory with `metadata: {"source": "consolidation"}`.
5. Mark the processed episodes as consolidated (sets `consolidated_at` timestamp).

### Failure Semantics

Consolidation follows a never-raises pattern. If the LLM call or storage fails, a warning is logged and `0` is returned. Episodes are only marked as consolidated after all semantic memories are successfully stored.

## Procedural Memory Injection

When `procedural.enabled` is `true`, procedural memories are automatically loaded into the system prompt on every agent run. Up to 20 of the most recent procedural memories are injected as a `## Learned Procedures and Policies` section:

```
## Learned Procedures and Policies

- [deployment] Always run tests before deploying to production
- [code_review] Check for SQL injection in any database queries
- [communication] Summarize changes in bullet points for the user
```

This injection happens transparently — the agent sees these as part of its system prompt and follows them as standing instructions.

## Database Schema

The memory database contains four tables:

### `store_meta`

Key-value metadata (e.g. dimensions, embedding model):

| Column | Type | Description |
|--------|------|-------------|
| `key` | `TEXT PRIMARY KEY` | Metadata key (e.g. `"dimensions"`, `"embedding_model"`) |
| `value` | `TEXT` | Metadata value (e.g. `"1536"`, `"openai:text-embedding-3-small"`) |

### `sessions`

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER PRIMARY KEY` | Auto-incrementing row ID |
| `session_id` | `TEXT` | Unique session identifier |
| `agent_name` | `TEXT` | Agent name from `metadata.name` |
| `timestamp` | `TEXT` | ISO 8601 timestamp |
| `messages_json` | `TEXT` | JSON-serialized PydanticAI message history |

Indexed on `(agent_name, timestamp DESC)` for fast latest-session lookups.

### `memories`

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER PRIMARY KEY` | Auto-incrementing memory ID |
| `content` | `TEXT` | Memory content |
| `category` | `TEXT` | Category label (default: `"general"`) |
| `created_at` | `TEXT` | ISO 8601 creation timestamp |
| `memory_type` | `TEXT` | One of `episodic`, `semantic`, `procedural`. Default: `semantic`. Has a `CHECK` constraint. |
| `metadata_json` | `TEXT` | Optional JSON metadata (e.g. `{"trigger_type": "cron"}`, `{"source": "consolidation"}`) |
| `consolidated_at` | `TEXT` | ISO 8601 timestamp when the episode was consolidated. `NULL` for unconsolidated or non-episodic memories. |

Indexes:
- `idx_memories_category` on `(category)`
- `idx_memories_type` on `(memory_type)`
- `idx_memories_type_category` on `(memory_type, category)`

Existing databases are auto-migrated: the `memory_type`, `metadata_json`, and `consolidated_at` columns are added via `ALTER TABLE` if missing, and new indexes are created.

### `memories_vec`

Virtual table for vector similarity search (created lazily on first `remember()`, `learn_procedure()`, or `record_episode()` call):

| Column | Type | Description |
|--------|------|-------------|
| `rowid` | `INTEGER` | Matches `memories.id` |
| `embedding` | `float[N]` | Vector embedding (dimension auto-detected from model) |

## CLI Commands

### `memory clear`

Clear memory data for an agent.

```bash
initrunner memory clear role.yaml              # clear all (prompts for confirmation)
initrunner memory clear role.yaml --force      # skip confirmation
initrunner memory clear role.yaml --sessions-only   # clear only sessions
initrunner memory clear role.yaml --memories-only   # clear only long-term memories
initrunner memory clear role.yaml --type semantic    # clear only semantic memories
initrunner memory clear role.yaml --type episodic    # clear only episodic memories
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `role_file` | `Path` | *(required)* | Path to the role YAML file. |
| `--sessions-only` | `bool` | `false` | Only clear session history. |
| `--memories-only` | `bool` | `false` | Only clear long-term memories. |
| `--type` | `str` | `null` | Clear only a specific memory type: `episodic`, `semantic`, or `procedural`. |
| `--force` | `bool` | `false` | Skip the confirmation prompt. |

If the memory store database doesn't exist, the command prints "No memory store found." and exits.

### `memory export`

Export all long-term memories to a JSON file.

```bash
initrunner memory export role.yaml                    # exports to memories.json
initrunner memory export role.yaml -o my-export.json  # custom output path
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `role_file` | `Path` | *(required)* | Path to the role YAML file. |
| `-o, --output` | `Path` | `memories.json` | Output JSON file path. |

The exported JSON is an array of objects:

```json
[
  {
    "id": 1,
    "content": "The user prefers dark mode.",
    "category": "preferences",
    "created_at": "2025-06-01T10:30:00+00:00",
    "memory_type": "semantic",
    "metadata": null
  },
  {
    "id": 2,
    "content": "Deployed v2.1 to staging successfully.",
    "category": "autonomous_run",
    "created_at": "2025-06-02T14:00:00+00:00",
    "memory_type": "episodic",
    "metadata": {"trigger_type": "cron"}
  }
]
```

### `memory list`

List stored memories for an agent.

```bash
initrunner memory list role.yaml                      # list all (default limit: 20)
initrunner memory list role.yaml --type procedural     # filter by type
initrunner memory list role.yaml --category deployment # filter by category
initrunner memory list role.yaml --limit 50            # custom limit
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `role_file` | `Path` | *(required)* | Path to the role YAML file. |
| `--type` | `str` | `null` | Filter by memory type: `episodic`, `semantic`, or `procedural`. |
| `--category` | `str` | `null` | Filter by category. |
| `--limit` | `int` | `20` | Maximum number of results. |

### `memory consolidate`

Manually run memory consolidation — extract semantic facts from unconsolidated episodic memories.

```bash
initrunner memory consolidate role.yaml
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `role_file` | `Path` | *(required)* | Path to the role YAML file. |

This command always runs consolidation regardless of the `consolidation.interval` setting. It processes up to `consolidation.max_episodes_per_run` unconsolidated episodes.

## Store Location

```
~/.initrunner/memory/<agent-name>.db
```

Override with `store_path` in the memory config. The directory is created automatically if it doesn't exist.

## Shared Memory

Multiple agents can share a single memory database, allowing one agent's `remember()` calls to be visible to another agent's `recall()`. There are two mechanisms:

- **Compose**: set `spec.shared_memory.enabled: true` in a compose definition to give all services a common store. See [Agent Composer: Shared Memory](../orchestration/agent_composer.md#shared-memory).
- **Delegation**: set `shared_memory.store_path` on a delegate tool to share memory between inline sub-agents. See [Delegation: Shared Memory](../orchestration/delegation.md#shared-memory).

Both work by overriding `store_path` (and optionally `max_memories`) on each agent's memory config at startup, pointing them at the same SQLite database.

Concurrent access from multiple service threads is safe — SQLite WAL mode and `busy_timeout` handle contention without additional locking.

## Dimension & Model Identity Tracking

The memory store tracks embedding dimensions and model identity the same way as the [ingestion store](ingestion.md#dimension--model-identity-tracking):

- **Session-only usage**: the store works without knowing dimensions — the `memories_vec` table is created lazily on the first `remember()` call.
- **First `remember()` call**: dimensions and the embedding model identity are detected and written to `store_meta`.
- **Subsequent opens**: dimensions and model identity are read from `store_meta`. An `EmbeddingModelChangedError` is raised if the model has changed; a `DimensionMismatchError` is raised if dimensions conflict.
- **Migration**: pre-existing stores default to 1536.

See [Ingestion: Dimension & Model Identity Tracking](ingestion.md#dimension--model-identity-tracking) for details on the model identity format and interactive prompt behavior.

## Scaffold a Memory-Enabled Role

```bash
initrunner init --name assistant --template memory
```

This generates a `role.yaml` with `memory` pre-configured and a system prompt that instructs the agent to use `remember()`, `recall()`, and `list_memories()`.

## Embedding Models

Memory uses the same embedding provider resolution as [Ingestion](ingestion.md#embedding-models):

1. `memory.embeddings.model` — If set, used directly.
2. `memory.embeddings.provider` — Used to look up the default model.
3. `spec.model.provider` — Falls back to the agent's model provider.

### Provider Defaults

| Provider | Default Embedding Model |
|----------|------------------------|
| `openai` | `openai:text-embedding-3-small` |
| `anthropic` | `openai:text-embedding-3-small` |
| `google` | `google:text-embedding-004` |
| `ollama` | `ollama:nomic-embed-text` |
