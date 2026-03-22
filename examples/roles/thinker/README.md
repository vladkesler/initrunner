# Thinker

Agent that reasons step-by-step with self-critique before acting. Uses the enhanced think tool with accumulated reasoning chains and periodic self-evaluation nudges.

## Quick start

```bash
# Install
initrunner install vladkesler/thinker

# Ask a question that benefits from structured reasoning
initrunner run thinker -p "Should we use a monorepo or polyrepo for our new project?"

# Technical decision-making
initrunner run thinker -p "What are the trade-offs of using event sourcing vs traditional CRUD?"
```

## How it works

The think tool accumulates a numbered reasoning chain visible to the agent across tool calls. With critique enabled, every 5th thought triggers a self-evaluation:

> "You have recorded 5 thoughts. Before proceeding, critically evaluate your reasoning. What assumptions might be wrong? What have you missed?"

This makes the agent question its own reasoning before committing to an answer.

## Example prompts

```
Should we use a monorepo or polyrepo for our new project?
What are the trade-offs of using event sourcing vs traditional CRUD?
Is it worth migrating from REST to GraphQL for our mobile app?
Compare SQLite, PostgreSQL, and DynamoDB for a serverless application
```

## Configuration

Adjust the think tool in `role.yaml`:

```yaml
tools:
  - type: think
    critique: true       # self-critique every 5th thought
    max_thoughts: 20     # ring buffer size
```

Set `critique: false` to disable the self-evaluation nudges.

## Changing the model

Edit `spec.model` in `role.yaml`:

```yaml
model:
  provider: anthropic
  name: claude-sonnet-4-20250514
```
