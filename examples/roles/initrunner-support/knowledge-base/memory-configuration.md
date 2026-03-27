# Memory Configuration

InitRunner agents can remember information across sessions using three types of long-term memory: semantic (facts), episodic (events), and procedural (rules). Memory is stored in a local LanceDB vector database and searched by similarity.


## Quick start

Add a `memory` section to your role.yaml:

```yaml
spec:
  memory:
    max_sessions: 10
    max_resume_messages: 20
    semantic:
      enabled: true
      max_memories: 1000
    episodic:
      enabled: true
      max_episodes: 500
    procedural:
      enabled: true
      max_procedures: 100
    consolidation:
      enabled: true
      interval: after_session
```

For chat mode, memory is enabled by default with no configuration needed:

```bash
initrunner run              # memory on by default
initrunner run --resume     # resume with recalled memories
initrunner run --no-memory  # disable memory
```


## Memory types

### Semantic memory (facts and knowledge)

Stores facts, preferences, and knowledge the user shares. Use `remember()` to save and `recall()` to search.

Examples: "User prefers Anthropic models", "Project uses PostgreSQL", "Deploy target is AWS ECS".

### Episodic memory (what happened)

Records events, outcomes, and decisions. Use `record_episode()` to save.

Examples: "Successfully configured RAG with paragraph chunking", "Resolved API key error by running setup", "Deployed v2.0 to production".

### Procedural memory (rules and workflows)

Stores policies and best practices the agent should follow. Procedural memories are automatically injected into the system prompt on session start.

Examples: "Always suggest uv over pip", "Confirm before destructive operations", "Use metric units".


## Memory tools

| Tool | Signature | Memory type | Purpose |
|------|-----------|-------------|---------|
| `remember()` | `(content, category="general")` | Semantic | Save a fact or preference |
| `recall()` | `(query, top_k=5, memory_types=None)` | All | Search by similarity |
| `record_episode()` | `(content, category="general")` | Episodic | Record an event or outcome |
| `learn_procedure()` | `(content, category="general")` | Procedural | Save a rule or workflow |
| `list_memories()` | `(category=None, limit=20, type=None)` | All | Browse stored memories |

The `recall()` tool searches across all memory types by default. You can narrow the search with `memory_types=["semantic"]` or `memory_types=["procedural", "episodic"]`.


## Session persistence and resume

Session history is saved after each REPL turn. To resume a previous session:

```bash
initrunner run role.yaml -i --resume
```

On resume, InitRunner:
1. Loads the most recent message history (up to `max_resume_messages * 2` messages)
2. Auto-recalls relevant memories based on the conversation context
3. Uses the current `spec.role` system prompt (not the one from the saved session)

The `max_resume_messages` setting controls how many messages are loaded. Default is 20. Set higher for longer conversations, lower to save context window space.


## Configuration reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_sessions` | `int` | `10` | Sessions to keep (oldest pruned) |
| `max_resume_messages` | `int` | `20` | Messages loaded on `--resume` |
| `store_backend` | `str` | `"lancedb"` | Vector store backend |
| `store_path` | `str` or `null` | `null` | Custom store path |
| `embeddings.provider` | `str` | *(from model)* | Embedding provider override |
| `embeddings.model` | `str` | *(provider default)* | Embedding model override |
| `semantic.enabled` | `bool` | `true` | Enable semantic memory |
| `semantic.max_memories` | `int` | `1000` | Max semantic memories |
| `episodic.enabled` | `bool` | `true` | Enable episodic memory |
| `episodic.max_episodes` | `int` | `500` | Max episodic memories |
| `procedural.enabled` | `bool` | `true` | Enable procedural memory |
| `procedural.max_procedures` | `int` | `100` | Max procedural memories |
| `consolidation.enabled` | `bool` | `true` | Auto-consolidate episodes |
| `consolidation.interval` | `str` | `"after_session"` | When to consolidate |


## Consolidation

Consolidation extracts semantic facts from episodic memories using the agent's LLM. For example, if several episodes mention "deployed to AWS", consolidation creates a semantic memory: "Deployment target is AWS".

Consolidation intervals:
- `after_session` -- runs automatically when an interactive session ends
- `after_autonomous` -- runs after autonomous mode completes
- `manual` -- only when you run the CLI command

Manual consolidation:

```bash
initrunner memory consolidate role.yaml
```


## Memory CLI commands

```bash
# List memories
initrunner memory list role.yaml
initrunner memory list role.yaml --type semantic --category preference

# Clear memories
initrunner memory clear role.yaml
initrunner memory clear role.yaml --type episodic --force

# Export to JSON
initrunner memory export role.yaml -o memories.json

# Import from JSON
initrunner memory import role.yaml memories.json

# Run consolidation
initrunner memory consolidate role.yaml
```


## Store location

Memory is stored at:

```
~/.initrunner/memory/<agent-name>.lance
```

You can override this with `memory.store_path` in your role.yaml.


## Auto-capture behavior

| Run mode | Auto-capture |
|----------|-------------|
| Autonomous | `finish_task` summary saved as episodic memory |
| Daemon | Each run result saved as episodic memory |
| Interactive | No auto-capture (use `record_episode()` manually) |
