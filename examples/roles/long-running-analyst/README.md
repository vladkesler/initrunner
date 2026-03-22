# Long-Running Analyst

Autonomous research analyst that methodically gathers information from multiple sources, synthesizes findings, and produces structured reports. Uses history compaction to keep context manageable during long investigations.

## Quick start

```bash
# Install
initrunner install vladkesler/long-running-analyst

# Run a research task
initrunner run long-running-analyst -a -p "Research the current state of WebAssembly adoption"

# Multi-source investigation
initrunner run long-running-analyst -a -p "Compare the top 3 cloud providers on serverless pricing and DX"
```

## How it works

1. Creates a todo list with one item per source or research angle
2. Fetches data from each source via HTTP
3. Updates todo items with key findings as notes
4. When all sources are processed, writes the final report to `./reports/`
5. Calls `finish_task` with an executive summary

History compaction kicks in after 15 messages, summarizing older context with a cheap model to keep the conversation window manageable during long runs.

## Example prompts

```
Research the current state of WebAssembly adoption
Compare the top 3 cloud providers on serverless pricing and DX
Investigate recent trends in developer productivity tools
Summarize the key papers on retrieval-augmented generation from 2025
```

## Configuration

Key settings in `role.yaml`:

```yaml
autonomy:
  compaction:
    enabled: true
    threshold: 15       # compact after this many messages
    tail_messages: 4    # keep this many recent messages verbatim
    model_override: "openai:gpt-4o-mini"  # cheap model for summaries
```

## Changing the model

Edit `spec.model` in `role.yaml`:

```yaml
model:
  provider: anthropic
  name: claude-sonnet-4-20250514
```
