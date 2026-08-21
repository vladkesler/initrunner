# Logging

InitRunner writes logs to **stderr**. At the default level you see warnings and errors only, which keeps one-shot runs quiet. When something is failing and you need to know why, turn the level up.

## Quick start

```bash
# Debug logging for one command (the flag goes before the subcommand)
initrunner --verbose run role.yaml -p "hello"
initrunner -v run role.yaml -p "hello"

# Same thing via the environment, which works for daemons and containers
INITRUNNER_LOG_LEVEL=DEBUG initrunner a2a serve role.yaml
```

`--verbose` is a **global** option, so it must come before the subcommand. `initrunner a2a serve role.yaml --verbose` is an error.

## Levels

| Level | What you get |
|-------|--------------|
| `ERROR` | Only errors. |
| `WARNING` | **Default.** Errors plus failed runs, degraded tools, and skipped features. |
| `INFO` | Adds lifecycle detail: scheduled tasks, bot and socket connections, service start and stop. |
| `DEBUG` | Everything InitRunner emits, **plus provider HTTP traffic** (`httpx`, `openai`, `anthropic`, `pydantic_ai`). This is the deepest level; there is no `TRACE`. |

Set the level one of two ways:

- `--verbose` / `-v` on the CLI, which always means `DEBUG`.
- `INITRUNNER_LOG_LEVEL`, which takes a level name (case-insensitive) or a numeric Python logging level. The flag wins when both are set.

An unrecognized value is reported and ignored:

```
$ INITRUNNER_LOG_LEVEL=TRACE initrunner run role.yaml -p hi
[log] ignoring invalid INITRUNNER_LOG_LEVEL='TRACE' (expected a level name such as DEBUG, INFO, WARNING)
```

## Log format

Each line is tagged with the emitting subsystem:

```
[agent.run] run 271ad196da9c of agent 'support-bot' failed [auth]: Model API error: status_code: 401, ...
[triggers.telegram] Telegram bot started polling
```

The tag is the module path with the `initrunner.` prefix stripped.

## Failed runs

Every failed run emits one WARNING at the default level, in every mode: one-shot, REPL, daemon, flow, team, `--serve`, A2A, and the dashboard:

```
[agent.run] run <run-id> of agent '<name>' failed [<category>]: <error>
```

The category is the same classification the retry and circuit-breaker logic uses: `auth`, `rate_limit`, `timeout`, `connection`, `server_error`, `usage_limit`, `content_blocked`, or `unknown`. It tells you what kind of problem you have before you read the message.

This matters most in the long-running modes. An A2A client or an OpenAI-compatible client sees a failed task or an error response, but the operator watching the process log needs the reason on the server side:

```
$ initrunner a2a serve role.yaml
A2A Server: support-bot
  Endpoint:   http://127.0.0.1:8000
[agent.run] run 01b147e59c75 of agent 'support-bot' failed [auth]: Model API error:
  status_code: 401, body: {'message': 'Invalid API key provided', 'code': 'invalid_api_key'}
```

Known secret formats (API keys, bearer tokens) are scrubbed from the message before it is logged, the same way they are scrubbed from the [audit trail](../core/audit.md).

## Debugging a provider connection

For a self-hosted OpenAI-compatible endpoint (LiteLLM, vLLM, Ollama, a gateway), `DEBUG` shows the request that failed and the response that came back:

```bash
INITRUNNER_LOG_LEVEL=DEBUG initrunner run role.yaml -p "ping"
```

```
[openai._base_client] Sending HTTP Request: POST http://litellm.internal/v1/chat/completions
[httpx] HTTP Request: POST http://litellm.internal/v1/chat/completions "HTTP/1.1 401 Unauthorized"
[openai._base_client] Re-raising status error
[agent.run] run 271ad196da9c of agent 'support-bot' failed [auth]: Model API error: status_code: 401,
  model_name: gpt-4o-mini, body: {'message': 'Invalid API key provided', 'code': 'invalid_api_key'}
```

`initrunner doctor` is the faster first step for credential and connectivity problems. Reach for `DEBUG` when doctor passes but a real run still fails.

## Containers and services

`INITRUNNER_LOG_LEVEL` is the right knob wherever you cannot edit the command line:

```yaml
# docker-compose.yml
services:
  agent:
    image: ghcr.io/vladkesler/initrunner:latest
    command: ["initrunner", "a2a", "serve", "/app/role.yaml"]
    environment:
      INITRUNNER_LOG_LEVEL: DEBUG
```

For structured, queryable run history rather than a text log, use the [audit trail](../core/audit.md) or [OpenTelemetry export](../core/observability.md).

## See also

- [Audit trail](../core/audit.md) for a durable record of every run
- [Observability](../core/observability.md) for OpenTelemetry traces and metrics
- [Doctor](doctor.md) for provider and credential checks
- [CLI reference](../getting-started/cli.md) for the full option list
