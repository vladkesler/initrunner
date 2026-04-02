# Reasoning Primitives

InitRunner's reasoning system gives agents structured cognitive tools and execution strategies. Two orthogonal layers compose naturally: **cognitive tools** (think, todo, spawn) that the LLM uses voluntarily within a turn, and **reasoning strategies** (react, todo_driven, plan_execute, reflexion) that orchestrate behavior across turns in autonomous mode.

All reasoning tools are **run-scoped** -- built fresh per-run with isolated state, never leaking across REPL/daemon sessions.

## Quick Start

Minimal autonomous agent with structured reasoning:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: planner
  description: Autonomous planner with structured reasoning
spec:
  role: |
    You are a senior project planner. Break tasks into structured
    todo lists, research each item, and synthesize findings.
  model:
    provider: openai
    name: gpt-5.4-mini-2026-03-17
  tools:
    - type: think
      critique: true
    - type: todo
      max_items: 20
    - type: search
      provider: duckduckgo
  reasoning:
    pattern: todo_driven
    auto_plan: true
  autonomy:
    max_plan_steps: 20
  guardrails:
    max_iterations: 15
    autonomous_token_budget: 100000
```

Run it:

```bash
initrunner run planner.yaml -a -p "Research the top 3 Python web frameworks and compare them."
```

The agent will:
1. Create a structured todo list (batch_add_todos)
2. Work through each item (get_next_todo, update_todo)
3. Auto-complete when all items reach terminal status

## Think Tool

Gives the agent a scratchpad that accumulates reasoning as a numbered chain. Unlike a plain "thought recorded" response, the agent sees its full reasoning history on every call -- surviving context trimming.

### Configuration

```yaml
tools:
  - type: think
    critique: true       # nudge self-critique every 5th thought
    max_thoughts: 30     # ring buffer capacity (default: 50)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `critique` | bool | `false` | Append self-critique nudge every 5th thought |
| `max_thoughts` | int | `50` | Ring buffer capacity (1-200) |

### How it works

Each `think(thought)` call appends the thought and returns the full numbered chain:

```
Thoughts (3):
  1. The user wants a CLI tool, so startup time matters
  2. Python is faster to develop but Rust compiles to a single binary
  3. Distribution is the key differentiator here
```

With `critique: true`, every 5th thought appends:

> You have recorded 5 thoughts. Before proceeding, critically evaluate your reasoning. What assumptions might be wrong? What have you missed?

The ring buffer evicts the oldest thought when full, bounding token overhead to ~3500 tokens at 50 thoughts.

### When to use

- **Always add** `type: think` for agents doing multi-step reasoning
- **Enable critique** for complex tasks where self-correction matters
- **Reduce max_thoughts** for agents with tight token budgets

### Modes

The think tool works in both single-shot and autonomous mode. In single-shot, the agent can call it multiple times within one run. In autonomous mode, thoughts persist across iterations through the run-scoped state.

## Todo Tool

Priority-aware task management with dependency resolution. Operates on the agent's unified `ReflectionState`, giving a single source of truth for progress and budget awareness.

### Configuration

```yaml
tools:
  - type: todo
    max_items: 30        # max concurrent items (default: 30)
    shared: false        # sub-agent visibility (default: false)
    shared_path: ""      # SQLite path (required when shared: true)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_items` | int | `30` | Maximum concurrent items (1-100) |
| `shared` | bool | `false` | Back state with SQLite for sub-agent access |
| `shared_path` | str | `""` | SQLite file path (required when `shared: true`) |

### Tool functions exposed to the LLM

| Tool | Description |
|------|-------------|
| `add_todo(description, priority?, depends_on?)` | Create an item. Returns its 8-char ID + the full formatted list. |
| `batch_add_todos(items)` | Create multiple items at once. Supports inter-batch dependency refs via index ("0", "1", ...). |
| `update_todo(id, status?, notes?, priority?)` | Update fields on an existing item. Returns the full formatted list. |
| `remove_todo(id)` | Remove an item and clean up dangling dependency references. |
| `list_todos(status_filter?)` | Show all items, or filter by status. |
| `get_next_todo()` | Return the highest-priority pending item whose dependencies are all in terminal status. |
| `finish_task(summary, status)` | Explicitly signal task completion (completed/blocked/failed). |

### Statuses

| Status | Terminal? | Icon | Description |
|--------|-----------|------|-------------|
| `pending` | No | `[ ]` | Not started |
| `in_progress` | No | `[>]` | Currently being worked on |
| `completed` | Yes | `[x]` | Successfully finished |
| `failed` | Yes | `[!]` | Failed |
| `skipped` | Yes | `[-]` | Intentionally skipped |

### Priority ordering

`critical > high > medium > low`. `get_next_todo()` returns the highest-priority pending item whose dependencies are all in terminal status.

### Dependencies

Items can depend on other items by ID. The agent specifies dependencies when creating items:

```
add_todo("Deploy to staging", priority="high", depends_on=["abc12345"])
```

Or in batch, using 0-based batch indices:

```
batch_add_todos([
  {"description": "Write tests", "priority": "high"},
  {"description": "Run tests", "depends_on": ["0"]},
  {"description": "Deploy", "depends_on": ["1"]}
])
```

Cycles are detected via Kahn's algorithm and rejected immediately. When an item is removed, dangling dependency references in other items are cleaned up.

### Auto-completion

When every item in the list reaches a terminal status (completed, failed, or skipped), the autonomous loop automatically signals completion. The agent does not need to call `finish_task` explicitly -- though it can do so at any time to override.

### Shared mode

When `shared: true`, the todo list is backed by SQLite with WAL mode for concurrent access. Sub-agents spawned via the delegate or spawn tool can read and update the same list.

```yaml
tools:
  - type: todo
    shared: true
    shared_path: ./.initrunner/shared_todo.db
```

## Spawn Tool

Non-blocking parallel agent execution. Spawn sub-agents as background tasks, poll for results, and await completion -- all within a single agent run.

### Configuration

```yaml
tools:
  - type: spawn
    max_concurrent: 3         # parallel task limit (default: 4, max: 16)
    timeout_seconds: 120      # per-task timeout (default: 300)
    agents:
      - name: researcher
        role_file: ./agents/researcher.yaml
        description: Researches a specific topic
      - name: coder
        role_file: ./agents/coder.yaml
        description: Writes and reviews code
    shared_memory:            # optional shared memory for sub-agents
      store_path: ./.initrunner/shared.db
      max_memories: 1000
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `agents` | list | required | Agent refs with `name`, `role_file` or `url`, and `description` |
| `max_concurrent` | int | `4` | Maximum parallel tasks (1-16) |
| `max_depth` | int | `3` | Maximum delegation depth |
| `timeout_seconds` | int | `300` | Per-task wall-clock timeout |
| `shared_memory` | object | `null` | Shared LanceDB memory config |

Each agent ref needs either `role_file` (inline execution via `InlineInvoker`) or `url` (remote execution via `McpInvoker`).

### Tool functions exposed to the LLM

| Tool | Description |
|------|-------------|
| `spawn_agent(agent_name, prompt)` | Submit a background task. Returns immediately with a task_id. |
| `poll_tasks(task_ids?)` | Check status of specific tasks or all. Returns a formatted status table. |
| `await_tasks(task_ids)` | Block until all specified tasks complete. Returns their results. |
| `await_any(task_ids)` | Block until any one task completes. Returns its result. |
| `cancel_task(task_id)` | Cancel a running background task. |

### How it works

The spawn pool maintains a private asyncio event loop in a daemon thread. When the agent calls `spawn_agent`, the task is submitted via `asyncio.run_coroutine_threadsafe()`. The underlying invokers (`InlineInvoker` for local agents, `McpInvoker` for remote) run via `asyncio.to_thread()`.

Task statuses: `running`, `completed`, `failed`, `timeout`.

The pool is cleaned up when the run ends -- remaining tasks are cancelled and the event loop is stopped.

### Typical usage pattern

```
1. spawn_agent("researcher", "Find stats on Python adoption")  -> task_a
2. spawn_agent("researcher", "Find stats on Rust adoption")    -> task_b
3. await_tasks([task_a, task_b])                                -> results
4. Synthesize results into final answer
```

## Reasoning Strategies

The `spec.reasoning` config controls how the autonomous runner orchestrates agent behavior across turns. Strategies operate in **autonomous mode only** (`-a` flag).

### Configuration

```yaml
spec:
  reasoning:
    pattern: todo_driven     # react | todo_driven | plan_execute | reflexion
    auto_plan: true          # prepend planning instructions to first turn
    reflection_rounds: 0     # post-completion self-critique rounds (reflexion only)
    auto_detect: true        # infer pattern from tool/autonomy config
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pattern` | string | `"react"` | Reasoning pattern to use |
| `auto_plan` | bool | `false` | Prepend "create a todo list" to first turn |
| `reflection_rounds` | int | `0` | Number of self-critique rounds after completion |
| `auto_detect` | bool | `true` | Infer pattern from tool/autonomy config |

### Budget-aware continuation prompts

All strategies inject a `BUDGET:` block into the continuation prompt (iterations 2+) so the agent knows how much runway it has left. The autonomous runner populates `ReflectionState` with budget fields after each iteration, and `format_reflection_state()` renders them:

```
CURRENT STATUS:
Todo List:
  [x] 8c753a3f [high] Research Python
  [>] a1b2c3d4 [high] Research Rust
  [ ] e5f6g7h8 [medium] Write comparison

BUDGET:
- Iteration: 2/10 (20%)
- Tokens: 12,000/50,000 (24%)
- Time: 30s/300s (10%)
```

The iteration line always appears in autonomous mode. Token and time lines only appear when `autonomous_token_budget` or `autonomous_timeout_seconds` are configured in guardrails. Percentages are truncated to whole integers.

This lets the agent make informed decisions: skip low-priority items when iterations are running out, compress remaining work when the token budget is tight, or wrap up proactively before hitting a hard limit.

### Patterns

#### react (default)

Standard ReAct loop. The LLM decides when and how to use tools. No extra orchestration from the runner. This is the pattern every agent uses today.

```yaml
reasoning:
  pattern: react
```

#### todo_driven

Plan-first execution. The runner prepends instructions to create a structured todo list on the first turn. Continuation prompts guide the agent: "Check your todo list. Get the next item and work on it."

**Requires** a `todo` tool in `spec.tools`.

```yaml
tools:
  - type: todo
reasoning:
  pattern: todo_driven
  auto_plan: true        # recommended
```

How it works:
1. First turn: prompt is prefixed with "Before starting, create a structured todo list..."
2. Subsequent turns: "Check your todo list. Call get_next_todo..."
3. Loop exits when all items reach terminal status (auto-completion) or the agent calls `finish_task`

#### plan_execute

Two-phase execution. Phase 1 (planning): the agent creates a comprehensive plan without executing. Phase 2 (execution): the agent works through plan items. The agent explicitly calls `finalize_plan()` to signal that planning is complete and transition to execution.

**Requires** a `todo` tool in `spec.tools`.

```yaml
tools:
  - type: todo
reasoning:
  pattern: plan_execute
```

How it works:
1. First turn: "PHASE 1 - PLANNING: Analyze this task and create a comprehensive todo list. Focus only on planning. Do not execute yet. When your plan is complete, call finalize_plan()."
2. Planning continues until the agent calls `finalize_plan()` (requires at least one todo item)
3. Phase transition: "PHASE 2 - EXECUTION: Work through your plan."
4. Execution continues until auto-completion or `finish_task`

#### reflexion

Post-completion self-critique. After the agent finishes (calls `finish_task` or todo auto-completes), the runner re-opens the state and injects the agent's output back as a critique prompt for additional rounds.

**Requires** `reflection_rounds > 0`.

```yaml
reasoning:
  pattern: reflexion
  reflection_rounds: 1   # 1-3 rounds of self-critique
```

How it works:
1. Agent works normally until completion
2. Runner re-opens the state: "REFLECTION (1/1): Review your work so far. What could be improved?"
3. Agent gets `reflection_rounds` additional turns to self-correct
4. Final output is from the last iteration

Reflexion composes with other patterns. A `todo_driven` agent with `reflection_rounds: 1` first completes its todo list, then gets one critique pass.

### Auto-detection

When `auto_detect: true` (the default) and no explicit `pattern` is set:

| Condition | Detected pattern |
|-----------|-----------------|
| Has `todo` tool + `spec.autonomy` configured | `todo_driven` |
| Has `reflection_rounds > 0` | `reflexion` |
| Everything else | `react` |

Explicit `pattern` setting always overrides auto-detection.

### Validation

The loader validates reasoning config at build time:

- `todo_driven` or `plan_execute` without a `todo` tool raises `RoleLoadError`
- `reflexion` with `reflection_rounds == 0` raises `RoleLoadError`

## Zero-Config Examples

You don't need to set `spec.reasoning` explicitly. Auto-detection picks the right pattern:

### Minimal todo agent (auto-detects `todo_driven`)

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: task-agent
  description: Agent with structured task tracking
spec:
  role: You are a helpful assistant that plans work carefully.
  model:
    provider: openai
    name: gpt-5.4-mini-2026-03-17
  tools:
    - type: think
    - type: todo
  autonomy:
    max_plan_steps: 15
  guardrails:
    max_iterations: 10
    autonomous_token_budget: 50000
```

```bash
initrunner run task-agent.yaml -a -p "Summarize the key differences between REST and GraphQL"
```

### Single-shot with think (auto-detects `react`)

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: reasoner
  description: Agent that thinks before answering
spec:
  role: |
    You are a careful analyst. Always use the think tool to reason
    step by step before giving your answer.
  model:
    provider: openai
    name: gpt-5.4-mini-2026-03-17
  tools:
    - type: think
      critique: true
```

```bash
initrunner run reasoner.yaml -p "Should we migrate from REST to GraphQL?"
```

## Composing Primitives

The tools compose naturally through LLM reasoning. No special wiring needed.

### think + todo (structured reasoning)

The agent uses `think` to reason about each todo item before working on it:

```yaml
tools:
  - type: think
    critique: true
  - type: todo
reasoning:
  pattern: todo_driven
  auto_plan: true
```

### todo + spawn (parallel research)

The agent creates a todo list, spawns background agents for parallelizable items, awaits results, then updates statuses:

```yaml
tools:
  - type: todo
  - type: spawn
    agents:
      - name: researcher
        role_file: ./agents/researcher.yaml
reasoning:
  pattern: todo_driven
  auto_plan: true
```

### todo + reflexion (self-correcting planner)

The agent plans and executes via todo_driven, then gets one round of self-critique:

```yaml
tools:
  - type: todo
  - type: think
    critique: true
reasoning:
  pattern: todo_driven
  auto_plan: true
  reflection_rounds: 1
```

## Run-Scoped Tool Architecture

Reasoning tools carry per-run state (thought chains, todo lists, spawn pools). Standard tools are built once at agent-build time and reused across runs. Run-scoped tools are different: they are built fresh for each run with isolated state, preventing leaks across REPL/daemon sessions.

### How it works

1. Tool author marks a tool as run-scoped in the registration decorator:

```python
@register_tool("todo", TodoToolConfig, run_scoped=True)
def build_todo_toolset(config, ctx, state):
    ...
```

2. `build_toolsets()` automatically skips run-scoped tools during agent construction
3. The runner calls `build_run_scoped_toolsets()` at the start of each run to construct them with fresh state
4. Run-scoped toolsets are passed as `extra_toolsets` to `execute_run()`

### Creating custom run-scoped tools

If you're building a custom tool that needs per-run state:

```python
from initrunner.agent.tools._registry import register_tool, ToolBuildContext
from initrunner.agent.schema.tools import ToolConfigBase
from pydantic_ai.toolsets.function import FunctionToolset

class MyStatefulConfig(ToolConfigBase):
    type: Literal["my_stateful"] = "my_stateful"

@register_tool("my_stateful", MyStatefulConfig, run_scoped=True)
def build_my_toolset(config, ctx):
    state = []  # fresh per-run
    toolset = FunctionToolset()

    @toolset.tool_plain
    def record(value: str) -> str:
        state.append(value)
        return f"Recorded {len(state)} values."

    return toolset
```

## Full Example: Autonomous Research Lead

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: research-lead
  description: Autonomous research lead with parallel workers and self-critique
spec:
  role: |
    You are a research lead. Given a topic:
    1. Break it into research questions (todo list)
    2. Spawn researchers for parallelizable questions
    3. Synthesize findings into a structured report
    4. Self-critique before finalizing
  model:
    provider: openai
    name: gpt-5.4-mini-2026-03-17
  tools:
    - type: think
      critique: true
    - type: todo
      max_items: 15
    - type: spawn
      max_concurrent: 3
      agents:
        - name: web-researcher
          role_file: ./agents/web-researcher.yaml
          description: Searches the web and summarizes findings
        - name: data-analyst
          role_file: ./agents/data-analyst.yaml
          description: Analyzes data and produces charts
    - type: filesystem
      root_path: ./output
      read_only: false
  reasoning:
    pattern: todo_driven
    auto_plan: true
    reflection_rounds: 1
  autonomy:
    max_plan_steps: 20
  guardrails:
    max_iterations: 20
    autonomous_token_budget: 150000
    timeout_seconds: 600
```

```bash
initrunner run research-lead.yaml -a -p "Compare the top 3 vector databases for production RAG systems"
```
