# Self-Correcting Writer

Technical writer that produces content, then self-critiques and improves it via the reflexion reasoning pattern. After completing the initial draft, the agent gets one round of reflection to identify and fix gaps, weak arguments, and structural issues.

## Quick start

```bash
# Install
initrunner install vladkesler/self-correcting-writer

# Write a technical guide
initrunner run self-correcting-writer -a -p "Write a technical blog post about database indexing strategies"

# Write a proposal
initrunner run self-correcting-writer -a -p "Write a project proposal for migrating to Kubernetes"
```

## How it works

1. Creates a todo list for the major sections of the document
2. Writes each section, updating todo items as it completes them
3. Calls `finish_task` when the draft is done
4. The reflexion pattern re-opens the state and prompts: "Review your work. What could be improved?"
5. The agent identifies gaps, strengthens arguments, adds examples, and fixes structural issues
6. Final output is the improved version

## Example prompts

```
Write a technical blog post about database indexing strategies
Write a project proposal for migrating to Kubernetes
Write a concise guide to container networking for developers
Draft an RFC for adding rate limiting to our API gateway
Write onboarding documentation for new backend engineers
```

## Configuration

The reflexion config in `role.yaml`:

```yaml
reasoning:
  pattern: reflexion
  reflection_rounds: 1    # one self-critique round (max 3)
```

Increase `reflection_rounds` to 2 or 3 for more thorough self-review (at the cost of more tokens).

## Changing the model

Edit `spec.model` in `role.yaml`:

```yaml
model:
  provider: anthropic
  name: claude-sonnet-4-20250514
```
