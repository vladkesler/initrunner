# Token Usage Control

InitRunner provides guardrails that limit how many tokens an agent can consume. These controls prevent runaway costs in development, enforce budgets in production daemons, and give visibility into token usage across the CLI, TUI, and dashboard.

All guardrails are configured under `spec.guardrails` in your `role.yaml`.

## Quick Start

Add guardrails to any role definition to cap per-run output and set a session budget for interactive use:

```yaml
spec:
  guardrails:
    max_tokens_per_run: 50000
    session_token_budget: 500000
```

For daemon roles, add lifetime and daily budgets:

```yaml
spec:
  guardrails:
    max_tokens_per_run: 50000
    daemon_token_budget: 2000000
    daemon_daily_token_budget: 200000
```

## Guardrails Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_tokens_per_run` | `int > 0` | `50000` | Maximum **output** tokens per single run. Maps to PydanticAI `output_tokens_limit`. |
| `input_tokens_limit` | `int > 0 \| null` | `null` | Maximum **input** tokens per single run. Maps to PydanticAI `input_tokens_limit`. |
| `total_tokens_limit` | `int > 0 \| null` | `null` | Maximum **total** (input + output) tokens per single run. Maps to PydanticAI `total_tokens_limit`. |
| `max_tool_calls` | `int >= 0` | `20` | Maximum tool calls per single run. Maps to PydanticAI `tool_calls_limit`. |
| `max_request_limit` | `int > 0` | `50` | Maximum model requests (API round-trips) per single run. Maps to PydanticAI `request_limit`. |
| `timeout_seconds` | `int > 0` | `300` | Wall-clock timeout for a single run (5 minutes). |
| `session_token_budget` | `int > 0 \| null` | `null` | Cumulative total token budget for a REPL session. |
| `daemon_token_budget` | `int > 0 \| null` | `null` | Lifetime total token budget for a daemon process. |
| `daemon_daily_token_budget` | `int > 0 \| null` | `null` | Daily total token budget for a daemon process (resets at UTC midnight). |

When a field is `null` (or omitted), no limit is enforced for that dimension.

## Per-Run Limits

Per-run limits are checked on every `execute_run` and `execute_run_stream` call. They map directly to PydanticAI's `UsageLimits` and are enforced by the model framework itself.

### Output Tokens (`max_tokens_per_run`)

Caps the number of **output** tokens generated in a single run. This is the primary cost control for individual prompts.

```yaml
guardrails:
  max_tokens_per_run: 50000
```

When exceeded, the run fails with `UsageLimitExceeded` and the error is recorded in the audit log.

### Input Tokens (`input_tokens_limit`)

Caps the number of **input** tokens (prompt + context) consumed in a single run. Useful when agents use large context windows or retrieve many documents.

```yaml
guardrails:
  input_tokens_limit: 100000
```

### Total Tokens (`total_tokens_limit`)

Caps the combined input + output tokens for a single run. Use this as a single knob when you want to control total cost per interaction.

```yaml
guardrails:
  total_tokens_limit: 200000
```

### Tool Calls (`max_tool_calls`)

Limits how many tool calls the agent can make in a single run. Prevents infinite tool-calling loops.

```yaml
guardrails:
  max_tool_calls: 20
```

Setting this to `0` disables all tool use for that run.

### Model Requests (`max_request_limit`)

Limits the number of model API round-trips per run. Each tool call result that gets sent back to the model counts as a new request.

```yaml
guardrails:
  max_request_limit: 50
```

### Timeout (`timeout_seconds`)

Wall-clock timeout for a single run. If the agent hasn't completed within this window, the run is terminated.

```yaml
guardrails:
  timeout_seconds: 300
```

## Session Token Budget

The `session_token_budget` tracks cumulative token usage across all turns in an interactive REPL session (`initrunner run <role.yaml> -i`). This is useful for capping how much a single interactive session can spend.

```yaml
guardrails:
  session_token_budget: 500000
```

### How It Works

1. A running counter tracks `total_tokens` across all turns in the session.
2. At **80% consumed**, a warning is displayed:
   ```
   Warning: 82% of session token budget consumed (410,000/500,000)
   ```
3. When the budget is **exhausted**, the REPL stops accepting new prompts:
   ```
   Session token budget exhausted. Stopping further execution.
   ```

The budget is checked both before accepting a new prompt and after each run completes.

### TUI Behavior

In the TUI run screen, the session budget is displayed in the status bar with color-coded percentages: green under 80%, yellow at 80-99%, and red at 100%. When the budget is exhausted, the send action is disabled and a notification is shown.

## Daemon Token Budgets

Daemon mode (`initrunner daemon <role.yaml>`) supports two independent budget controls that work together. Both are tracked in-memory by a thread-safe `DaemonTokenTracker`.

### Lifetime Budget (`daemon_token_budget`)

Total tokens the daemon can consume across its entire lifetime. When exhausted, all further trigger executions are skipped.

```yaml
guardrails:
  daemon_token_budget: 2000000
```

### Daily Budget (`daemon_daily_token_budget`)

Total tokens the daemon can consume per calendar day. Resets automatically at UTC midnight. When exhausted, trigger executions are skipped until the next day.

```yaml
guardrails:
  daemon_daily_token_budget: 200000
```

### Behavior

- Before each trigger execution, `DaemonTokenTracker.check_before_run()` checks both budgets.
- If either budget is exceeded, the trigger is skipped with a log message:
  ```
  Budget exceeded -- skipping trigger: Daily budget exhausted (200,000/200,000)
  ```
- After each run, `record_usage()` updates both the lifetime and daily counters.
- The daily counter resets when the current UTC date advances past the last reset date.
- Both counters are **in-memory only** and reset when the daemon process restarts. The `daemon_token_budget` is a per-process lifetime, not persistent across restarts.

On startup, the daemon displays configured budgets:

```
Daemon mode -- agent: my-agent
  Lifetime token budget: 2,000,000
  Daily token budget: 200,000
  Token budgets reset on process restart.
  2 trigger(s) active. Press Ctrl+C to stop.
```

## Visibility

Token control settings are surfaced across all interfaces.

### CLI (`initrunner validate`)

The `validate` command displays all configured guardrail fields in a summary table:

```
Max Tokens/Run    50000
Max Tool Calls    20
Max Requests      50
Timeout           300s
Session Token Budget    500,000
Daemon Token Budget     2,000,000
Daemon Daily Budget     200,000
```

Fields with `null` values are omitted from the table.

### REPL Panel Subtitle

Each response panel in interactive mode shows per-turn token usage. When a session budget is configured, it also shows cumulative progress:

```
tokens: 1200in/450out | 320ms | budget: 1,650/500,000
```

### TUI Status Bar

The TUI run screen shows a persistent status bar with cumulative token counts and, when a session budget is configured, a color-coded percentage:

```
my-agent | openai:gpt-5-mini | 1200 in 450 out | 1,650/500,000 (0%)
```

The guardrails detail screen in the TUI lists all nine guardrail fields with their current values (showing "unlimited" for unset optional limits).

### Dashboard API

The `/api/roles/{role_id}` endpoint returns a `guardrails` object with all nine fields:

```json
{
  "guardrails": {
    "max_tokens_per_run": 50000,
    "timeout_seconds": 300,
    "max_tool_calls": 20,
    "max_request_limit": 50,
    "input_tokens_limit": null,
    "total_tokens_limit": null,
    "session_token_budget": 500000,
    "daemon_token_budget": null,
    "daemon_daily_token_budget": null
  }
}
```

### Audit Logs

Every run is recorded in the SQLite audit trail (`~/.initrunner/audit.db`) with per-run token counts:

- `tokens_in` -- input tokens consumed
- `tokens_out` -- output tokens generated
- `total_tokens` -- combined total
- `tool_calls` -- number of tool calls made
- `duration_ms` -- wall-clock duration

When a run fails due to `UsageLimitExceeded`, the `error` field captures the specific limit that was breached. See [audit.md](../core/audit.md) for querying audit data.

## Tool Output Limits

Individual tools have their own output size caps to prevent a single tool call from consuming the agent's context window:

| Tool | Limit |
|------|-------|
| `read_file` | 1 MB |
| `http_request` | 100 KB |
| `fetch_page` (web_reader) | 500 KB |
| `run_python` | 100 KB |
| `query_database` (sql) | 100 KB |

Outputs exceeding these limits are truncated with `[truncated]` appended. These are separate from the guardrail token limits and are configured per-tool. See [tools.md](../agents/tools.md) for tool-specific configuration.

## Examples

### Cost-Conscious Development

Tight per-run limits and a session budget for local development:

```yaml
spec:
  guardrails:
    max_tokens_per_run: 10000
    max_tool_calls: 5
    max_request_limit: 10
    timeout_seconds: 60
    session_token_budget: 100000
```

### Production Daemon

A cron-triggered daemon with both lifetime and daily budgets:

```yaml
spec:
  guardrails:
    max_tokens_per_run: 50000
    max_tool_calls: 20
    timeout_seconds: 300
    max_request_limit: 50
    daemon_token_budget: 5000000
    daemon_daily_token_budget: 500000
  triggers:
    - type: cron
      schedule: "*/15 * * * *"
      prompt: "Check system health and report anomalies."
```

### RAG with Budget

A knowledge assistant with input token limits to control retrieval context size:

```yaml
spec:
  guardrails:
    max_tokens_per_run: 50000
    input_tokens_limit: 100000
    total_tokens_limit: 200000
    max_tool_calls: 20
    session_token_budget: 500000
  ingest:
    sources:
      - "./docs/**/*.md"
    chunking:
      strategy: fixed
      chunk_size: 512
```

---

See also: [security.md](../security/security.md) for content policies and sandboxing, [tools.md](../agents/tools.md) for tool-specific limits, [audit.md](../core/audit.md) for querying token usage history.
