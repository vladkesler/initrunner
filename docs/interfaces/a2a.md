# A2A Server -- Agent-to-Agent Protocol

The `initrunner a2a serve` command exposes any agent as an [A2A (Agent-to-Agent)](https://google.github.io/A2A/) server. A2A is Google's open standard for AI agents to communicate across frameworks and vendors. This lets other A2A-compatible agents discover and invoke your InitRunner agents over HTTP.

## Quick Start

```bash
# Install the A2A extra
uv pip install initrunner[a2a]

# Start the server
initrunner a2a serve role.yaml

# With authentication
initrunner a2a serve role.yaml --api-key my-secret-key

# Custom host/port
initrunner a2a serve role.yaml --host 0.0.0.0 --port 9000
```

The server exposes:
- `/.well-known/agent-card.json` -- agent card (discovery)
- JSON-RPC endpoint at the root URL -- handles `message/send` and `tasks/get`

## CLI Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `role_file` | `Path` | *(required)* | Path to the role YAML file. |
| `--host` | `str` | `127.0.0.1` | Host to bind to. Use `0.0.0.0` to expose on all interfaces. |
| `--port` | `int` | `8000` | Port to listen on. |
| `--api-key` | `str` | `None` | API key for Bearer token authentication. When set, all endpoints except the agent card require `Authorization: Bearer <key>`. |
| `--cors-origin` | `str` | `None` | Allowed CORS origin. Can be repeated. |
| `--audit-db` | `Path` | `~/.initrunner/audit.db` | Path to audit database. |
| `--no-audit` | `bool` | `false` | Disable audit logging. |
| `--skill-dir` | `Path` | `None` | Extra skill search directory. |
| `--model` | `str` | `None` | Model alias or provider:model override. |

## How It Works

The A2A server uses [FastA2A](https://pydantic.dev/docs/ai/integrations/a2a/#fasta2a) (from PydanticAI) as the ASGI framework, with a custom worker that routes execution through InitRunner's executor. This means A2A-served agents get the same behavior as `--serve` agents:

- Input content validation
- Role guardrail usage limits
- Retry/timeout wrapping
- Output validation and serialization
- Audit logging
- Agent-principal context

### Agent Card

The agent card at `/.well-known/agent-card.json` is auto-generated from your role YAML:

```json
{
  "name": "researcher",
  "description": "Gathers and summarizes research from the web",
  "url": "http://localhost:8000",
  "version": "1.0.0"
}
```

### Conversation Context

A2A uses `context_id` to maintain conversation threads across multiple requests. When a client sends messages with the same `context_id`, the server preserves the full message history, enabling multi-turn conversations.

## Calling A2A Agents from a Role

Use the delegate tool with `mode: a2a` to call a remote A2A agent from within another agent:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: coordinator
spec:
  role: >
    You coordinate research tasks by delegating to specialized agents.
  model:
    provider: openai
    name: gpt-4o
  tools:
    - type: delegate
      mode: a2a
      timeout_seconds: 120
      agents:
        - name: research-agent
          url: http://research-server:8000
          description: Gathers and summarizes research from the web
        - name: analysis-agent
          url: http://analysis-server:8000
          description: Performs data analysis and generates reports
          headers_env:
            Authorization: ANALYSIS_AGENT_API_KEY
```

### How It Works

When the LLM calls `delegate_to_research_agent("find papers on transformers")`, InitRunner:

1. Sends a JSON-RPC `message/send` request to `http://research-server:8000`
2. If the task completes immediately, extracts the result from A2A artifacts
3. If the task is async (submitted/working), polls `tasks/get` with exponential backoff until completion or timeout
4. Returns the result text to the LLM

### Delegate Config Reference

The `mode: a2a` delegate config uses the same fields as `mode: mcp`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `mode` | `"a2a"` | Yes | Selects the A2A protocol. |
| `agents` | `list` | Yes | List of agent references. |
| `agents[].name` | `str` | Yes | Agent name (used in tool function name). |
| `agents[].url` | `str` | Yes | A2A server URL. |
| `agents[].description` | `str` | No | Description shown to the LLM. |
| `agents[].headers_env` | `dict` | No | Map of header name to environment variable name. |
| `timeout_seconds` | `int` | No | Timeout for the full request+polling cycle. Default: 120. |
| `max_depth` | `int` | No | Max delegation depth. Default: 3. |

### Error Handling

All errors are returned as strings prefixed with `[DELEGATION ERROR]` so the LLM can see and handle failures gracefully. Errors include:

- Task failed/rejected/canceled
- Timeout (connection or polling)
- HTTP errors
- JSON-RPC errors
- Policy denial (when agent authorization is configured)

## Comparison with Other Interfaces

| Feature | `--serve` (OpenAI) | `mcp serve` | `a2a serve` |
|---------|-------------------|-------------|-------------|
| Protocol | OpenAI chat completions | MCP (JSON-RPC) | A2A (JSON-RPC) |
| Discovery | Manual | MCP tool listing | Agent card at `/.well-known/agent-card.json` |
| Multi-turn | Server-side via `x-conversation-id` | Per-tool call | Via `context_id` |
| Agents per server | 1 | Multiple | 1 |
| Client tool | `delegate` mode `mcp` | Native MCP clients | `delegate` mode `a2a` |
| Use case | Drop-in OpenAI replacement | Tool sharing with AI IDEs | Cross-framework agent communication |
