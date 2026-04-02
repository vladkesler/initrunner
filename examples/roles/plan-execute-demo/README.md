# Plan-Execute Demo

Two-phase autonomous agent that strictly separates planning from execution. The agent builds a complete plan first, calls `finalize_plan()` to lock it in, then executes items step by step.

This is the stricter sibling of `todo_driven` -- where `todo_driven` lets the agent interleave planning and execution, `plan_execute` enforces a hard boundary between the two phases.

## Quick start

```bash
# Install
initrunner install vladkesler/plan-execute-demo

# Architecture design
initrunner run plan-execute-demo -a -p "Design a 3-tier web application architecture"

# Migration planning
initrunner run plan-execute-demo -a -p "Plan a database migration from MySQL to PostgreSQL"

# Infrastructure
initrunner run plan-execute-demo -a -p "Break down the steps to set up a Kubernetes cluster"
```

## How it works

1. **Phase 1 (planning)**: The agent receives the prompt prefixed with "PHASE 1 - PLANNING". It uses `batch_add_todos` to create a structured plan with priorities and dependencies. The continuation prompt reminds it to call `finalize_plan()` when done.
2. **Transition**: The agent calls `finalize_plan()`, which validates at least one todo exists and flips the phase.
3. **Phase 2 (execution)**: The continuation prompt switches to "PHASE 2 - EXECUTION". The agent calls `get_next_todo`, works on items, updates statuses.
4. **Completion**: When all items reach terminal status, auto-completion kicks in. The agent can also call `finish_task` directly.

## When to use plan_execute vs todo_driven

| | `plan_execute` | `todo_driven` |
|---|---|---|
| Planning phase | Strict, isolated | Interleaved with execution |
| Phase transition | Explicit (`finalize_plan()`) | Implicit (just start working) |
| Best for | Complex tasks where upfront planning pays off | Simpler tasks, exploration |
| Overhead | +1 tool call for transition | None |

## Configuration

```yaml
reasoning:
  pattern: plan_execute    # strict two-phase
  auto_detect: false       # don't let auto-detection override
```
