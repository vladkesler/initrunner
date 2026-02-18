# Delegation — Agent-Calls-Agent

Delegation lets an agent invoke other agents as tool calls. A parent agent sees tools like `delegate_to_summarizer(prompt)` and can call them during execution. The sub-agent runs independently (fresh context, no history inheritance), and its output is returned as the tool result.

Delegation supports two modes:
- **Inline** — sub-agent is loaded and run in the same process (local dev, tests)
- **MCP** — sub-agent is called via HTTP to a remote `initrunner serve` instance (k8s, distributed)

Switching modes is a config change — the LLM sees the same tool interface regardless.

## Quick Example

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: coordinator
  description: Coordinates research and summarization
spec:
  role: |
    You are a coordinator. Use delegate_to_researcher to gather information,
    then use delegate_to_summarizer to create a summary.
  model:
    provider: openai
    name: gpt-5-mini
  tools:
    - type: delegate
      agents:
        - name: researcher
          role_file: ./roles/researcher.yaml
          description: "Researches topics in depth"
        - name: summarizer
          role_file: ./roles/summarizer.yaml
          description: "Summarizes long text concisely"
      mode: inline
      max_depth: 3
      timeout_seconds: 120
```

```bash
initrunner run coordinator.yaml -p "Research and summarize recent advances in fusion energy"
```

## Configuration

The `delegate` tool type is configured in `spec.tools` alongside other tool types (filesystem, http, mcp, custom).

```yaml
tools:
  - type: delegate
    agents:            # required — list of agent references
      - name: agent-a
        role_file: ./roles/agent-a.yaml
        description: "Does A"
      - name: agent-b
        role_file: ./roles/agent-b.yaml
        description: "Does B"
    mode: inline       # default: "inline" — or "mcp"
    max_depth: 3       # default: 3
    timeout_seconds: 120  # default: 120
    shared_memory:     # optional, inline mode only
      store_path: ./shared-memory.db
      max_memories: 1000
```

### Top-Level Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `"delegate"` | *(required)* | Discriminator for the delegate tool type. |
| `agents` | `list[DelegateAgentRef]` | *(required)* | List of agents that can be delegated to. |
| `mode` | `"inline" \| "mcp"` | `"inline"` | Execution mode. `inline` runs agents in-process; `mcp` calls remote services via HTTP. |
| `max_depth` | `int` | `3` | Maximum delegation depth. Prevents infinite recursion when agents delegate to each other. |
| `timeout_seconds` | `int` | `120` | Timeout in seconds for each delegation call. |
| `shared_memory` | `DelegateSharedMemory \| null` | `null` | Shared memory config for sub-agents (inline mode only). |

### Agent Reference Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | *(required)* | Agent name. Becomes part of the tool name: `delegate_to_{name}`. |
| `role_file` | `str \| null` | `null` | Path to the agent's role YAML file. **Required** in `inline` mode. Resolved relative to the parent role file's directory. |
| `url` | `str \| null` | `null` | Base URL of the agent's `initrunner serve` endpoint. **Required** in `mcp` mode. |
| `description` | `str` | `""` | Tool description shown to the LLM. Should clearly explain what this agent does. |
| `headers_env` | `dict[str, str]` | `{}` | Maps HTTP header names to environment variable names. Only used in `mcp` mode. Values are resolved at call time. |

## Inline Mode

In inline mode, sub-agents are loaded from local role YAML files and run in the same process. This is the simplest setup for development and testing.

```yaml
tools:
  - type: delegate
    agents:
      - name: summarizer
        role_file: ./roles/summarizer.yaml
        description: "Summarizes long text"
      - name: researcher
        role_file: ./roles/researcher.yaml
        description: "Researches topics"
    mode: inline
    max_depth: 3
```

### Path Resolution

The `role_file` path is resolved relative to the **parent role file's directory**, not the current working directory. Given this directory structure:

```
project/
  roles/
    coordinator.yaml    # has delegate tool with role_file: ./researcher.yaml
    researcher.yaml
```

Running `initrunner run project/roles/coordinator.yaml` correctly resolves `./researcher.yaml` to `project/roles/researcher.yaml`.

### How It Works

1. The parent agent's LLM calls `delegate_to_researcher(prompt="...")`
2. InitRunner loads `researcher.yaml` and builds a fresh agent
3. The sub-agent runs with the given prompt (no history from the parent)
4. The sub-agent's output text is returned as the tool result
5. The parent agent continues with the result

Sub-agents share the audit database (`~/.initrunner/audit.db`) with the parent. SQLite WAL mode handles concurrent writes safely.

## MCP Mode

In MCP mode, sub-agents are called via HTTP POST to running `initrunner serve` instances. This is designed for distributed deployment (k8s, multi-host).

```yaml
tools:
  - type: delegate
    agents:
      - name: summarizer
        url: http://summarizer:8000
        description: "Summarizes long text"
      - name: researcher
        url: http://researcher:8000
        description: "Researches topics"
        headers_env:
          Authorization: RESEARCHER_AUTH_TOKEN
    mode: mcp
    timeout_seconds: 120
```

### How It Works

1. The parent agent's LLM calls `delegate_to_summarizer(prompt="...")`
2. InitRunner sends an HTTP POST to `http://summarizer:8000/v1/chat/completions` with the prompt
3. The response is parsed (OpenAI-compatible format) and the content is returned as the tool result
4. The parent agent continues with the result

### Authentication

The `headers_env` field maps header names to environment variable names. Values are resolved at call time, supporting rotating tokens:

```yaml
agents:
  - name: researcher
    url: http://researcher:8000
    headers_env:
      Authorization: MY_AUTH_TOKEN    # reads $MY_AUTH_TOKEN at call time
      X-API-Key: RESEARCHER_API_KEY   # reads $RESEARCHER_API_KEY at call time
```

Missing environment variables result in empty header values (the header is omitted).

### Starting Remote Agents

Each remote agent must be running as an `initrunner serve` instance:

```bash
# Terminal 1: Start researcher agent
initrunner serve roles/researcher.yaml --host 0.0.0.0 --port 8000

# Terminal 2: Start summarizer agent
initrunner serve roles/summarizer.yaml --host 0.0.0.0 --port 8001

# Terminal 3: Run coordinator
initrunner run coordinator.yaml -p "Research and summarize AI safety"
```

See [Server](../interfaces/server.md) for details on the serve command.

## Depth Tracking

Delegation depth is tracked per-thread to prevent infinite recursion. When agent A delegates to agent B, and B delegates to C, the depth is 2. If the depth exceeds `max_depth`, the delegation fails with an error message.

```yaml
tools:
  - type: delegate
    agents:
      - name: sub-agent
        role_file: ./sub.yaml
    max_depth: 3    # allows parent → child → grandchild → great-grandchild
```

The delegation chain is tracked and included in error messages:

```
[DELEGATION ERROR] Delegation depth 4 exceeds max_depth 3 (chain: coordinator -> researcher -> analyst -> deep-agent)
```

## Shared Memory

When `shared_memory` is configured on a delegate tool, all inline sub-agents share a single memory database. One agent's `remember()` call is visible to another agent's `recall()`.

```yaml
tools:
  - type: delegate
    agents:
      - name: researcher
        role_file: ./roles/researcher.yaml
        description: "Researches topics"
      - name: writer
        role_file: ./roles/writer.yaml
        description: "Writes content"
    mode: inline
    shared_memory:
      store_path: ./shared-memory.db
      max_memories: 500
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `store_path` | `str` | *(required)* | Path to the shared memory database. |
| `max_memories` | `int` | `1000` | Maximum number of memories in the shared store. |

### Behavior

At invocation time, `apply_shared_memory()` patches each sub-agent's role definition — overriding `store_path` and `max_memories` if the role already has `memory:` configured, or injecting a `MemoryConfig` if it doesn't. The sub-agent then has access to `remember()`, `recall()`, and `list_memories()` tools backed by the shared store.

Shared memory only applies to **inline** mode. MCP agents manage their own memory independently.

### Parent Agent

The parent agent is **not** automatically included in the shared store. If the parent should also share memory with its sub-agents, set the same `store_path` in the parent role's own `memory:` config:

```yaml
spec:
  memory:
    store_path: ./shared-memory.db
  tools:
    - type: delegate
      shared_memory:
        store_path: ./shared-memory.db
```

### Embedding Consistency

All agents sharing a memory store must use embedding models with the same dimensions. Mismatched dimensions will raise a `DimensionMismatchError`. The store also tracks the embedding model identity, so switching models across shared stores is caught even when dimensions happen to match (raises `EmbeddingModelChangedError`).

## Error Handling

Delegation errors are returned as tool results prefixed with `[DELEGATION ERROR]`. This convention allows the LLM to distinguish system failures from normal agent output and react accordingly (e.g., retry, use a different agent, or inform the user).

Error cases:
- **Load failure**: `[DELEGATION ERROR] Failed to load agent from ./missing.yaml: Cannot read ...`
- **Depth exceeded**: `[DELEGATION ERROR] Delegation depth 4 exceeds max_depth 3 (chain: ...)`
- **Agent failure**: `[DELEGATION ERROR] Agent 'summarizer' failed: API limit exceeded`
- **Timeout**: `[DELEGATION ERROR] Connection timed out to agent 'summarizer' at http://...`
- **HTTP error**: `[DELEGATION ERROR] HTTP 500 from agent 'summarizer': Internal Server Error`

Delegation errors **never raise exceptions** — they always return error strings so the parent agent can handle them gracefully.

## Distributed Deployment (k8s)

The same configs work locally (inline mode) and distributed (MCP mode) with only a mode switch and URLs:

```
Local dev:                           k8s / distributed:
+----------------------+             +---------+ +---------+
| single process       |             |researcher| |summariz.|
| parent agent         |             | Pod      | | Pod     |
|  +-- researcher      |    ==>      | serve    | | serve   |
|  +-- summarizer      |             | :8000    | | :8000   |
|      (all inline)    |             +----+-----+ +----+----+
+----------------------+                  |            |
                                     +----+------------+----+
                                     | coordinator-runner   |
                                     | Job/CronJob          |
                                     | mode: mcp            |
                                     | agents by URL        |
                                     +----------------------+
```

- Each agent runs as `initrunner serve <role.yaml>` in its own Deployment + Service
- The coordinator runs with `mode: mcp` targeting agent service URLs
- Audit stays local per pod (SQLite per process)
- No k8s-specific code — users bring their own manifests

### Example k8s Coordinator Config

```yaml
# coordinator.yaml (for k8s deployment)
tools:
  - type: delegate
    agents:
      - name: researcher
        url: http://researcher-svc:8000
        description: "Researches topics"
      - name: summarizer
        url: http://summarizer-svc:8000
        description: "Summarizes text"
    mode: mcp
    timeout_seconds: 300
```

## Registered Functions

For each agent in the `agents` list, one tool is registered:

- **`delegate_to_{name}(prompt: str) -> str`** — Send a prompt to the named agent and return its output. The description comes from the agent ref's `description` field.

## Validation

The `validate` command displays delegate tool configuration:

```bash
initrunner validate coordinator.yaml
```

```
+-------------------+-------------------------------------------+
| Field             | Value                                     |
+-------------------+-------------------------------------------+
| Tools             | delegate (inline): researcher, summarizer |
+-------------------+-------------------------------------------+
```

Validation enforces:
- Inline mode: every agent must have `role_file`
- MCP mode: every agent must have `url`
- At least one agent in the `agents` list
