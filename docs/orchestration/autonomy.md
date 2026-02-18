# Autonomous Execution

Run agents in an iterative agentic loop that plans, executes, reflects, and self-schedules follow-ups.

## Overview

By default, InitRunner executes a single prompt-response cycle. **Autonomous mode** replaces this with an iterative loop where the agent:

1. Receives an initial prompt and begins working
2. Uses `update_plan` to track multi-step progress
3. Iterates — each turn receives a continuation prompt with the current plan state
4. Calls `finish_task` to signal completion, or stops when the iteration/token budget is exhausted
5. In daemon mode, can schedule follow-up runs via `schedule_followup` / `schedule_followup_at`

This is useful for research tasks, multi-step workflows, and any work that requires the agent to break a problem into steps and work through them methodically.

## Quick Start

Minimal role YAML:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: my-agent
  description: An autonomous agent
spec:
  role: |
    You are a helpful assistant. Break complex tasks into steps,
    track progress with update_plan, and call finish_task when done.
  model:
    provider: openai
    name: gpt-5-mini
  guardrails:
    max_iterations: 10
```

Run it:

```bash
initrunner run my-agent.yaml -p "Summarize the key differences between REST and GraphQL" -a
```

The `-a` / `--autonomous` flag activates the agentic loop.

## Configuration Reference

### `spec.autonomy`

Controls loop behavior. All fields are optional — defaults apply if the `autonomy:` block is omitted entirely.

| Field | Type | Default | Description |
|---|---|---|---|
| `continuation_prompt` | `str` | `"Continue working on the task..."` | Prompt injected at the start of each non-first iteration. The agent's current plan state is appended automatically. |
| `max_history_messages` | `int` | `40` | Maximum messages retained in conversation history between iterations. Older messages are trimmed (first message is always preserved). |
| `max_plan_steps` | `int` | `20` | Maximum number of steps accepted by `update_plan`. Extra steps are silently dropped. |
| `iteration_delay_seconds` | `float` | `0` | Seconds to wait between iterations. Useful for rate-limiting API calls. |
| `max_scheduled_per_run` | `int` | `3` | Maximum follow-up runs an agent can schedule in a single execution. Daemon mode only. |
| `max_scheduled_total` | `int` | `50` | Maximum total pending scheduled tasks across the daemon lifetime. |
| `max_schedule_delay_seconds` | `int` | `86400` | Maximum delay (in seconds) for a scheduled follow-up. Default is 24 hours. |

### `spec.guardrails` (autonomous fields)

These fields in the `guardrails:` block control autonomous execution limits:

| Field | Type | Default | Description |
|---|---|---|---|
| `max_iterations` | `int` | `10` | Maximum number of loop iterations before the run stops. Can be overridden with `--max-iterations` on the CLI. |
| `autonomous_token_budget` | `int \| null` | `null` (unlimited) | Total token budget across all iterations. The loop stops when this budget is exhausted. |

## Tools

Four tools are automatically injected when running in autonomous mode. You do not need to declare them in `spec.tools`.

### `finish_task`

Signal that the current task is done.

```
finish_task(summary: str, status: "completed" | "blocked" | "failed" = "completed") -> str
```

- **`summary`** — A brief summary of what was accomplished or why the agent is blocked/failed.
- **`status`** — The outcome: `completed`, `blocked`, or `failed`.

The loop stops immediately when `finish_task` is called. The summary is persisted to memory (if configured) and displayed in the final summary panel.

### `update_plan`

Replace the current plan with a new list of steps.

```
update_plan(steps: list[dict]) -> str
```

Each step dict accepts:

| Key | Required | Description |
|---|---|---|
| `description` | Yes | What this step does |
| `status` | No | One of: `pending`, `in_progress`, `completed`, `failed`, `skipped`. Defaults to `pending`. |
| `notes` | No | Additional context or results for this step |

The plan is fully replaced on each call (not patched). This is intentional — full replacement is more reliable for LLMs than index-based updates. The plan is injected into every continuation prompt so the agent always sees its progress, even after history trimming.

### `schedule_followup` (daemon mode only)

Schedule a follow-up agent run after a delay.

```
schedule_followup(prompt: str, delay_seconds: int) -> str
```

- **`prompt`** — The prompt for the follow-up run.
- **`delay_seconds`** — Seconds to wait before running (minimum 1, maximum `max_schedule_delay_seconds`).

### `schedule_followup_at` (daemon mode only)

Schedule a follow-up agent run at a specific time.

```
schedule_followup_at(prompt: str, iso_datetime: str) -> str
```

- **`prompt`** — The prompt for the follow-up run.
- **`iso_datetime`** — ISO 8601 datetime string (e.g. `2024-01-15T14:30:00Z`). Naive datetimes are treated as UTC.

## How the Loop Works

1. **Iteration 1**: The user's original prompt is sent to the agent with the reflection toolset (`finish_task`, `update_plan`) injected.

2. **Iterations 2+**: A continuation prompt is built from `autonomy.continuation_prompt` plus the current `ReflectionState` (the plan rendered as a checklist). This ensures the agent always sees its progress even if earlier messages were trimmed.

3. **History trimming**: After each iteration, message history is trimmed to `max_history_messages` messages. The first message (original prompt) is always preserved to maintain task context.

4. **Budget check**: Before each iteration, cumulative token usage is compared against `autonomous_token_budget`. If exceeded, the loop stops with status `budget_exceeded`.

5. **Terminal conditions** (the loop stops when any of these occur):
   - The agent calls `finish_task` → status from the tool call (`completed`, `blocked`, or `failed`)
   - Token budget is exhausted → `budget_exceeded`
   - An execution error occurs → `error`
   - `max_iterations` is reached → `max_iterations`

6. **Rate limiting**: If `iteration_delay_seconds > 0`, the loop sleeps between iterations.

7. **Result**: An `AutonomousResult` is returned with aggregate statistics (total tokens, duration, iteration count) and the final status.

## CLI Usage

```bash
# Basic autonomous run
initrunner run role.yaml -p "Research quantum computing advances" -a

# Override max iterations
initrunner run role.yaml -p "Research quantum computing advances" -a --max-iterations 20

# Dry run (no API calls, uses TestModel)
initrunner run role.yaml -p "Test the agentic loop" -a --dry-run
```

Flags:

| Flag | Description |
|---|---|
| `-a`, `--autonomous` | Enable autonomous agentic loop mode |
| `--max-iterations N` | Override `guardrails.max_iterations` for this run |
| `--dry-run` | Use `TestModel` instead of making real API calls |

Note: `--autonomous` requires `--prompt` (`-p`) and is mutually exclusive with `--interactive` (`-i`).

## Daemon Mode

In daemon mode (`initrunner daemon role.yaml`), triggers can opt into autonomous execution per trigger fire.

Set `autonomous: true` on any trigger config:

```yaml
spec:
  triggers:
    - type: cron
      schedule: "0 */6 * * *"
      prompt: "Check for new research papers and summarize findings"
      autonomous: true
    - type: webhook
      path: /research
      port: 8080
      autonomous: true
```

When a trigger with `autonomous: true` fires, the agent runs through the full agentic loop (not a single-shot response). Scheduled follow-up runs (via `schedule_followup` / `schedule_followup_at`) also use the agentic loop if `spec.autonomy` is configured.

### Scheduling

When `spec.autonomy` is configured, daemon-mode agents gain access to the `schedule_followup` and `schedule_followup_at` tools. These allow the agent to create one-shot follow-up runs.

Important caveats:

- **In-memory only** — scheduled tasks are stored in memory and lost on daemon restart
- **Bounded** — limited by `max_scheduled_per_run` (per trigger fire) and `max_scheduled_total` (across daemon lifetime)
- **Max delay** — individual schedules cannot exceed `max_schedule_delay_seconds` (default 24h)

## Memory Integration

When `spec.memory` is configured:

- The autonomous run's session (all iterations) is saved for `--resume` in interactive mode
- **Episodic auto-capture**: when `finish_task` is called with a summary, the summary is persisted as an episodic memory with category `autonomous_run` and structured metadata
- **Consolidation**: on autonomous loop exit, consolidation runs automatically (if `consolidation.interval` is `after_autonomous` or `after_session`) to extract semantic facts from episodic records
- Memories from previous runs can be recalled by the agent via the `recall` tool, which searches across all memory types (episodic, semantic, procedural)
- The agent also has access to `record_episode()` (to manually capture episodes) and `learn_procedure()` (to store reusable policies) when those memory types are enabled
- **Procedural injection**: any learned procedures are auto-injected into the system prompt at the start of each iteration
- In daemon mode, sessions are pruned after each trigger execution and episodic memories are auto-captured with trigger metadata

See [Memory System](../core/memory.md) for full details on memory types, consolidation, and configuration.

## Budget and Safety

Multiple layers of limits prevent runaway execution:

| Limit | Scope | Default | Config location |
|---|---|---|---|
| `max_iterations` | Per autonomous run | `10` | `spec.guardrails` |
| `autonomous_token_budget` | Per autonomous run | Unlimited | `spec.guardrails` |
| `max_tokens_per_run` | Per single iteration | `50000` | `spec.guardrails` |
| `max_tool_calls` | Per single iteration | `20` | `spec.guardrails` |
| `timeout_seconds` | Per single iteration | `300` | `spec.guardrails` |
| `max_scheduled_per_run` | Per trigger fire | `3` | `spec.autonomy` |
| `max_scheduled_total` | Per daemon lifetime | `50` | `spec.autonomy` |
| `iteration_delay_seconds` | Between iterations | `0` | `spec.autonomy` |
| `daemon_token_budget` | Per daemon lifetime | Unlimited | `spec.guardrails` |
| `daemon_daily_token_budget` | Per calendar day | Unlimited | `spec.guardrails` |

For production autonomous agents, it is recommended to set `autonomous_token_budget` and keep `max_iterations` reasonable.

## Example: Deployment Checker

Full annotated example from `examples/roles/deployment-checker.yaml`:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: deployment-checker
  description: Autonomous deployment verification agent that checks endpoints, investigates failures, and reports results
  tags: [devops, autonomous, deployment]
spec:
  role: |
    You are a deployment verification agent. When given one or more URLs to check,
    create a verification plan, execute each step, and produce a pass/fail report.

    Workflow:
    1. Use update_plan to create a checklist — one step per URL to verify
    2. Run curl -sSL -o /dev/null -w "%{http_code} %{time_total}s" for each URL
    3. Mark each step passed (2xx) or failed (anything else)
    4. If a check fails, adapt your plan — add a retry or investigation step
    5. When done, send a Slack summary with pass/fail results per URL
    6. Call finish_task with the overall status

    Keep each plan step concise. Mark steps completed/failed as you go.
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.0
  tools:
    - type: shell
      allowed_commands:
        - curl
      require_confirmation: false
      timeout_seconds: 30
    - type: slack
      webhook_url: "${SLACK_WEBHOOK_URL}"
      default_channel: "#deployments"
      username: Deploy Checker
      icon_emoji: ":white_check_mark:"
  autonomy:
    max_plan_steps: 6
    max_history_messages: 20
    iteration_delay_seconds: 1
    max_scheduled_per_run: 1
  guardrails:
    max_iterations: 6
    autonomous_token_budget: 30000
    max_tokens_per_run: 10000
    max_tool_calls: 15
```

Run it:

```bash
initrunner run examples/roles/deployment-checker.yaml \
  -p "Verify the staging deployment at https://staging.example.com is healthy" \
  -a
```

## Troubleshooting

### Agent never calls `finish_task`

The agent may reach `max_iterations` without explicitly finishing. To fix:

- Make your system prompt (the `role:` field) clearly instruct the agent to call `finish_task` when done
- Increase `max_iterations` if the task genuinely requires more steps
- Check the iteration output panels — if the agent seems stuck in a loop, adjust the `continuation_prompt`

### Token budget exceeded

The run stopped with status `budget_exceeded`. Options:

- Increase `autonomous_token_budget` in `spec.guardrails`
- Reduce `max_history_messages` to trim context sent per iteration
- Use a smaller/cheaper model to reduce tokens per iteration

### Scheduled tasks lost on restart

Scheduled follow-ups (`schedule_followup` / `schedule_followup_at`) are in-memory only. If the daemon process restarts, all pending scheduled tasks are lost. For persistent scheduling, use cron triggers with appropriate schedules instead.

### Agent makes no tool calls

If the agent responds with text but doesn't use tools, the loop logs a debug message and continues to the next iteration with a nudge. If this persists, ensure your system prompt instructs the agent to use the available tools and call `finish_task`.
