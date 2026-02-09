# AG-UI Chat Endpoint

The dashboard exposes an AG-UI-compatible SSE chat endpoint alongside the existing WebSocket endpoint. The AG-UI endpoint uses PydanticAI's `AGUIAdapter` to stream structured events (text deltas, tool calls, run lifecycle) over Server-Sent Events.

## Backend

### `POST /api/chat/{role_id}`

Accepts an AG-UI `RunAgentInput` JSON body and returns an SSE stream of AG-UI events.

**Headers:**

| Header | Value | Required |
|--------|-------|----------|
| `Content-Type` | `application/json` | Yes |
| `Accept` | `text/event-stream` | Recommended |
| `Authorization` | `Bearer <api_key>` | When auth is enabled |

**Request body** (AG-UI `RunAgentInput`):

```json
{
  "thread_id": "thread_abc",
  "run_id": "run_123",
  "messages": [
    { "id": "msg_1", "role": "user", "content": "Hello" }
  ],
  "tools": [],
  "context": [],
  "state": {},
  "forwarded_props": {}
}
```

AG-UI uses client-managed history — send the full conversation history with each request.

**Response:** `text/event-stream` with `data:` prefixed JSON lines.

**Error responses:**

| Status | Condition |
|--------|-----------|
| `401` | Missing or invalid API key (when auth is enabled) |
| `404` | Role ID does not match any discovered role |
| `422` | Invalid or missing request body fields |

### Agent caching

Agents are cached in a `dict[str, tuple]` keyed by `role_id`. Building an agent involves discovering roles, loading YAML, and constructing the PydanticAI `Agent` — caching avoids repeating this on every request.

### Auth

The endpoint is protected by the same Bearer token / `?api_key=` middleware that covers all `/api/` routes. No additional auth logic is needed in the route itself.

## SSE Event Types

The stream emits standard AG-UI events. Each SSE line has the format `data: <json>`.

### Run lifecycle

| Event | Fields | Description |
|-------|--------|-------------|
| `RUN_STARTED` | `type`, `thread_id`, `run_id` | Run has begun |
| `RUN_FINISHED` | `type`, `usage` | Run completed; `usage` contains `input_tokens`, `output_tokens`, `duration_ms` |
| `RUN_ERROR` | `type`, `message` | Run failed with an error |

### Text messages

| Event | Fields | Description |
|-------|--------|-------------|
| `TEXT_MESSAGE_START` | `type`, `message_id`, `role` | Assistant message started |
| `TEXT_MESSAGE_CONTENT` | `type`, `message_id`, `delta` | Text chunk delta |
| `TEXT_MESSAGE_END` | `type`, `message_id` | Assistant message complete |

### Tool calls

| Event | Fields | Description |
|-------|--------|-------------|
| `TOOL_CALL_START` | `type`, `tool_call_id`, `tool_call_name` | Tool invocation started |
| `TOOL_CALL_ARGS` | `type`, `tool_call_id`, `delta` | Argument chunk delta |
| `TOOL_CALL_END` | `type`, `tool_call_id` | Tool call arguments complete |
| `TOOL_CALL_RESULT` | `type`, `tool_call_id`, `result` | Tool execution result |

### Example stream

```
data: {"type": "RUN_STARTED", "thread_id": "t1", "run_id": "r1"}
data: {"type": "TEXT_MESSAGE_START", "message_id": "m1", "role": "assistant"}
data: {"type": "TEXT_MESSAGE_CONTENT", "message_id": "m1", "delta": "Hello"}
data: {"type": "TEXT_MESSAGE_CONTENT", "message_id": "m1", "delta": "!"}
data: {"type": "TEXT_MESSAGE_END", "message_id": "m1"}
data: {"type": "TOOL_CALL_START", "tool_call_id": "tc1", "tool_call_name": "get_time"}
data: {"type": "TOOL_CALL_ARGS", "tool_call_id": "tc1", "delta": "{}"}
data: {"type": "TOOL_CALL_END", "tool_call_id": "tc1"}
data: {"type": "TOOL_CALL_RESULT", "tool_call_id": "tc1", "result": "2025-01-15T10:30:00Z"}
data: {"type": "TEXT_MESSAGE_CONTENT", "message_id": "m1", "delta": "The time is 10:30 AM."}
data: {"type": "TEXT_MESSAGE_END", "message_id": "m1"}
data: {"type": "RUN_FINISHED", "usage": {"input_tokens": 50, "output_tokens": 20}}
```

## Frontend Integration

The chat page (`dashboard/src/app/roles/[id]/chat/client.tsx`) uses the AG-UI POST endpoint instead of WebSocket.

### How it works

1. User types a message and hits Enter.
2. The full message history is sent as an AG-UI `RunAgentInput` POST request via `authFetch()`.
3. The response body is read as a `ReadableStream`, parsed line-by-line for `data:` SSE events.
4. Each event type updates React state:
   - `TEXT_MESSAGE_CONTENT` — streams assistant text into the current message bubble.
   - `TOOL_CALL_START/ARGS/END` — accumulates tool call info (name + arguments).
   - `TOOL_CALL_RESULT` — attaches the result to the matching tool call.
   - `RUN_FINISHED` — displays token/duration stats.
   - `RUN_ERROR` — shows an error message.
5. Assistant messages are rendered with `react-markdown` + `remark-gfm`.
6. Tool calls render as collapsible cards showing the tool name, arguments JSON, and result.

### Persistence

- Messages are persisted to `localStorage` keyed by role ID (`initrunner_chat_{roleId}`).
- On mount, saved messages are restored from `localStorage`.
- The "New chat" button clears `localStorage` and resets the conversation.

### Key dependencies

| Package | Purpose |
|---------|---------|
| `react-markdown` | Render assistant markdown content |
| `remark-gfm` | GitHub-flavored markdown (tables, strikethrough, task lists) |

## WebSocket Endpoint (Legacy)

The WebSocket endpoint at `WS /api/chat/{role_id}` remains available for backward compatibility with the TUI. It uses a different protocol (JSON messages over WebSocket) and manages server-side session state. See `initrunner/api/routes/agents.py`.

## Testing

### Run the AG-UI chat tests

```bash
uv run pytest tests/test_agui_chat.py -v
```

### Test coverage

| Test class | What it covers |
|------------|----------------|
| `TestAGUIChatAuth` | Bearer token and query param auth enforcement, no-auth mode |
| `TestAGUIChatRoleResolution` | Unknown role returns 404 |
| `TestAGUIChatSSEFormat` | Response content-type is `text/event-stream`, events have `data:` prefix with valid JSON containing a `type` field |
| `TestAGUIChatValidation` | Empty body and missing `messages` field return 422 |

### Manual testing

1. Start the dashboard:
   ```bash
   uv run initrunner ui
   ```

2. Open `http://127.0.0.1:8420`, navigate to a role, and click "Chat".

   **Frontend development mode** (only when editing frontend source):
   ```bash
   # Terminal 1
   uv run initrunner ui --no-browser
   # Terminal 2
   cd dashboard && npm run dev    # open http://localhost:3000
   ```

3. Verify:
   - Assistant text streams in real-time.
   - Tool calls appear as collapsible cards with name, args, and result.
   - Token stats show after the run completes.
   - Messages survive a page refresh (localStorage).
   - "New chat" clears the conversation.
