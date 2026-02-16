# OpenAI-Compatible API Server

The `initrunner serve` command exposes any agent as an OpenAI-compatible HTTP API. This lets you use InitRunner agents as drop-in replacements for OpenAI in any client that speaks the chat completions wire format — including the official OpenAI SDKs, `curl`, and tools like Open WebUI.

## Quick Start

```bash
# Start the server
initrunner serve role.yaml

# With authentication
initrunner serve role.yaml --api-key my-secret-key

# Custom host/port
initrunner serve role.yaml --host 0.0.0.0 --port 3000
```

## CLI Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `role_file` | `Path` | *(required)* | Path to the role YAML file. |
| `--host` | `str` | `127.0.0.1` | Host to bind to. Use `0.0.0.0` to expose on all interfaces. |
| `--port` | `int` | `8000` | Port to listen on. |
| `--api-key` | `str` | `None` | API key for Bearer token authentication. When set, all `/v1/*` endpoints require `Authorization: Bearer <key>`. |
| `--audit-db` | `Path` | `~/.initrunner/audit.db` | Path to audit database. |
| `--no-audit` | `bool` | `false` | Disable audit logging. |
| `--cors-origin` | `str` | `None` | Allowed CORS origin. Can be repeated. Merged with `security.server.cors_origins` from role YAML. |
| `--skill-dir` | `Path` | `None` | Extra skill search directory. |

## Endpoints

### `GET /health`

Health check endpoint. Always returns `200 OK`.

```json
{"status": "ok"}
```

Not protected by authentication even when `--api-key` is set.

### `GET /v1/models`

Lists available models. Returns the agent's `metadata.name` as the model ID.

```json
{
  "object": "list",
  "data": [
    {
      "id": "my-agent",
      "object": "model",
      "created": 1700000000,
      "owned_by": "initrunner"
    }
  ]
}
```

### `POST /v1/chat/completions`

The main chat completions endpoint. Accepts the standard OpenAI request format.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | `str` | `""` | Model name (ignored — the agent's model is used). |
| `messages` | `list[ChatMessage]` | `[]` | Conversation messages. |
| `stream` | `bool` | `false` | Enable Server-Sent Events streaming. |
| `temperature` | `float \| null` | `null` | Ignored (uses role config). |
| `max_tokens` | `int \| null` | `null` | Ignored (uses role config). |

Each `ChatMessage` has:

| Field | Type | Description |
|-------|------|-------------|
| `role` | `str` | `"system"`, `"user"`, or `"assistant"` |
| `content` | `str \| null` | Message content |

## Non-Streaming Response

```json
{
  "id": "chatcmpl-a1b2c3d4e5f6",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "my-agent",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! How can I help you?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 15,
    "completion_tokens": 8,
    "total_tokens": 23
  }
}
```

## Streaming Response

When `stream: true`, the server responds with Server-Sent Events (SSE). Each event is a `data:` line containing a JSON chunk:

```
data: {"id":"chatcmpl-a1b2c3","object":"chat.completion.chunk","created":1700000000,"model":"my-agent","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-a1b2c3","object":"chat.completion.chunk","created":1700000000,"model":"my-agent","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-a1b2c3","object":"chat.completion.chunk","created":1700000000,"model":"my-agent","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":15,"completion_tokens":8,"total_tokens":23}}

data: [DONE]
```

The first chunk contains `delta.role`, subsequent chunks contain `delta.content`, and the final chunk has `finish_reason: "stop"` along with `usage` metrics (matching OpenAI's streaming usage format).

**Input validation**: If the prompt is blocked by guardrails (content policy), the server returns HTTP 400 *before* the SSE stream starts, so the client receives a standard error response rather than a partially-opened stream.

**Heartbeat**: For long-running responses, the server sends SSE comment lines (`: heartbeat`) to keep the connection alive and prevent proxy timeouts.

## Multi-Turn Conversations

The server supports server-side conversation history via the `X-Conversation-Id` header.

**How it works:**

1. Send a request with an `X-Conversation-Id` header value (any string).
2. The server stores the full PydanticAI message history after each request.
3. On subsequent requests with the same ID, the server uses the stored history — only the last user message from your request is used as the new prompt.
4. If no `X-Conversation-Id` is provided, a random ID is generated per request (no continuity).

The response includes an `X-Conversation-Id` header so clients can capture it for follow-up requests.

### Conversation TTL

Conversations are stored in memory and expire after **1 hour** of inactivity (last access time). Expired conversations are cleaned up lazily on the next access. All conversations are cleared when the server shuts down.

## Authentication

When `--api-key` is set, all `/v1/*` endpoints require a Bearer token:

```
Authorization: Bearer <api-key>
```

The `/health` endpoint is never protected, allowing load balancers and health checks to work without credentials.

Invalid or missing tokens return:

```json
{"error": {"message": "invalid API key", "type": "authentication_error", "code": 401}}
```

## CORS

By default, the server sends **no CORS headers** (secure default). CORS origins are configured via the role YAML (`security.server.cors_origins`) and/or the `--cors-origin` CLI flag.

- Origins from both sources are **merged** (CLI supplements YAML, does not replace).
- When at least one origin is configured, the server adds CORS middleware with `allow_methods: ["*"]` and `allow_headers: ["*"]` for those origins.
- If no origins are configured, no CORS middleware is added.

```bash
# Add origins via CLI (repeatable flag)
initrunner serve role.yaml --cors-origin https://myapp.com --cors-origin https://staging.com
```

## Error Handling

Errors follow the OpenAI error response format:

```json
{"error": {"message": "...", "type": "error_type", "code": 400}}
```

| Status | Type | When |
|--------|------|------|
| 400 | `invalid_request_error` | Invalid JSON body, validation failure, missing user message, or blocked input (streaming pre-flight) |
| 400 | `context_length_exceeded` | Agent's usage limit exceeded |
| 401 | `authentication_error` | Invalid or missing API key |
| 500 | `server_error` | Agent run failure or unexpected error |

During streaming, errors are sent as SSE data events rather than HTTP status codes (since the stream has already started with a 200).

## Usage Examples

### curl (non-streaming)

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### curl (streaming)

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

### curl (with auth and conversation)

```bash
# First message
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer my-secret-key" \
  -H "X-Conversation-Id: conv-001" \
  -d '{
    "messages": [{"role": "user", "content": "My name is Alice."}]
  }'

# Follow-up (server remembers context)
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer my-secret-key" \
  -H "X-Conversation-Id: conv-001" \
  -d '{
    "messages": [{"role": "user", "content": "What is my name?"}]
  }'
```

### OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="my-secret-key",  # or "unused" if no --api-key set
)

response = client.chat.completions.create(
    model="my-agent",  # matches metadata.name in role.yaml
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

### OpenAI Python SDK (streaming)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="unused",
)

stream = client.chat.completions.create(
    model="my-agent",
    messages=[{"role": "user", "content": "Tell me a story."}],
    stream=True,
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### OpenAI Node.js SDK

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://127.0.0.1:8000/v1",
  apiKey: "my-secret-key",
});

const response = await client.chat.completions.create({
  model: "my-agent",
  messages: [{ role: "user", content: "Hello!" }],
});
console.log(response.choices[0].message.content);
```

## Message Conversion

When no server-side conversation exists, the server converts OpenAI-format messages to PydanticAI's internal format:

- The **last user message** becomes the prompt.
- Prior `user` and `assistant` messages become `message_history`.
- `system` messages are prepended to the next user message's content.
- `tool` role messages are skipped.

When a server-side conversation exists (via `X-Conversation-Id`), only the last user message from the request is extracted as the new prompt, and the stored history is used directly.

## Open WebUI Integration

[Open WebUI](https://github.com/open-webui/open-webui) gives you a ChatGPT-like web interface for any InitRunner agent. Because `initrunner serve` speaks the OpenAI wire format, Open WebUI works out of the box — no plugins or adapters needed.

### Setup

This walkthrough uses the `support-agent` example, which includes a RAG knowledge base.

**1. Ingest the knowledge base**

```bash
initrunner ingest examples/roles/support-agent/support-agent.yaml
```

**2. Start the InitRunner server**

```bash
initrunner serve examples/roles/support-agent/support-agent.yaml --host 0.0.0.0 --port 3000
```

> `--host 0.0.0.0` is required so the Docker container can reach the server.

**3. Launch Open WebUI**

```bash
docker run -d \
  --name open-webui \
  --network host \
  -e OPENAI_API_BASE_URL=http://127.0.0.1:3000/v1 \
  -e OPENAI_API_KEY=unused \
  -v open-webui:/app/backend/data \
  ghcr.io/open-webui/open-webui:main
```

**4. Open your browser**

Navigate to `http://localhost:8080`, create a local account, and select the `support-agent` model from the model dropdown. Start chatting — responses are served by your InitRunner agent.

### Cleanup

```bash
docker rm -f open-webui
docker volume rm open-webui
```

### Notes

- If you start the server with `--api-key`, set `OPENAI_API_KEY` to the same value in the `docker run` command.
- For production deployments, consider running both services behind a reverse proxy with TLS.
