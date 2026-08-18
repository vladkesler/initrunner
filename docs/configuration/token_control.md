# Token Usage Control

InitRunner provides guardrails that limit how many tokens an agent can consume. These controls prevent runaway costs in development, enforce budgets in production daemons, and give visibility into token usage across the CLI.

All guardrails are configured under the top-level `guardrails` key in your `role.yaml`.

## Quick Start

Add guardrails to any role definition to cap per-run output and set a session budget for interactive use:

```yaml
guardrails:
  max_tokens_per_run: 50000
  session_token_budget: 500000
```

For daemon roles, add lifetime and daily budgets:

```yaml
guardrails:
  max_tokens_per_run: 50000
  daemon_token_budget: 2000000
  daemon_daily_token_budget: 200000
```

## Guardrails Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_tokens_per_run` | `int > 0` | `50000` | Maximum **output** tokens per single run. Maps to PydanticAI `output_tokens_limit`. |
| `input_tokens_limit` | `int > 0 \| null` | `null` | Maximum **input** tokens per logical run (pause + resume). Maps to PydanticAI `input_tokens_limit`. |
| `per_request_input_tokens_limit` | `int > 0 \| null` | `null` | Maximum **input** tokens on one model request, including cached prefix tokens. Maps to PydanticAI `per_request_input_tokens_limit`. |
| `cost_limit` | `float > 0 \| null` | `null` | Best-effort USD cap per logical run. Maps to PydanticAI `cost_limit`. Converted with `Decimal(str(value))`. Unpriced models skip enforcement and warn. |
| `total_tokens_limit` | `int > 0 \| null` | `null` | Maximum **total** (input + output) tokens per logical run. Maps to PydanticAI `total_tokens_limit`. |
| `max_tool_calls` | `int >= 0` | `20` | Maximum tool calls per single run. Maps to PydanticAI `tool_calls_limit`. |
| `max_request_limit` | `int > 0 \| null` | *derived* | Maximum model requests (API round-trips) per single run. Maps to PydanticAI `request_limit`. When omitted or `null`, it is derived as `max(max_tool_calls + 10, 30)`, which is `30` with the default `max_tool_calls: 20`. |
| `timeout_seconds` | `int > 0` | `300` | Wall-clock timeout for a single run (5 minutes). |
| `session_token_budget` | `int > 0 \| null` | `null` | Cumulative total token budget for a REPL session. |
| `daemon_token_budget` | `int > 0 \| null` | `null` | Lifetime total token budget for a daemon process. |
| `daemon_daily_token_budget` | `int > 0 \| null` | `null` | Daily total token budget for a daemon process (resets at midnight in `budget_timezone`). |
| `daemon_daily_cost_budget` | `float > 0 \| null` | `null` | Daily USD cost budget for daemon (resets at midnight in `budget_timezone`). |
| `daemon_weekly_cost_budget` | `float > 0 \| null` | `null` | Weekly USD cost budget for daemon (resets on ISO year-week boundary). |
| `budget_timezone` | `string` | `"UTC"` | IANA timezone for daily/weekly budget resets (e.g. `America/New_York`). |

When a field is `null` (or omitted), no limit is enforced for that dimension.

Budget counters are persisted to the audit database after each run, so they survive daemon/bot restarts. The `--budget-timezone` CLI flag overrides the YAML value.

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

Caps the number of **input** tokens (prompt + context) consumed in a logical run, including approval resume. Useful when agents use large context windows or retrieve many documents.

```yaml
guardrails:
  input_tokens_limit: 100000
```

### Per-request input (`per_request_input_tokens_limit`)

Caps a single model request's context size. Unlike `input_tokens_limit`, this is not cumulative. Cached prefix tokens still count: the cap is context size, not cache-miss cost.

```yaml
guardrails:
  per_request_input_tokens_limit: 80000
```

### Per-run cost (`cost_limit`)

Caps estimated USD spend for one logical run using PydanticAI's `RunUsage.cost` (genai-prices). This is not the provider invoice. If the model has no price data, the cap is not enforced.

```yaml
guardrails:
  cost_limit: 0.50
```

Approval resume keeps the same budget: prior usage from `message_history` is passed back into `agent.run(usage=...)` so tokens and cost do not reset after a pause.

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

Limits the number of model API round-trips per run. Each tool call result that gets sent back to the model counts as a new request. Omit the field to let InitRunner derive it from `max_tool_calls`, or set it explicitly to override:

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

The `session_token_budget` tracks cumulative token usage across all turns in an interactive REPL session (`initrunner run <path> -i`). This is useful for capping how much a single interactive session can spend.

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

## Daemon Token Budgets

Daemon mode (`initrunner run <path> --daemon`) supports two independent budget controls that work together. Both are tracked in-memory by a thread-safe `DaemonTokenTracker`.

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
- Both counters are held in memory by `DaemonTokenTracker`, but a snapshot is written to the audit database after every run (`save_budget_state`) and restored at startup (`load_budget_state`), keyed by agent name. `daemon_token_budget` is therefore a durable lifetime budget that survives daemon and bot restarts. The daily and weekly counters are re-checked against the current date during restore, so they still roll over normally. Running with `--no-audit` leaves nothing to persist to and makes the counters per-process.

On startup, the daemon displays configured budgets:

```
Daemon mode -- agent: my-agent
  Lifetime token budget: 2,000,000
  Daily token budget: 200,000
  Daily cost budget: $5.00
  Weekly cost budget: $25.00
  Budgets reset on process restart.
  2 trigger(s) active. Press Ctrl+C to stop.
```

### Cost Budgets (`daemon_daily_cost_budget`, `daemon_weekly_cost_budget`)

USD-based cost limits for daemon and bot modes. Cost is estimated after each run using `genai-prices` and accumulated alongside token counters.

```yaml
guardrails:
  daemon_daily_cost_budget: 5.00
  daemon_weekly_cost_budget: 25.00
```

At startup, pricing availability is validated for the role's model. If pricing data is unavailable, the daemon exits with an error rather than silently disabling cost enforcement.

See [cost-tracking.md](../core/cost-tracking.md) for the full cost tracking system, CLI commands, and estimation.

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
guardrails:
  max_tokens_per_run: 10000
  max_tool_calls: 5
  max_request_limit: 10
  timeout_seconds: 60
  session_token_budget: 100000
```

### Production Daemon

A cron-triggered daemon with token and cost budgets:

```yaml
guardrails:
  max_tokens_per_run: 50000
  max_tool_calls: 20
  timeout_seconds: 300
  max_request_limit: 50
  daemon_token_budget: 5000000
  daemon_daily_token_budget: 500000
  daemon_daily_cost_budget: 10.00
  daemon_weekly_cost_budget: 50.00
triggers:
  - type: cron
    schedule: "*/15 * * * *"
    prompt: "Check system health and report anomalies."
```

### RAG with Budget

A knowledge assistant with input token limits to control retrieval context size:

```yaml
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

See also: [cost-tracking.md](../core/cost-tracking.md) for cost analytics and estimation, [security.md](../security/security.md) for content policies and sandboxing, [tools.md](../agents/tools.md) for tool-specific limits, [audit.md](../core/audit.md) for querying token usage history.
