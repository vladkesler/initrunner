# Always-on Services

Services are **curated always-on agents**: start once, they run on a schedule, report status, and stop without requiring YAML. Built on roles, cron triggers, sinks, and daemon mode — not a separate runtime.

**Prerequisites**

- Linux (process supervision is Linux-only in v1)
- A configured model provider (`initrunner setup` or env keys)
- For `collector`: `pip install "initrunner[search]"`

## Quick start

```bash
# See what's available
initrunner service list

# Start collector (needs initrunner[search] + a provider)
initrunner service start collector acme.com

# Or with explicit schedule / sink
initrunner service start collector acme.com \
  --every daily \
  --sink file:./collector-report.md

# Health
initrunner service status collector

# Force one cycle without waiting for cron
initrunner service run collector

# Stop (keep instance) or purge local files
initrunner service stop collector
initrunner service stop collector --purge
```

## Commands

| Command | What it does |
|---------|----------------|
| `service list` | Catalog + local status |
| `service info <slug>` | Params, requires, defaults |
| `service start <slug> [primary]` | Materialize + start daemon |
| `service status <slug>` | State, process health (with the daemon's RSS), last run, cost |
| `service run <slug>` | One-shot tick (briefly stops daemon if running) |
| `service stop [--purge]` | Stop daemon; `--purge` deletes instance dir |
| `service logs <slug>` | Daemon log tail |

### Start options

| Flag | Meaning |
|------|---------|
| positional | Value for the service `primary_param` (e.g. `target`) |
| `--set key=value` | Any declared param (duplicate keys rejected) |
| `--every` | `hourly` / `daily` / `weekly` / raw 5-field cron |
| `--sink file:/path` or `webhook:url` | Replace entire sink set (repeatable) |

Do not pass the primary both as a positional and via `--set`.

## Shipped services

### `collector`

Continuous monitoring for one target. Searches and reads public sources, diffs against memory, writes a brief when something material changes.

| Param | Required | Default | Notes |
|-------|----------|---------|-------|
| `target` | yes | — | Company, person, domain, topic (primary) |
| `alert_severity` | no | `medium` | `low` / `medium` / `high` |

Default schedule: `daily` (06:00 UTC). Requires: `initrunner[search]`.

Runtime agent name is `service-collector` (isolates audit, memory, and budgets from any role also named `collector`).

## How it works

1. **Catalog** — templates under `initrunner/service_catalog/<slug>/` (`service.yaml` + `role.yaml`).
2. **Start** — validates params and requirements, writes a generationed instance role with `{{ params.* }}` filled, injects schedule/sinks, starts a supervised daemon.
3. **Stop** — signals only a **verified** daemon process; instance config remains unless `--purge`.
4. **Run** — one-shot tick; if the service was running, the daemon is stopped, the tick runs, then the daemon is restarted.

```text
~/.initrunner/services/<slug>/
  state.json
  role.<n>.yaml
  daemon.log
  data/                 # relative file sinks

~/.initrunner/services/.locks/<slug>.lock   # never purged
```

## Purge scope

`stop --purge` deletes instance configuration, logs, and file outputs under `~/.initrunner/services/<slug>/`. It does **not** delete:

- global audit history
- memory store data for `service-<slug>`
- budget counters

## v1 limits

- Linux only for start / stop / run supervision
- One instance per service slug
- Agent entry only (no Flow services)
- Per-service process (not a multi-service supervisor)
- Sinks: `file:` and `webhook:` only
- No reboot auto-start (re-run `service start` after reboot)
