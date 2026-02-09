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

## Token budgets

Token usage is tracked per-run in the audit log and displayed in the CLI and TUI.

- **Per-run limits** (`max_tokens_per_run`, `max_tool_calls`, `timeout_seconds`, `max_request_limit`) enforce hard stops on individual agent executions.
- **Session budgets** (`session_token_budget`) track cumulative usage across REPL turns and warn at 80% consumption.
- **Daemon budgets** (`daemon_token_budget`, `daemon_daily_token_budget`) protect long-running daemons from unbounded spend. The daily budget resets at UTC midnight.

See [token_control.md](token_control.md) for advanced token budget configuration and monitoring.
