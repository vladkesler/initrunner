# Triggers — Configuration Reference

Triggers allow agents to run automatically in response to events — cron schedules, file changes, or incoming webhooks. They are configured in the `spec.triggers` list and activated with the `initrunner daemon` command.

Triggers follow the same discriminated-union pattern as tools and sinks, keyed on the `type` field.

## Trigger Types

| Type | Description |
|------|-------------|
| `cron` | Fire on a cron schedule |
| `file_watch` | Fire when files change in watched directories |
| `webhook` | Fire on incoming HTTP requests (localhost only) |

## Quick Example

```yaml
spec:
  triggers:
    - type: cron
      schedule: "0 9 * * 1"
      prompt: "Generate weekly status report."
    - type: file_watch
      paths: ["./watched"]
      extensions: [".md", ".txt"]
      prompt_template: "File changed: {path}. Summarize the changes."
    - type: webhook
      path: /webhook
      port: 8080
      secret: ${WEBHOOK_SECRET}
```

Run with:

```bash
initrunner daemon role.yaml
```

## Cron Trigger

Fires the agent on a cron schedule using [croniter](https://github.com/kiorky/croniter) syntax.

```yaml
triggers:
  - type: cron
    schedule: "0 9 * * 1"                    # required
    prompt: "Generate weekly status report."  # required
    timezone: UTC                             # default: UTC
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `schedule` | `str` | *(required)* | Cron expression. Standard 5-field syntax (`min hour day month weekday`). |
| `prompt` | `str` | *(required)* | The prompt sent to the agent when the trigger fires. |
| `timezone` | `str` | `"UTC"` | Timezone for schedule evaluation. |

### Schedule Syntax

Uses standard cron expressions:

| Field | Values |
|-------|--------|
| Minute | `0-59` |
| Hour | `0-23` |
| Day of month | `1-31` |
| Month | `1-12` |
| Day of week | `0-7` (0 and 7 are Sunday) |

Examples:
- `"0 9 * * 1"` — Every Monday at 9:00 AM
- `"*/5 * * * *"` — Every 5 minutes
- `"0 0 1 * *"` — First day of every month at midnight
- `"30 14 * * 1-5"` — Weekdays at 2:30 PM

### Behavior

- The trigger calculates the next fire time from the current UTC time.
- It sleeps in 1-second increments to allow clean shutdown on signal.
- When the fire time arrives, the configured `prompt` is sent to the agent.
- The trigger event includes `metadata: {"schedule": "..."}` with the cron expression.

## File Watch Trigger

Fires when files change in watched directories. Uses [watchfiles](https://watchfiles.helpmanual.io/) for efficient filesystem monitoring.

```yaml
triggers:
  - type: file_watch
    paths:                                              # required
      - "./watched"
      - "./data"
    extensions: [".md", ".txt"]                         # default: [] (all files)
    prompt_template: "File changed: {path}. Summarize." # default: "File changed: {path}"
    debounce_seconds: 1.0                               # default: 1.0
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `paths` | `list[str]` | *(required)* | Directories to watch for changes. |
| `extensions` | `list[str]` | `[]` | File extensions to filter on. Empty list watches all files. Include the dot (e.g. `".md"`). |
| `prompt_template` | `str` | `"File changed: {path}"` | Template for the prompt sent to the agent. `{path}` is replaced with the changed file's path. |
| `debounce_seconds` | `float` | `1.0` | Debounce interval in seconds. Multiple changes within this window are batched. |
| `process_existing` | `bool` | `false` | When `true`, fire once for each matching file already present in the watched directories on startup, before starting live monitoring. |

### Behavior

- Watches all specified `paths` simultaneously.
- When `extensions` is set, only files matching those extensions trigger events.
- Each changed file generates a separate trigger event with the rendered `prompt_template`.
- The `debounce_seconds` value is converted to milliseconds and passed to `watchfiles`.
- The trigger event includes `metadata: {"path": "..."}` with the changed file's absolute path.

### Startup Scan

When `process_existing: true`, the trigger scans each watched directory on startup before beginning live monitoring:

- One event is fired per existing file that matches the configured `extensions`.
- Files are processed in sorted order (alphabetical).
- After the initial scan completes, live monitoring begins normally.
- This is useful in compose pipelines where a service should process both existing and new files — for example, a content watcher that needs to handle drafts already present in a directory at startup.

### Template Variables

| Variable | Description |
|----------|-------------|
| `{path}` | Absolute path to the changed file |

## Webhook Trigger

Fires when an HTTP request is received on a local endpoint. Useful for integrating with GitHub webhooks, CI/CD systems, or other services that can send HTTP callbacks.

```yaml
triggers:
  - type: webhook
    path: /webhook          # default: "/webhook"
    port: 8080              # default: 8080
    method: POST            # default: "POST"
    secret: ${WEBHOOK_SECRET}  # default: null (no verification)
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | `str` | `"/webhook"` | URL path to listen on. |
| `port` | `int` | `8080` | Port to listen on. |
| `method` | `str` | `"POST"` | HTTP method to accept. Other methods return 405. |
| `secret` | `str \| null` | `null` | HMAC secret for signature verification. When set, requests must include a valid `X-Hub-Signature-256` header. |

### HMAC Verification

When `secret` is set, the webhook validates incoming requests using GitHub-style HMAC-SHA256 signatures:

1. The server computes `sha256=HMAC(secret, request_body)`.
2. It compares this with the `X-Hub-Signature-256` header using constant-time comparison.
3. Requests with invalid or missing signatures receive a `403 Forbidden` response.

This is compatible with GitHub webhook signatures and any system that uses the same signing scheme.

### Behavior

- The webhook server binds to `127.0.0.1` only (localhost). It is not exposed to external networks.
- The request body (decoded as UTF-8) becomes the prompt sent to the agent.
- The server is run via uvicorn in a thread with `log_level: warning`.
- The trigger event includes `metadata: {"path": "..."}` with the configured path.
- On success, the webhook returns `{"status": "ok"}` with a 200 status code.

### Example: GitHub Webhook

```yaml
triggers:
  - type: webhook
    path: /github
    port: 9000
    secret: ${GITHUB_WEBHOOK_SECRET}
```

```bash
# Test locally
curl -X POST http://127.0.0.1:9000/github \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=..." \
  -d '{"action": "opened", "pull_request": {"title": "Fix bug"}}'
```

## Daemon Mode

The `initrunner daemon` command starts all configured triggers and waits for events:

```bash
initrunner daemon role.yaml
initrunner daemon role.yaml --audit-db ./custom-audit.db
initrunner daemon role.yaml --no-audit
```

### CLI Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `role_file` | `Path` | *(required)* | Path to the role YAML file. |
| `--audit-db` | `Path` | `~/.initrunner/audit.db` | Path to audit database. |
| `--no-audit` | `bool` | `false` | Disable audit logging. |

### Lifecycle

1. The role is loaded and the agent is built.
2. All triggers are started in daemon threads via `TriggerDispatcher`.
3. When a trigger fires, the prompt is sent to the agent synchronously.
4. The result is displayed and dispatched to any configured sinks.
5. The daemon continues until interrupted.

### Signal Handling

The daemon installs handlers for `SIGINT` (Ctrl+C) and `SIGTERM`:

1. The signal sets a stop event.
2. All triggers are stopped via `TriggerDispatcher.stop_all()`.
3. Trigger threads are joined with a 5-second timeout.
4. The process exits cleanly.

### Trigger Events

Every trigger fires a `TriggerEvent` containing:

| Field | Type | Description |
|-------|------|-------------|
| `trigger_type` | `str` | `"cron"`, `"file_watch"`, or `"webhook"` |
| `prompt` | `str` | The prompt to send to the agent |
| `timestamp` | `str` | ISO 8601 timestamp of when the event was created |
| `metadata` | `dict[str, str]` | Type-specific metadata (schedule, path, etc.) |
