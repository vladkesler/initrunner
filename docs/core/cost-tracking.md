# Cost Tracking

InitRunner estimates USD cost for every agent run using the `genai-prices` library (a transitive dependency of `pydantic-ai`). Cost data is derived from token counts already stored in the audit trail -- nothing extra to configure.

## CLI Commands

The `initrunner cost` command group provides cost analytics from the audit database.

### `cost report`

Cost breakdown by agent.

```bash
initrunner cost report
initrunner cost report --agent my-agent
initrunner cost report --since 2026-04-01T00:00:00Z --until 2026-04-07T00:00:00Z
```

Output:

```
              Cost Report
┏━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Agent      ┃ Requests ┃ Tokens In ┃ Tokens Out ┃ Est. Cost ┃ Avg/Request ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ code-review│    142   │   890,200 │    312,400 │    $4.82  │    $0.0340  │
│ support    │     38   │   210,500 │     95,300 │    $1.22  │    $0.0321  │
└────────────┴──────────┴───────────┴────────────┴───────────┴─────────────┘

Total: 180 requests, $6.04 estimated
```

Filters: `--agent`, `--since`, `--until`, `--audit-db`.

### `cost summary`

High-level spend overview with time breakdowns and top agents.

```bash
initrunner cost summary
```

Shows today, this week, this month, and all-time totals. Lists the top 5 costliest agents and a 7-day daily trend.

### `cost by-model`

Cost grouped by model and provider.

```bash
initrunner cost by-model
initrunner cost by-model --since 2026-04-01T00:00:00Z
```

### `cost estimate`

Predict per-run cost from a role YAML before deploying.

```bash
initrunner cost estimate role.yaml
initrunner cost estimate role.yaml --prompt-tokens 1000
```

Output:

```
            Cost Estimate
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Metric                        ┃     Value ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ Model                         │ openai:…  │
│ Est. input tokens             │    3,400  │
│ Est. output tokens (typical)  │    1,228  │
│ Est. output tokens (max)      │    4,096  │
│ Per-run cost (typical)        │  $0.0098  │
│ Per-run cost (max)            │  $0.0241  │
│ Trigger firings/day           │      24.0 │
│ Daily estimate                │  $0.2352  │
│ Monthly estimate              │  $7.0560  │
└───────────────────────────────┴───────────┘
╭──────────────── Assumptions ─────────────────╮
│  - System prompt: ~85 tokens (len/4)         │
│  - 2 tools, 5 max calls                      │
│  - User prompt estimated at 200 tokens       │
│  - Output: 1228 typical, 4096 max            │
│  - Conservative: excludes skill content      │
│  - ~24.0 trigger firings/day                 │
╰──────────────────────────────────────────────╯
```

The estimator uses the raw system prompt only (skills are excluded and labeled conservative). If the model is unresolved (no `provider`/`name` in the role config), token estimates are shown but USD projections are skipped.

## USD Cost Budgets

In addition to token budgets, daemon and bot modes support USD-based cost limits.

```yaml
spec:
  guardrails:
    daemon_daily_cost_budget: 5.00    # USD per day
    daemon_weekly_cost_budget: 25.00  # USD per week
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `daemon_daily_cost_budget` | `float > 0` | *null* | Maximum USD spend per calendar day |
| `daemon_weekly_cost_budget` | `float > 0` | *null* | Maximum USD spend per ISO week |

### Behavior

- Cost is estimated after each run using `genai-prices` and accumulated in-memory.
- Daily cost resets at UTC midnight (same as `daemon_daily_token_budget`).
- Weekly cost resets when the ISO week number changes.
- At 80% consumption, a warning is logged.
- When the budget is exhausted, further trigger executions are skipped.
- Both counters reset on process restart.

### Startup Validation

When a cost budget is configured, InitRunner validates at startup that pricing data is available for the role's model and provider. If `genai-prices` doesn't cover that model, the daemon exits with a clear error:

```
Cannot enforce cost budget: no pricing data for custom-provider:custom-model.
Remove cost budget from guardrails or use a supported model/provider.
```

This prevents silent non-enforcement. Display contexts (CLI `cost report`, dashboard) show `N/A` instead.

### Combining Token and Cost Budgets

Token budgets and cost budgets are enforced independently. You can use both:

```yaml
spec:
  guardrails:
    daemon_token_budget: 5000000
    daemon_daily_token_budget: 500000
    daemon_daily_cost_budget: 10.00
    daemon_weekly_cost_budget: 50.00
```

Either limit being hit will pause the daemon.

## Dashboard UI

The `/cost` page in the dashboard provides visual cost analytics.

- **Summary strip** at the top shows today, this week, this month, and all-time spend totals. These values are fixed and do not change with the time range selector.
- **Period selector** (7d / 30d / 90d) controls the chart and both breakdown tables below.
- **Spend chart** shows daily cost as a bar chart. Hover any bar for date, cost, and run count.
- **By Agent table** breaks down cost per agent with runs, tokens, avg cost/run, and total. Rows link to the agent detail page.
- **By Model table** breaks down cost per model/provider combination.

The audit log (`/audit`) also shows a per-run cost column and includes cost in the detail drawer.

All cost values show `N/A` when pricing data is unavailable for a model/provider.

## Dashboard API

The dashboard exposes cost analytics via REST endpoints.

| Endpoint | Description |
|----------|-------------|
| `GET /api/cost/summary` | Today/week/month/all-time totals, top agents, daily trend |
| `GET /api/cost/by-agent` | Per-agent cost breakdown. Filters: `since`, `until`, `agent_name` |
| `GET /api/cost/daily` | Daily cost time series. Params: `days` (default 30), `agent_name` |
| `GET /api/cost/by-model` | Cost grouped by model/provider. Filters: `since`, `until` |

## How Cost is Calculated

1. Every agent run records `tokens_in`, `tokens_out`, `model`, and `provider` in the audit database.
2. Cost queries aggregate tokens via SQL (`GROUP BY agent/model/day`) and apply `genai-prices` per group.
3. If any group in a rolled-up total is unpriceable (unknown model/provider), the aggregate total shows `N/A` rather than a misleading partial sum.

Supported providers: OpenAI, Anthropic, Google, Groq, Mistral, xAI, DeepSeek, OpenRouter, Together, Fireworks.

---

See also: [token_control.md](../configuration/token_control.md) for token budgets, [audit.md](audit.md) for querying raw audit data, [dashboard.md](../interfaces/dashboard.md) for the web UI.
