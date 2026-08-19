# A2A Server -- Agent-to-Agent Protocol

The `initrunner a2a serve` command exposes any agent as an [A2A (Agent-to-Agent)](https://a2a-protocol.org/) 1.0 server. A2A is the Linux Foundation protocol for agents to discover and invoke each other across frameworks. Other A2A 1.0 clients can find your InitRunner agent at `/.well-known/agent-card.json` and call it over JSON-RPC.

InitRunner speaks **A2A 1.0 only**. There is no 0.3 compatibility mode. Clients and curl examples must send `A2A-Version: 1.0` on every JSON-RPC request. Method names are gRPC-style: `SendMessage`, `GetTask`, `CancelTask` (not `message/send` / `tasks/get`).

## Quick Start

```bash
# Install the A2A extra
uv pip install initrunner[a2a]

# Start the server
initrunner a2a serve role.yaml

# With authentication
initrunner a2a serve role.yaml --api-key my-secret-key

# Custom host/port. Binding a non-loopback host without --api-key fails closed:
# a key is generated and printed rather than serving the agent unauthenticated.
# Pass --url so the card advertises a dialable address (not http://0.0.0.0:9000).
initrunner a2a serve role.yaml --host 0.0.0.0 --port 9000 \
  --url http://agent.example:9000 --api-key my-secret-key
```

The server exposes:

- `GET /.well-known/agent-card.json` -- agent card (discovery; no auth)
- `POST /` -- JSON-RPC (`SendMessage`, `SendStreamingMessage`, `GetTask`, `CancelTask`, `SubscribeToTask`, …)

```bash
curl -s http://127.0.0.1:8000/.well-known/agent-card.json | jq .supportedInterfaces

curl -s http://127.0.0.1:8000/ \
  -H 'Content-Type: application/json' \
  -H 'A2A-Version: 1.0' \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "SendMessage",
    "params": {
      "message": {
        "role": "ROLE_USER",
        "messageId": "m1",
        "parts": [{"text": "hello"}]
      }
    }
  }' | jq .result.task.status
```

A request without `A2A-Version: 1.0` is treated as protocol 0.3 and rejected with JSON-RPC error `-32009`.

Token stream (SSE):

```bash
curl -N http://127.0.0.1:8000/ \
  -H 'Content-Type: application/json' \
  -H 'A2A-Version: 1.0' \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "SendStreamingMessage",
    "params": {
      "message": {
        "role": "ROLE_USER",
        "messageId": "m1",
        "parts": [{"text": "hello"}]
      }
    }
  }'
```

## CLI Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `role_file` | `Path` | *(required)* | Path to the role YAML file, or a [group file](../orchestration/groups.md) together with `--agent`. |
| `--agent` | `str` | `None` | Which member of a group to serve. A2A publishes one agent card per URL, so a group target requires it. |
| `--host` | `str` | `127.0.0.1` | Host to bind to. Use `0.0.0.0` to expose on all interfaces. |
| `--port` | `int` | `8000` | Port to listen on. |
| `--url` | `str` | `http://{host}:{port}` | Public URL written into the agent card. Required for a dialable card when `--host` is `0.0.0.0` or `::`. |
| `--api-key` | `str` | `None` | API key for Bearer token authentication. When set, all endpoints except the agent card require `Authorization: Bearer <key>`. Binding a non-loopback `--host` without a key fails closed — one is generated and printed so the JSON-RPC endpoint is never served unauthenticated off-host. |
| `--cors-origin` | `str` | `None` | Allowed CORS origin. Can be repeated. |
| `--audit-db` | `Path` | `~/.initrunner/audit.db` | Path to audit database. |
| `--no-audit` | `bool` | `false` | Disable audit logging. |
| `--skill-dir` | `Path` | `None` | Extra skill search directory. |
| `--model` | `str` | `None` | Model alias or provider:model override. |

## How It Works

The server is a Starlette app assembled from `a2a-sdk` 1.0 routes (`create_agent_card_routes` + `create_jsonrpc_routes`) and `DefaultRequestHandlerV2`. The custom `InitRunnerAgentExecutor` routes every task through `execute_run_stream_async()`, so A2A-served agents match `--serve` and CLI runs:

- Input content validation
- Role guardrail usage limits
- Retry/timeout wrapping
- Output validation and serialization
- Audit logging
- Agent-principal context

Blocking `SendMessage` waits until the task is terminal (`COMPLETED`, `FAILED`, `CANCELED`, `REJECTED`) or interrupted (`INPUT_REQUIRED`, `AUTH_REQUIRED`). `configuration.returnImmediately: true` returns the `SUBMITTED`/`WORKING` task and finishes in the background; poll with `GetTask`.

`CancelTask` cancels the running `execute_run_stream_async()` coroutine and marks the task `TASK_STATE_CANCELED`.

`SendStreamingMessage` (and `SubscribeToTask`) stream over SSE. Text roles emit append-artifact chunks as tokens arrive (`lastChunk: true` on the final delta). Structured output is published once at the end as a data part. Delegation (`A2AInvoker`) stays on blocking `SendMessage`.

### Agent Card

The card at `/.well-known/agent-card.json` is built from the role YAML. It includes `supportedInterfaces` (JSON-RPC, protocol version `1.0`), `version` from the role's top-level `version:` field, one default skill for the role plus one per resolved `SKILL.md`, and a Bearer security scheme when `--api-key` is set.

The SDK serializer also emits a few A2A 0.3 mirror fields (`url`, `preferredTransport`, …). Treat `supportedInterfaces` as the source of truth.

```json
{
  "name": "researcher",
  "description": "Gathers and summarizes research from the web",
  "version": "1.0.0",
  "supportedInterfaces": [
    {
      "url": "http://127.0.0.1:8000",
      "protocolBinding": "JSONRPC",
      "protocolVersion": "1.0"
    }
  ],
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "extendedAgentCard": false
  },
  "defaultInputModes": [
    "text/plain",
    "application/json",
    "image/*",
    "audio/*",
    "video/*",
    "application/pdf",
    "application/octet-stream"
  ],
  "defaultOutputModes": ["text/plain", "application/json"],
  "skills": [
    {
      "id": "researcher",
      "name": "researcher",
      "description": "Gathers and summarizes research from the web"
    }
  ]
}
```

### Conversation Context

A2A uses `contextId` to keep conversation threads. The executor stores PydanticAI `message_history` in an in-process LRU (1000 contexts) keyed by `contextId`. Tasks live in the SDK `InMemoryTaskStore`. Both die when the process exits.

### Why we wrap the SDK executor

`a2a-sdk` samples (and PydanticAI's old `agent.to_a2a()`) call `agent.run()` directly. `InitRunnerAgentExecutor` at `initrunner/a2a/server.py` implements `AgentExecutor.execute()` so every A2A task goes through `execute_run_stream_async()` instead. That keeps:

- Input content validation (guardrail inputs)
- Usage limits from the role's `guardrails`
- Retry/timeout wrapping
- Audit logging via `AuditLogger`
- Agent-principal context for authz checks
- Output post-processing (structured type coercion, deferred-tool handling)

An agent served over A2A must behave like the same agent served over OpenAI chat completions (`--serve`) or run from the CLI. Do not swap the executor for a raw `agent.run()` wrapper.

Inbound parts: text is joined; `data` is JSON-dumped into the text prompt; `url` becomes `ImageUrl` / `AudioUrl` / `VideoUrl` / `DocumentUrl` (media type first, then file extension); `raw` becomes `BinaryContent` and is rejected above 20 MB. Text-only messages stay a plain `str`. Structured output is a data part (plus `json_schema` metadata), not a text dump.

Human-in-the-loop pause (`INPUT_REQUIRED` / `AUTH_REQUIRED`) and a durable SQLite task store are documented follow-ups, not implemented.

## Calling A2A Agents from a Role

Use the delegate tool with `mode: a2a` to call a remote A2A 1.0 agent from another agent:

```yaml
name: coordinator
model: openai:gpt-4o
prompt: >
  You coordinate research tasks by delegating to specialized agents.
tools:
  - delegate:
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

1. Resolves `http://research-server:8000/.well-known/agent-card.json` (cached on the invoker)
2. Sends JSON-RPC `SendMessage` with `A2A-Version: 1.0` and a per-invoker `contextId`
3. If the task completes, extracts text from artifacts, then `status.message`, then the last agent history message
4. If the server returns `SUBMITTED` / `WORKING` (it honored `returnImmediately`), polls `GetTask` with exponential backoff until completion or timeout
5. Returns the result text to the LLM

Repeated `delegate_to_*` calls on the same invoker reuse that `contextId`, so the remote server can keep multi-turn history.

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

All errors are returned as strings prefixed with `[DELEGATION ERROR]` so the LLM can see and handle failures. Errors include:

- Task failed / rejected / canceled / auth-required / input-required
- Timeout (connection or polling)
- HTTP errors
- JSON-RPC errors (including missing `A2A-Version`)
- Agent-card resolution failures
- Policy denial (when agent authorization is configured)

`INPUT_REQUIRED` and `AUTH_REQUIRED` are terminal for delegation today. They become resumable only when HITL lands.

## Debugging a Failed Task

When a run fails, the reason travels two ways. The client gets it in the failed task's status message:

```json
"status": {"state": "TASK_STATE_FAILED", "message": {"parts": [{"text":
  "Model API error: status_code: 401, model_name: gpt-4o-mini, body:
   {'message': 'Invalid API key provided', 'code': 'invalid_api_key'}"}]}}
```

The server logs the same failure, so an operator watching the process does not need the client to report it:

```
[agent.run] run 01b147e59c75 of agent 'support-bot' failed [auth]: Model API error: status_code: 401, ...
```

For the provider request behind the failure (useful against a self-hosted OpenAI-compatible endpoint such as LiteLLM or vLLM), start the server with debug logging:

```bash
INITRUNNER_LOG_LEVEL=DEBUG initrunner a2a serve role.yaml
```

See [Logging](../operations/logging.md) for the full set of levels.

## Comparison with Other Interfaces

| Feature | `--serve` (OpenAI) | `mcp serve` | `a2a serve` |
|---------|-------------------|-------------|-------------|
| Protocol | OpenAI chat completions | MCP (JSON-RPC) | A2A 1.0 (JSON-RPC) |
| Discovery | Manual | MCP tool listing | Agent card at `/.well-known/agent-card.json` |
| Multi-turn | Server-side via `x-conversation-id` | Per-tool call | Via `contextId` |
| Agents per server | 1 | Multiple | 1 |
| Client tool | `delegate` mode `mcp` | Native MCP clients | `delegate` mode `a2a` |
| Use case | Drop-in OpenAI replacement | Tool sharing with AI IDEs | Cross-framework agent communication |
