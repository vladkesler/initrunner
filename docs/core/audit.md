# Audit Trail

InitRunner logs every agent run to an append-only SQLite database. The audit trail records prompts, outputs, token usage, timing, tool call counts, success/failure status, and trigger context — providing a complete history of agent activity.

## Quick Start

Audit logging is enabled by default. Every `run`, `daemon`, and `serve` command writes to the audit database.

```bash
# Runs are automatically logged
initrunner run role.yaml -p "Hello!"

# Custom audit database path
initrunner run role.yaml -p "Hello!" --audit-db ./my-audit.db

# Disable audit logging
initrunner run role.yaml -p "Hello!" --no-audit

# Export audit records as JSON
initrunner audit export

# Export to a file, filtered by agent
initrunner audit export --agent my-agent -o audit.json
```

## Default Location

```
~/.initrunner/audit.db
```

The directory is created automatically if it doesn't exist.

## CLI Options

The `--audit-db` and `--no-audit` flags are available on `run`, `daemon`, and `serve` commands:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--audit-db` | `Path` | `~/.initrunner/audit.db` | Custom path to the audit database. |
| `--no-audit` | `bool` | `false` | Disable audit logging entirely. |

## Audit Export

The `audit export` command exports audit records as JSON or CSV. No role file is required — the audit database is shared across all agents.

```bash
initrunner audit export [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-f`, `--format` | `str` | `json` | Output format: `json` or `csv`. |
| `-o`, `--output` | `Path` | stdout | Write to file instead of stdout. |
| `--agent` | `str` | — | Filter by agent name. |
| `--run-id` | `str` | — | Filter by run ID. |
| `--trigger-type` | `str` | — | Filter by trigger type (e.g. `cron`, `file_watch`, `webhook`). |
| `--since` | `str` | — | Include records with `timestamp >= value` (ISO 8601). |
| `--until` | `str` | — | Include records with `timestamp <= value` (ISO 8601). |
| `--limit` | `int` | `1000` | Maximum number of records to return. |
| `--audit-db` | `Path` | `~/.initrunner/audit.db` | Custom path to the audit database. |

### Examples

**Export all records as JSON:**

```bash
initrunner audit export
```

**Export to a file:**

```bash
initrunner audit export -o audit-export.json
```

**Export as CSV:**

```bash
initrunner audit export -f csv -o audit.csv
```

**Filter by agent and time range:**

```bash
initrunner audit export --agent my-agent --since 2025-06-01T00:00:00Z --until 2025-07-01T00:00:00Z
```

**Export only trigger-initiated runs:**

```bash
initrunner audit export --trigger-type cron
initrunner audit export --trigger-type file_watch
```

**Limit results:**

```bash
initrunner audit export --limit 50
```

### JSON Output Format

JSON output deserializes `trigger_metadata` back to a dict:

```json
[
  {
    "run_id": "a1b2c3d4e5f6",
    "agent_name": "my-agent",
    "timestamp": "2025-06-15T09:00:00+00:00",
    "user_prompt": "Generate weekly status report.",
    "model": "gpt-4o-mini",
    "provider": "openai",
    "output": "Here is your weekly report...",
    "tokens_in": 150,
    "tokens_out": 500,
    "total_tokens": 650,
    "tool_calls": 2,
    "duration_ms": 3200,
    "success": true,
    "error": null,
    "trigger_type": "cron",
    "trigger_metadata": {
      "schedule": "0 9 * * 1"
    }
  }
]
```

Records are ordered by timestamp descending (most recent first).

### CSV Output Format

CSV output keeps `trigger_metadata` as a raw JSON string:

```csv
run_id,agent_name,timestamp,...,trigger_type,trigger_metadata
a1b2c3d4e5f6,my-agent,2025-06-15T09:00:00+00:00,...,cron,"{""schedule"": ""0 9 * * 1""}"
```

## Trigger Traceability

When an agent run is initiated by a trigger in daemon mode, the audit record captures which trigger caused it:

- **`trigger_type`** — The type of trigger (`cron`, `file_watch`, `webhook`).
- **`trigger_metadata`** — A JSON object with trigger-specific details.

For manually initiated runs (via `run` or `serve`), both fields are `null`.

### Metadata by Trigger Type

| Trigger Type | Typical Metadata Keys |
|-------------|----------------------|
| `cron` | `schedule` |
| `file_watch` | `path`, `change_type` |
| `webhook` | `method`, `path` |

### Filtering by Trigger

Use `audit export` to find all trigger-initiated runs:

```bash
# All cron-triggered runs
initrunner audit export --trigger-type cron

# All file-watch-triggered runs for a specific agent
initrunner audit export --trigger-type file_watch --agent my-watcher
```

Or query the database directly:

```sql
-- Runs initiated by triggers (any type)
SELECT * FROM audit_log WHERE trigger_type IS NOT NULL ORDER BY timestamp DESC;

-- Cron-triggered runs with schedule details
SELECT timestamp, agent_name, user_prompt, trigger_metadata
FROM audit_log
WHERE trigger_type = 'cron'
ORDER BY timestamp DESC;
```

## Database Schema

The audit database uses WAL journal mode for concurrent read/write safety.

### `audit_log` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER PRIMARY KEY` | Auto-incrementing row ID |
| `run_id` | `TEXT` | Unique identifier for the run |
| `agent_name` | `TEXT` | Agent name from `metadata.name` |
| `timestamp` | `TEXT` | ISO 8601 timestamp of the run |
| `user_prompt` | `TEXT` | The prompt sent to the agent |
| `model` | `TEXT` | Model name (e.g. `gpt-4o-mini`) |
| `provider` | `TEXT` | Model provider (e.g. `openai`) |
| `output` | `TEXT` | The agent's response text |
| `tokens_in` | `INTEGER` | Input tokens consumed |
| `tokens_out` | `INTEGER` | Output tokens generated |
| `total_tokens` | `INTEGER` | Total tokens (in + out) |
| `tool_calls` | `INTEGER` | Number of tool calls made |
| `duration_ms` | `INTEGER` | Run duration in milliseconds |
| `success` | `BOOLEAN` | Whether the run completed successfully |
| `error` | `TEXT` | Error message (null on success) |
| `trigger_type` | `TEXT` | Trigger type that initiated the run (null for manual runs) |
| `trigger_metadata` | `TEXT` | JSON string with trigger-specific metadata (null for manual runs) |

### Indexes

| Index | Column(s) | Purpose |
|-------|-----------|---------|
| `idx_agent_name` | `agent_name` | Filter by agent |
| `idx_timestamp` | `timestamp` | Time-range queries |
| `idx_run_id` | `run_id` | Look up specific runs |
| `idx_trigger_type` | `trigger_type` | Filter by trigger type |

### Schema Migration

The `trigger_type` and `trigger_metadata` columns are added automatically when opening an existing audit database that was created before this feature. The migration is idempotent — opening the same database multiple times is safe.

Existing records will have `null` for both trigger columns.

## Never-Raises Guarantee

The audit logger follows a strict **never-raises** pattern: if writing an audit record fails (disk full, permissions error, database corruption), the error is printed to stderr but **never** propagated as an exception. This ensures that audit failures cannot crash agent runs.

```
[audit] Failed to write audit record: disk I/O error
```

This design means your agent continues operating even if the audit database becomes unavailable.

## Auto-Pruning

The audit logger automatically prunes old records during normal operation. Every 1000 inserts (configurable), `log()` calls `prune()` in the background to enforce retention limits. This prevents the audit database from growing unboundedly in high-frequency daemon and trigger scenarios.

### Defaults

| Parameter | Default | Description |
|-----------|---------|-------------|
| `auto_prune_interval` | `1000` | Number of inserts between automatic prune runs. Set to `0` to disable. |
| `retention_days` | `90` | Records older than this are deleted. |
| `max_records` | `100,000` | Hard cap — oldest records beyond this count are deleted. |

Auto-pruning preserves the **never-raises** guarantee: if pruning fails, the error is logged to stderr and the insert still succeeds.

Manual pruning via `initrunner audit prune` remains available for one-off cleanup.

## Querying the Audit Database

Use `sqlite3` to query the audit trail directly:

```bash
# Open the database
sqlite3 ~/.initrunner/audit.db
```

### Example Queries

**Recent runs for an agent:**

```sql
SELECT timestamp, user_prompt, output, tokens_in, tokens_out, duration_ms, success
FROM audit_log
WHERE agent_name = 'my-agent'
ORDER BY timestamp DESC
LIMIT 10;
```

**Failed runs:**

```sql
SELECT timestamp, agent_name, user_prompt, error
FROM audit_log
WHERE success = 0
ORDER BY timestamp DESC;
```

**Token usage summary by agent:**

```sql
SELECT agent_name,
       COUNT(*) as runs,
       SUM(tokens_in) as total_in,
       SUM(tokens_out) as total_out,
       SUM(total_tokens) as total_tokens,
       AVG(duration_ms) as avg_duration_ms
FROM audit_log
GROUP BY agent_name;
```

**Runs in a time range:**

```sql
SELECT *
FROM audit_log
WHERE timestamp >= '2025-06-01' AND timestamp < '2025-07-01'
ORDER BY timestamp;
```

**Most expensive runs (by token usage):**

```sql
SELECT timestamp, agent_name, user_prompt, total_tokens, duration_ms
FROM audit_log
ORDER BY total_tokens DESC
LIMIT 10;
```

**Tool call frequency:**

```sql
SELECT agent_name,
       AVG(tool_calls) as avg_tool_calls,
       MAX(tool_calls) as max_tool_calls
FROM audit_log
GROUP BY agent_name;
```

**Trigger-initiated runs summary:**

```sql
SELECT trigger_type,
       COUNT(*) as runs,
       AVG(duration_ms) as avg_duration_ms,
       SUM(total_tokens) as total_tokens
FROM audit_log
WHERE trigger_type IS NOT NULL
GROUP BY trigger_type;
```

## WAL Journal Mode

The audit database uses SQLite's Write-Ahead Logging (WAL) mode, which allows concurrent readers and a single writer without blocking. This is set automatically when the database is created:

```sql
PRAGMA journal_mode=WAL;
```

WAL mode creates two additional files alongside the database:

- `audit.db-wal` — Write-ahead log
- `audit.db-shm` — Shared memory file

These are normal and managed automatically by SQLite.
