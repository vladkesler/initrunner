# Slack Daily Digest

A curated daily briefing that learns what your team cares about. Searches for news on your configured topics every weekday morning, posts a clean digest to Slack, and remembers what it already reported so stories never repeat.

## Quick start

```bash
# Install
initrunner install vladkesler/slack-digest

# Set your webhook
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../..."
export OPENAI_API_KEY="your-api-key"

# IMPORTANT: Edit the topic list in role.yaml (see Customization below)

# Start the daemon
initrunner daemon role.yaml
```

The agent runs on a cron schedule (weekdays at 9:00 UTC by default).

## Prerequisites

1. **Slack incoming webhook** -- Create one at [Slack API > Incoming Webhooks](https://api.slack.com/messaging/webhooks). Point it at the channel where you want digests posted.
2. No extra pip dependencies required.

## Customization

### Topics

The most important thing to customize. Open `role.yaml` and find the **Topics to cover** section in the system prompt:

```yaml
spec:
  role: |
    ...
    ## Topics to cover
    ##
    ## >>> EDIT THIS LIST to match your team's interests <<<
    ##
    - AI and large language models
    - Python ecosystem and releases
    - Cloud infrastructure (AWS, GCP, Azure)
    - Cybersecurity threats and advisories
    - Open source project launches
```

Replace these with whatever your team follows. Be specific -- "Kubernetes CVEs" works better than "tech news".

### Schedule

Edit the cron expression in `role.yaml`:

```yaml
triggers:
  - type: cron
    schedule: "0 9 * * 1-5"   # weekdays at 9:00
    timezone: UTC              # change to your timezone (e.g. America/New_York)
```

### Slack channel

The webhook URL determines the channel. Create a new webhook pointed at a different channel to change where digests land.

## Example digest output

```
*Daily Briefing -- Wednesday, March 19*

*AI & LLMs*
- Claude 4.5 Opus released with 1M context -- Anthropic ships largest context window to date (<https://example.com|Anthropic Blog>)
- OpenAI announces GPT-5 API availability -- general access starting next week (<https://example.com|OpenAI>)

*Python*
- Python 3.13.1 released with JIT improvements -- 15% faster on benchmarks (<https://example.com|Python.org>)

*Cybersecurity*
- Critical curl vulnerability CVE-2026-1234 -- update to 8.12.1 immediately (<https://example.com|NVD>)

_Curated by InitRunner -- 4 stories across 3 topics_
```

## What's inside

- **Autonomous execution** -- Runs on a cron trigger with `autonomous: true`, no human in the loop
- **Web search** -- DuckDuckGo search with up to 10 results per query
- **Article reading** -- Fetches full articles to verify details before summarizing
- **Deduplication via memory** -- Remembers reported stories (200 episodes, 500 semantic memories) so tomorrow's digest is always fresh
- **Slack posting** -- Posts directly via incoming webhook using Slack mrkdwn formatting

## Changing the model

Edit `spec.model` in `role.yaml`. Memory uses embeddings that inherit from the model provider -- Anthropic falls back to OpenAI embeddings (`OPENAI_API_KEY` needed).

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-5-20250929
  memory:
    embeddings:
      provider: google
      model: text-embedding-004
```
