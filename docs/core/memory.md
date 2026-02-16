# Memory System

InitRunner's memory system gives agents two capabilities: **short-term session persistence** for resuming conversations, and **long-term semantic memory** for storing and recalling information across sessions.

Both are backed by a single database per agent using a configurable store backend (default: `sqlite-vec` for vector similarity search). The store is dimension-agnostic — embedding dimensions are auto-detected on first use.

## Quick Start

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: assistant
  description: Agent with long-term memory
spec:
  role: |
    You are a helpful assistant with long-term memory.
    Use the remember() tool to save important information.
    Use the recall() tool to search your memories before answering.
    Use the list_memories() tool to browse recent memories.
  model:
    provider: openai
    name: gpt-4o-mini
  memory:
    max_sessions: 10
    max_memories: 1000
    max_resume_messages: 20
```

```bash
# Interactive session (auto-saves history)
initrunner run role.yaml -i

# Resume where you left off
initrunner run role.yaml -i --resume

# Manage memory
initrunner memory clear role.yaml
initrunner memory export role.yaml -o memories.json
```

## Configuration

Memory is configured in the `spec.memory` section:

```yaml
spec:
  memory:
    max_sessions: 10          # default: 10
    max_memories: 1000        # default: 1000
    max_resume_messages: 20   # default: 20
    embeddings:
      provider: ""            # default: "" (derives from spec.model.provider)
      model: ""               # default: "" (uses provider default)
      base_url: ""            # default: "" (custom endpoint URL)
      api_key_env: ""         # default: "" (env var holding API key)
    store_backend: sqlite-vec # default: "sqlite-vec"
    store_path: null          # default: ~/.initrunner/memory/<agent-name>.db
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_sessions` | `int` | `10` | Maximum number of sessions to keep. Oldest sessions are pruned on REPL exit. |
| `max_memories` | `int` | `1000` | Maximum number of long-term memories to keep. Oldest memories are pruned when new ones are added. |
| `max_resume_messages` | `int` | `20` | Maximum number of messages loaded when using `--resume`. |
| `embeddings.provider` | `str` | `""` | Embedding provider. Empty string derives from `spec.model.provider`. |
| `embeddings.model` | `str` | `""` | Embedding model name. Empty string uses the provider default. |
| `embeddings.base_url` | `str` | `""` | Custom endpoint URL. Triggers OpenAI-compatible mode. |
| `embeddings.api_key_env` | `str` | `""` | Env var name holding the API key for custom endpoints. Empty uses provider default. |
| `store_backend` | `str` | `"sqlite-vec"` | Memory store backend. Currently only `sqlite-vec` is supported. |
| `store_path` | `str \| null` | `null` | Custom path for the memory database. Default: `~/.initrunner/memory/<agent-name>.db`. |

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

## Long-Term: Semantic Memory

When `spec.memory` is configured, three tools are auto-registered for the agent:

### `remember(content: str, category: str = "general") -> str`

Stores a piece of information in long-term memory with a semantic embedding for later retrieval.

- The `category` is sanitized: lowercased, non-alphanumeric characters replaced with underscores.
- An embedding is generated from the content using the configured embedding model.
- After storing, memories are pruned to `max_memories` (oldest removed).
- Returns a confirmation string with the memory ID and category.

### `recall(query: str, top_k: int = 5) -> str`

Searches long-term memory by semantic similarity.

- Generates an embedding from the query.
- Finds the `top_k` most similar memories using vector search.
- Returns results formatted as:

```
[Category: preferences | Score: 0.912 | 2025-06-01T10:30:00+00:00]
The user prefers dark mode and vim keybindings.

---

[Category: projects | Score: 0.845 | 2025-06-01T09:15:00+00:00]
Working on a React dashboard for the analytics team.
```

The score is `1 - distance` (higher is more similar).

### `list_memories(category: str | None = None, limit: int = 20) -> str`

Lists recent memories, optionally filtered by category. Returns entries formatted as:

```
[preferences] (2025-06-01T10:30:00+00:00) The user prefers dark mode.
[projects] (2025-06-01T09:15:00+00:00) Working on a React dashboard.
```

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

Indexed on `category` for filtered queries.

### `memories_vec`

Virtual table for vector similarity search (created lazily on first `remember()` call):

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
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `role_file` | `Path` | *(required)* | Path to the role YAML file. |
| `--sessions-only` | `bool` | `false` | Only clear session history. |
| `--memories-only` | `bool` | `false` | Only clear long-term memories. |
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
    "created_at": "2025-06-01T10:30:00+00:00"
  }
]
```

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
