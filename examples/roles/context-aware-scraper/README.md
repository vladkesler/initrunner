# Context-Aware Scraper

Autonomous web scraper that fetches large pages without crashing on context window limits. Demonstrates the **context budget guard** -- set `context_window` on the model and the system handles the rest.

## Quick start

```bash
# Scrape and summarize a page
initrunner run context-aware-scraper -a \
  -p "Scrape https://news.ycombinator.com and summarize the top stories"

# Multiple URLs
initrunner run context-aware-scraper -a \
  -p "Scrape these pages and compare them: https://example.com https://example.org"

# Daemon mode (weekly Monday 9am scrape)
initrunner run context-aware-scraper --daemon
```

## What happens under the hood

Web pages often produce tool results that exceed the model's context window. Without protection, this crashes the agent. The context budget guard prevents this:

1. Before every model call, the guard estimates the token count of the message history
2. If under budget (75% of `context_window`), nothing happens
3. If over budget:
   - **Stage 1**: Oversized tool results and text parts are truncated (with `[truncated]` marker)
   - **Stage 2**: If still over, oldest message pairs are dropped and replaced with a synthetic summary

The guard logs a WARNING when it activates, so you can see it working:

```
[agent.history_summarizer] History budget guard: truncated oversized parts
    (45000 -> 12000 estimated tokens, budget 96000)
```

## Example session

```
$ initrunner run context-aware-scraper -a \
    -p "Scrape https://news.ycombinator.com and summarize the top 5 stories"

Autonomous mode -- agent: context-aware-scraper
  Max iterations: 12
  Token budget: 80,000

  tool web_read: ok (1.2s)
[agent.history_summarizer] History budget guard: truncated oversized parts ...
  tool add_todo: ok
  ...

Agent (iteration 1/12)
  Created todo list, fetched HN front page, extracted top 5 stories.
  ...
```

## Configuration

The key setting is `context_window` on `spec.model`:

```yaml
spec:
  model:
    provider: openai
    name: gpt-5-mini
    context_window: 128000  # your model's context window in tokens
```

If you omit `context_window`, the guard uses provider-level defaults:

| Provider | Default |
|---|---|
| anthropic | 200,000 |
| openai | 128,000 |
| google | 1,000,000 |
| groq | 128,000 |
| bedrock | 200,000 |
| unknown | 32,000 (with warning) |

### Combining with LLM compaction

The budget guard and LLM compaction are complementary:

- **Budget guard** (always on): fast, no LLM calls, handles oversized recent parts
- **LLM compaction** (opt-in): produces quality summaries of older messages between iterations

For long-running agents, enable both:

```yaml
autonomy:
  compaction:
    enabled: true
    threshold: 15
    tail_messages: 4
```

## Changing the model

```yaml
model:
  provider: anthropic
  name: claude-sonnet-4-20250514
  context_window: 200000  # Anthropic models have 200K context
```
