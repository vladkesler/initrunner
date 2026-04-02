# Autonomous Execution

Run agents in an iterative agentic loop that plans, executes, reflects, and self-schedules follow-ups.

## Overview

By default, InitRunner executes a single prompt-response cycle. **Autonomous mode** replaces this with an iterative loop where the agent:

1. Receives an initial prompt and begins working
2. Uses `todo` tools to track multi-step progress (add_todo, get_next_todo, update_todo)
3. Iterates -- each turn receives a continuation prompt with the current todo state
4. Auto-completes when all todo items reach terminal status, or calls `finish_task` explicitly
5. In daemon mode, can schedule follow-up runs via `schedule_followup` / `schedule_followup_at`

Autonomous mode integrates with [Reasoning Strategies](../core/reasoning.md#reasoning-strategies) (react, todo_driven, plan_execute, reflexion) for structured multi-step workflows.

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
    You are a helpful assistant. Break complex tasks into steps
    and work through them methodically.
  model:
    provider: openai
    name: gpt-5.4-mini-2026-03-17
  tools:
    - type: think
    - type: todo
  reasoning:
    pattern: todo_driven
    auto_plan: true
  guardrails:
    max_iterations: 10
    autonomous_token_budget: 50000
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
| `max_plan_steps` | `int` | `20` | Maximum number of plan steps. When using `todo` tools, prefer `TodoToolConfig.max_items` instead. |
| `iteration_delay_seconds` | `float` | `0` | Seconds to wait between iterations. Useful for rate-limiting API calls. |
| `max_scheduled_per_run` | `int` | `3` | Maximum follow-up runs an agent can schedule in a single execution. Daemon mode only. |
| `max_scheduled_total` | `int` | `50` | Maximum total pending scheduled tasks across the daemon lifetime. |
| `max_schedule_delay_seconds` | `int` | `86400` | Maximum delay (in seconds) for a scheduled follow-up. Default is 24 hours. |
| `compaction.enabled` | `bool` | `false` | Enable LLM-driven summarization of old messages before trimming. |
| `compaction.threshold` | `int` | `30` | Minimum message count before compaction activates. |
| `compaction.tail_messages` | `int` | `6` | Number of recent messages to keep verbatim (not summarized). |
| `compaction.model_override` | `str \| null` | `null` | Model to use for summarization. Defaults to the role's model. |
| `compaction.summary_prefix` | `str` | `"[CONVERSATION HISTORY SUMMARY]\n"` | Prefix prepended to the LLM summary. |

### `spec.guardrails` (autonomous fields)

These fields in the `guardrails:` block control autonomous execution limits:

| Field | Type | Default | Description |
|---|---|---|---|
| `max_iterations` | `int` | `10` | Maximum number of loop iterations before the run stops. Can be overridden with `--max-iterations` on the CLI. |
| `autonomous_token_budget` | `int \| null` | `null` (unlimited) | Total token budget across all iterations. The loop stops when this budget is exhausted. The current consumption is shown to the agent in the continuation prompt BUDGET block. |
| `autonomous_timeout_seconds` | `int \| null` | `null` (unlimited) | Wall-clock timeout for the entire autonomous run. Elapsed time is shown to the agent in the continuation prompt BUDGET block. |

## Tools

### Run-scoped reasoning tools

When your role declares `type: todo` and/or `type: think` in `spec.tools`, those toolsets are built fresh per-run with isolated state. The todo tool provides CRUD task management with priorities and dependencies; the think tool provides an accumulated reasoning chain. See [Reasoning Primitives](../core/reasoning.md) for full documentation.

### `finish_task`

Always available in autonomous mode. Signals that the current task is done.

```
finish_task(summary: str, status: "completed" | "blocked" | "failed" = "completed") -> str
```

- **`summary`** -- A brief summary of what was accomplished or why the agent is blocked/failed.
- **`status`** -- The outcome: `completed`, `blocked`, or `failed`.

The loop stops immediately when `finish_task` is called. The summary is persisted to memory (if configured) and displayed in the final summary panel.

When using the `todo` tool, you often don't need to call `finish_task` explicitly -- the loop auto-completes when all todo items reach terminal status.

### `schedule_followup` (daemon mode only)

Schedule a follow-up agent run after a delay.

```
schedule_followup(prompt: str, delay_seconds: int) -> str
```

- **`prompt`** -- The prompt for the follow-up run.
- **`delay_seconds`** -- Seconds to wait before running (minimum 1, maximum `max_schedule_delay_seconds`).

### `schedule_followup_at` (daemon mode only)

Schedule a follow-up agent run at a specific time.

```
schedule_followup_at(prompt: str, iso_datetime: str) -> str
```

- **`prompt`** -- The prompt for the follow-up run.
- **`iso_datetime`** -- ISO 8601 datetime string (e.g. `2024-01-15T14:30:00Z`). Naive datetimes are treated as UTC.

## How the Loop Works

1. **Iteration 1**: The user's original prompt is sent to the agent with run-scoped toolsets (todo, think, finish_task) injected. If a [reasoning strategy](../core/reasoning.md#reasoning-strategies) is configured, it may augment the prompt (e.g., `todo_driven` prepends "create a todo list first").

2. **Iterations 2+**: The reasoning strategy builds a continuation prompt that includes the current todo state (rendered as a formatted checklist) and a **BUDGET** block showing consumed iterations, tokens, and wall-clock time against their respective limits. This ensures the agent always sees its progress and remaining resources even if earlier messages were trimmed. The agent can use this information to skip low-priority items, compress remaining work, or wrap up before hitting a hard limit.

3. **History compaction, trimming, and budget enforcement**: After each iteration, if `compaction.enabled` is true and the history exceeds `compaction.threshold`, older messages are summarized by an LLM call and replaced with a single summary message. The most recent `compaction.tail_messages` messages are kept verbatim. After compaction, history is trimmed to `max_history_messages`. The first message (original prompt) is always preserved to maintain task context. Compaction follows the never-raises pattern -- if the summarization LLM call fails, the original history is kept and trimming proceeds normally. Finally, a token budget guard enforces that the trimmed history fits within the model's context window (see [Context Budget Guard](#context-budget-guard)).

4. **Budget check**: Before each iteration, cumulative token usage is compared against `autonomous_token_budget`. If exceeded, the loop stops with status `budget_exceeded`. After each iteration, current budget state (iterations completed, tokens consumed, elapsed time) is written to the agent's `ReflectionState` so the next continuation prompt includes a BUDGET block like:

   ```
   BUDGET:
   - Iteration: 3/10 (30%)
   - Tokens: 15,000/50,000 (30%)
   - Time: 45s/300s (15%)
   ```

   Lines for token budget and timeout only appear when those limits are configured. Percentages are truncated (not rounded).

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

In daemon mode (`initrunner run role.yaml --daemon`), triggers can opt into autonomous execution per trigger fire.

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

Full annotated example from `examples/roles/deployment-checker/role.yaml`:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: deployment-checker
  description: Autonomous deployment verification agent
  tags: [devops, autonomous, deployment, reasoning]
spec:
  role: |
    You are a deployment verification agent. When given one or more URLs to check,
    create a verification checklist, execute each step, and produce a pass/fail report.

    Workflow:
    1. Create a todo list with one item per URL to verify (use batch_add_todos)
    2. Work through each item: run curl to check the URL
    3. Mark each item completed (2xx) or failed (anything else)
    4. If a check fails, add a retry or investigation item with high priority
    5. When all checks are done, send a Slack summary with pass/fail results
    6. Call finish_task with the overall status
  model:
    provider: openai
    name: gpt-5.4-mini-2026-03-17
    temperature: 0.0
  tools:
    - type: think
    - type: todo
      max_items: 15
    - type: shell
      allowed_commands:
        - curl
      require_confirmation: false
      timeout_seconds: 30
    - type: slack
      webhook_url: "${SLACK_WEBHOOK_URL}"
      default_channel: "#deployments"
  reasoning:
    pattern: todo_driven
    auto_plan: true
  autonomy:
    max_history_messages: 20
    iteration_delay_seconds: 1
  guardrails:
    max_iterations: 8
    autonomous_token_budget: 30000
    autonomous_timeout_seconds: 300
    max_tokens_per_run: 10000
    max_tool_calls: 20
```

Run it:

```bash
initrunner run deployment-checker -a \
  -p "Verify the staging deployment at https://staging.example.com is healthy"
```

## Troubleshooting

### Agent never calls `finish_task`

The agent may reach `max_iterations` without explicitly finishing. To fix:

- Add `type: todo` to tools and set `reasoning.pattern: todo_driven` -- the loop auto-completes when all items are done, no explicit `finish_task` needed
- Make your system prompt clearly instruct the agent to call `finish_task` when done
- Increase `max_iterations` if the task genuinely requires more steps
- Check the iteration output panels -- if the agent seems stuck in a loop, adjust the `continuation_prompt`

### Token budget exceeded

The run stopped with status `budget_exceeded`. Options:

- Increase `autonomous_token_budget` in `spec.guardrails`
- Reduce `max_history_messages` to trim context sent per iteration
- Use a smaller/cheaper model to reduce tokens per iteration

### Scheduled tasks lost on restart

Scheduled follow-ups (`schedule_followup` / `schedule_followup_at`) are in-memory only. If the daemon process restarts, all pending scheduled tasks are lost. For persistent scheduling, use cron triggers with appropriate schedules instead.

### Agent loses context in long runs

By default, old messages are silently dropped when history exceeds `max_history_messages`. Enable compaction to summarize old messages instead:

```yaml
spec:
  autonomy:
    compaction:
      enabled: true
      threshold: 30
      tail_messages: 6
```

This uses an LLM call to produce a summary of the dropped messages, preserving key decisions, tool results, and open tasks. The summary is injected as a single message before the recent tail. You can use `model_override` to route summarization to a cheaper model.

Additionally, the context budget guard (see below) protects against context window overflow from oversized tool results, even without compaction enabled.

### Agent makes no tool calls

If the agent responds with text but doesn't use tools, the loop logs a debug message and continues to the next iteration with a nudge. If this persists, ensure your system prompt instructs the agent to use the available tools and call `finish_task`.

## Context Budget Guard

Long-running agents (autonomous and daemon modes) can accumulate message history that exceeds the model's context window, causing API errors. The context budget guard prevents this by automatically enforcing a token budget before every model call.

### How it works

A PydanticAI `history_processor` is registered on every role-driven agent. Before each model API call, it:

1. **Estimates tokens** in the message history using a fast heuristic (`len(text) // 4`)
2. If under budget (75% of the model's context window), passes through unchanged
3. If over budget, applies two stages:
   - **Truncate oversized parts**: any text-bearing part (tool returns, assistant responses, user prompts) exceeding `budget // 20` characters is truncated with a `[truncated]` suffix
   - **Drop oldest message pairs**: if still over budget, oldest request-response pairs are removed and replaced with a synthetic summary (`[N earlier messages dropped to fit context budget; tools used: ...]`)

Changes made by the processor are permanent for the rest of the run (PydanticAI writes processed history back into run state). The same reducer also runs between iterations via `reduce_history()`, after LLM compaction and count-based trimming.

### Configuration

Set `context_window` on `spec.model` to tell the guard your model's context size:

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-20250514
    context_window: 200000  # tokens
```

If `context_window` is not set, the guard uses provider-level defaults:

| Provider | Default context window |
|---|---|
| `anthropic` | 200,000 |
| `openai` | 128,000 |
| `google` | 1,000,000 |
| `groq` | 128,000 |
| `bedrock` | 200,000 |
| Unknown | 32,000 (with warning) |

For unknown providers, the guard falls back to a conservative 32,000 tokens and logs a warning. Set `context_window` explicitly to avoid this.

### Interaction with other limits

The context budget guard is complementary to:

- **Message count trimming** (`autonomy.max_history_messages`): trims by count, not tokens. A few large tool results can still overflow the context window.
- **LLM compaction** (`autonomy.compaction`): produces high-quality summaries but is opt-in, runs between iterations only, and only compresses the older prefix (not oversized recent parts).
- **`guardrails.input_tokens_limit`**: a hard cap that raises an error. The budget guard proactively compresses before reaching that limit.

For best results in long-running agents, combine all three: enable compaction for quality, rely on the budget guard for safety, and set `input_tokens_limit` as a hard cap.

### Example

See [`examples/roles/context-aware-scraper/`](../../examples/roles/context-aware-scraper/) for a complete autonomous scraper that fetches large web pages without hitting context limits. It combines `context_window`, LLM compaction, and token budgets.
