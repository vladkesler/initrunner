# Sinks — Result Routing

Sinks route agent results to external destinations after every run. When a trigger fires in daemon mode, a prompt completes in single-shot mode, or a turn finishes in interactive mode, each configured sink receives a structured payload containing the agent's output, token usage, timing, and metadata.

Sinks are configured in the `spec.sinks` list of a role definition. They follow the same discriminated-union pattern as tools and triggers.

## Sink Types

| Type | Use case |
|------|----------|
| `webhook` | POST JSON to a URL (Slack, Discord, custom APIs) |
| `file` | Append results to a local file (JSONL or plain text) |
| `custom` | Call a user-provided Python function |

## Quick Example

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: my-daemon
  description: Daemon that routes results to Slack and a log file
  tags:
    - daemon
spec:
  role: |
    You are a monitoring assistant.
  model:
    provider: openai
    name: gpt-4o-mini
  triggers:
    - type: cron
      schedule: "0 9 * * 1"
      prompt: "Generate weekly status report."
  sinks:
    - type: webhook
      url: ${SLACK_WEBHOOK_URL}
      headers:
        Content-Type: application/json
      retry_count: 2
    - type: file
      path: ./agent-results.jsonl
      format: json
  guardrails:
    max_tokens_per_run: 50000
    timeout_seconds: 300
```

## Webhook Sink

POSTs a JSON payload to a URL using `httpx`.

```yaml
sinks:
  - type: webhook
    url: https://hooks.slack.com/services/T00/B00/xxx    # required
    method: POST          # default: POST
    headers:              # default: {}
      Content-Type: application/json
      Authorization: Bearer ${API_TOKEN}
    timeout_seconds: 30   # default: 30
    retry_count: 0        # default: 0 (no retries)
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | `str` | *(required)* | Destination URL. Supports `${ENV_VAR}` substitution. |
| `method` | `str` | `POST` | HTTP method (`POST`, `PUT`, `PATCH`, etc.) |
| `headers` | `dict[str, str]` | `{}` | HTTP headers. Values support `${ENV_VAR}` substitution. |
| `timeout_seconds` | `int` | `30` | Request timeout in seconds. |
| `retry_count` | `int` | `0` | Number of retry attempts on failure. Retries wait 1 second between attempts. |

### Retry Behavior

When `retry_count` is set, the webhook sink will retry failed requests up to `retry_count` additional times with a 1-second delay between attempts. On final failure, the error is logged to stderr but never raises an exception.

## File Sink

Appends results to a local file. Creates parent directories if they don't exist.

```yaml
sinks:
  - type: file
    path: ./results/agent-output.jsonl   # required
    format: json                          # default: json
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | `str` | *(required)* | File path. Supports `${ENV_VAR}` substitution. Parent dirs are created automatically. |
| `format` | `"json"` \| `"text"` | `"json"` | Output format. |

### Output Formats

**`json`** (default) — One JSON object per line (JSONL). Each line contains the full payload:

```json
{"agent_name": "my-agent", "run_id": "abc123", "prompt": "Hello", "output": "Hi there!", "success": true, "error": null, "tokens_in": 15, "tokens_out": 8, "duration_ms": 420, "model": "gpt-4o-mini", "provider": "openai", "trigger_type": "cron", "trigger_metadata": {"schedule": "daily"}, "timestamp": "2025-06-01T09:00:00+00:00"}
```

**`text`** — Human-readable, one line per result:

```
[2025-06-01T09:00:00+00:00] my-agent | OK | Hi there!
[2025-06-01T09:01:00+00:00] my-agent | ERROR: timeout exceeded |
```

## Custom Sink

Calls a Python function you provide. The function receives the payload as a plain `dict`.

```yaml
sinks:
  - type: custom
    module: my_handlers     # required — Python module to import
    function: notify_team   # required — function name in that module
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `module` | `str` | *(required)* | Python module path (e.g. `my_handlers` or `pkg.handlers`). |
| `function` | `str` | *(required)* | Function name to call. |

The role file's parent directory is added to `sys.path` at runtime, so local modules next to your `role.yaml` are importable without installation.

### Example Handler

```python
# my_handlers.py (in the same directory as role.yaml)

def notify_team(payload: dict) -> None:
    """Called by InitRunner after each agent run."""
    if not payload["success"]:
        # Alert on failures
        send_alert(f"Agent {payload['agent_name']} failed: {payload['error']}")

    # Log to your own system
    log_result(payload)
```

## Payload Schema

Every sink receives the same `SinkPayload` (delivered as a `dict` for custom sinks, as JSON for webhook/file sinks):

| Field | Type | Description |
|-------|------|-------------|
| `agent_name` | `str` | Name from `metadata.name` |
| `run_id` | `str` | Unique identifier for this run |
| `prompt` | `str` | The prompt that was sent to the agent |
| `output` | `str` | The agent's response text |
| `success` | `bool` | Whether the run completed successfully |
| `error` | `str \| null` | Error message if `success` is `false` |
| `tokens_in` | `int` | Input tokens consumed |
| `tokens_out` | `int` | Output tokens generated |
| `duration_ms` | `int` | Run duration in milliseconds |
| `model` | `str` | Model name from config |
| `provider` | `str` | Provider name from config |
| `trigger_type` | `str \| null` | Trigger type that initiated the run (daemon mode only) |
| `trigger_metadata` | `dict` | Metadata from the trigger event |
| `timestamp` | `str` | ISO 8601 timestamp |

## Environment Variable Substitution

Sink config values that commonly contain secrets support `${ENV_VAR}` substitution. This keeps credentials out of YAML files.

Supported fields:
- **Webhook**: `url`, `headers` values
- **File**: `path`

```yaml
sinks:
  - type: webhook
    url: ${SLACK_WEBHOOK_URL}
    headers:
      Authorization: Bearer ${API_TOKEN}
```

Unset environment variables are kept as-is (e.g. `${UNSET_VAR}` remains literally `${UNSET_VAR}`). This matches the behavior of `os.path.expandvars()`.

## Error Handling

Sinks follow a **never-raise** pattern:

- A failing sink logs to stderr but never crashes the agent run.
- If multiple sinks are configured, a failure in one does not prevent others from executing.
- Webhook retries are exhausted before logging the final error.

This means your agent continues operating even if a downstream destination is temporarily unavailable.

## Validation

The `validate` command displays configured sinks:

```bash
$ initrunner validate role.yaml
```

```
                Role: my-daemon
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Field           ┃ Value                          ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ...             │ ...                            │
│ Sinks           │ webhook: ${SLACK_WEBHOOK_URL}  │
│                 │ file: ./agent-results.jsonl    │
│                 │   (json)                       │
└─────────────────┴────────────────────────────────┘
```

## Delegate Sink (Compose Only)

The `delegate` sink type is used exclusively in [compose definitions](agent_composer.md) to route a service's output to other services via in-memory queues. It is not available in standalone role YAML files — it is configured via the `sink:` field on a compose service.

See [Agent Composer — Delegate Sink](agent_composer.md#delegate-sink) for configuration options, circuit breaker behavior, and examples.

## Run Modes

Sinks fire in all run modes:

| Mode | When sinks fire |
|------|----------------|
| Single-shot (`-p "..."`) | After the single run completes |
| Interactive (`-i`) | After each REPL turn |
| Daemon | After each trigger-initiated run, with `trigger_type` and `trigger_metadata` populated |
