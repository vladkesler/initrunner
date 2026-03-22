# Reasoning Planner

Autonomous planner that breaks tasks into structured todo lists, reasons through each item with self-critique, and reviews its own output before finalizing.

Showcases three reasoning primitives working together:
- **Think** (critique mode) -- accumulated reasoning chain with self-critique every 5th thought
- **Todo** (todo_driven pattern) -- priority-aware task list with dependency resolution
- **Reflexion** -- post-completion self-critique round

## Quick start

```bash
# Install
initrunner install vladkesler/reasoning-planner

# Run autonomously
initrunner run reasoning-planner -a -p "Compare React, Vue, and Svelte for a new dashboard project"

# Architecture planning
initrunner run reasoning-planner -a -p "Plan the architecture for a real-time chat application"

# Migration planning
initrunner run reasoning-planner -a -p "Break down the steps to migrate from REST to GraphQL"
```

## How it works

1. The `todo_driven` reasoning pattern prefixes the first turn with instructions to create a structured todo list
2. The agent uses `batch_add_todos` to create prioritized items with dependencies
3. On each iteration, the agent calls `get_next_todo` to find the highest-priority actionable item
4. The `think` tool (with critique) accumulates reasoning -- every 5th thought triggers a self-evaluation nudge
5. When all items reach terminal status, the todo list auto-completes
6. The `reflexion` pattern then re-opens the state for one round of self-critique
7. The agent reviews its work, makes corrections, and finalizes

## Example prompts

```
Compare React, Vue, and Svelte for a new dashboard project
Plan the architecture for a real-time chat application
Break down the steps to migrate from REST to GraphQL
Design a CI/CD pipeline for a microservices project
Evaluate the trade-offs of using a monorepo vs polyrepo
Plan a database schema for a multi-tenant SaaS application
```

## Configuration

The reasoning config can be adjusted in `role.yaml`:

```yaml
reasoning:
  pattern: todo_driven    # plan-first execution
  auto_plan: true         # prepend "create a todo list" to first turn
  reflection_rounds: 1    # one self-critique round after completion
```

Set `reflection_rounds: 0` to skip the self-critique phase. Set `pattern: plan_execute` for a stricter two-phase approach where planning and execution are separated.

## Changing the model

Edit `spec.model` in `role.yaml`:

```yaml
model:
  provider: anthropic
  name: claude-sonnet-4-20250514
```
