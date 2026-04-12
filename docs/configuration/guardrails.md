# Guardrails

Configurable limits protect against runaway agents. Set them in the `spec.guardrails` block of your role YAML.

## Configuration

```yaml
spec:
  guardrails:
    max_tokens_per_run: 50000       # max tokens consumed per run
    max_tool_calls: 20              # max tool invocations per run
    timeout_seconds: 300            # hard timeout per run
    max_request_limit: 50           # max LLM requests per run
    input_tokens_limit: 10000       # per-request input token limit
    total_tokens_limit: 20000       # per-request total token limit
    session_token_budget: 500000    # cumulative budget for REPL session
    daemon_token_budget: 1000000    # cumulative budget for daemon lifetime
    daemon_daily_token_budget: 100000  # daily budget for daemon mode
    daemon_daily_cost_budget: 5.00    # daily USD cost budget for daemon
    daemon_weekly_cost_budget: 25.00  # weekly USD cost budget for daemon

    # Daemon resilience
    retry_policy:
      max_attempts: 3                # retry failed runs up to 3 times
      backoff_base_seconds: 2.0      # exponential backoff base
      backoff_max_seconds: 30.0      # backoff cap
    circuit_breaker:
      failure_threshold: 5           # open circuit after 5 failures
      reset_timeout_seconds: 60      # try again after 60s
```

## Field reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_tokens_per_run` | int | `50000` | Maximum output tokens consumed per agent run |
| `max_tool_calls` | int | `20` | Maximum tool invocations per run |
| `timeout_seconds` | int | `300` | Wall-clock timeout per run |
| `max_request_limit` | int | `50` | Maximum LLM API round-trips per run |
| `input_tokens_limit` | int | *null* | Per-request input token limit |
| `total_tokens_limit` | int | *null* | Per-request combined input+output token limit |
| `session_token_budget` | int | *null* | Cumulative token budget for REPL session (warns at 80%) |
| `daemon_token_budget` | int | *null* | Lifetime token budget for daemon process |
| `daemon_daily_token_budget` | int | *null* | Daily token budget for daemon (resets at UTC midnight) |
| `daemon_daily_cost_budget` | float | *null* | Daily USD cost budget for daemon (resets at UTC midnight) |
| `daemon_weekly_cost_budget` | float | *null* | Weekly USD cost budget for daemon (resets on ISO week change) |
| `max_iterations` | int | `10` | Maximum iterations in autonomous mode |
| `autonomous_token_budget` | int | *null* | Cumulative token budget for autonomous run |
| `autonomous_timeout_seconds` | int | *null* | Wall-clock timeout for autonomous run |
| `retry_policy` | object | `{max_attempts: 1}` | Daemon-level retry policy (see below) |
| `circuit_breaker` | object | *null* | Circuit breaker config (see below) |

## Daemon resilience

When a trigger fires and the agent run fails with a transient provider error (rate limit, 5xx, connection failure), the daemon can retry the entire run with exponential backoff. A circuit breaker tracks failures across trigger fires and stops dispatching when the provider is unhealthy.

### Retry policy

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `max_attempts` | int | `1` | 1-5 | Total attempts per trigger fire (1 = no retry) |
| `backoff_base_seconds` | float | `2.0` | 0.5-30 | Base delay for exponential backoff |
| `backoff_max_seconds` | float | `30.0` | 1-300 | Maximum backoff delay |

Retries only fire for provider-transient errors: HTTP 429 (rate limit), HTTP 5xx (server error), and connection failures. Timeouts, auth errors, content blocks, and usage limits are not retried.

**Side effects**: daemon retry re-executes the entire agent run, including tool calls. Enable retry only for idempotent roles or when failures occur before tool execution (provider-level errors).

### Circuit breaker

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `failure_threshold` | int | `5` | 1-100 | Failures before circuit opens |
| `reset_timeout_seconds` | int | `60` | 10-3600 | Seconds before half-open probe |

The circuit breaker tracks provider health across trigger fires (not retry attempts). Only provider errors trip the breaker: rate limits, server errors, connection failures, and auth errors (401/403). Application-level errors (content blocks, usage limits) are ignored.

State machine: `CLOSED -> OPEN` after threshold failures, `OPEN -> HALF_OPEN` after reset timeout, `HALF_OPEN -> CLOSED` on probe success or `HALF_OPEN -> OPEN` on probe failure. State transitions are logged as security audit events (`circuit_open`, `circuit_half_open`, `circuit_closed`).

Set `circuit_breaker: null` (default) to disable.

## Autonomous guardrails

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_iterations` | int | `10` | Maximum iterations in autonomous mode |
| `autonomous_token_budget` | int | *null* | Cumulative token budget across all autonomous iterations |
| `autonomous_timeout_seconds` | int | *null* | Wall-clock timeout for the entire autonomous run |

In autonomous mode, the agent sees its remaining budget in every continuation prompt (iterations 2+). A `BUDGET:` block is appended showing consumed iterations, tokens, and elapsed time with percentages. Lines for token budget and timeout only appear when those limits are configured. This lets the agent make informed decisions about prioritization and wrap-up.

See [Autonomous Execution](../orchestration/autonomy.md) for the full loop lifecycle.

## Token budgets

Token usage is tracked per-run in the audit log and displayed in the CLI.

- **Per-run limits** (`max_tokens_per_run`, `max_tool_calls`, `timeout_seconds`, `max_request_limit`) enforce hard stops on individual agent executions.
- **Session budgets** (`session_token_budget`) track cumulative usage across REPL turns and warn at 80% consumption.
- **Daemon budgets** (`daemon_token_budget`, `daemon_daily_token_budget`) protect long-running daemons from unbounded spend. The daily budget resets at UTC midnight.
- **Cost budgets** (`daemon_daily_cost_budget`, `daemon_weekly_cost_budget`) enforce USD spend limits using `genai-prices`. Requires a supported model/provider.

See [token_control.md](token_control.md) for advanced token budget configuration and monitoring, and [cost-tracking.md](../core/cost-tracking.md) for cost analytics and estimation.
