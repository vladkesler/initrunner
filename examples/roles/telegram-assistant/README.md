# Telegram Personal Assistant

A personal AI in your pocket that remembers your preferences, researches for you, summarizes articles, and transcribes YouTube videos. Gets smarter the more you use it.

## Quick start

```bash
# Install
initrunner install vladkesler/telegram-assistant

# Set your tokens
export TELEGRAM_BOT_TOKEN="your-token-here"
export OPENAI_API_KEY="your-api-key"

# Start the bot
initrunner run role.yaml --daemon
```

You should see `Telegram bot started polling` in the logs.

## Prerequisites

1. **Create a bot** -- Open Telegram, find @BotFather, send `/newbot`, and follow the prompts. Copy the token. See the [Telegram quickstart](https://initrunner.dev/docs/getting-started/telegram) for details.
2. **Telegram extra** -- `pip install initrunner[telegram]` or `uv sync --extra telegram`.

## Example messages

```
Remember that I'm vegetarian and allergic to nuts
What's the weather in Tokyo right now?
Summarize this article: https://example.com/some-post
tl;dr https://youtube.com/watch?v=dQw4w9WgXcQ
What was that restaurant I mentioned last week?
What do you know about me?
```

## What's inside

- **Web search** -- DuckDuckGo search for factual questions and current events
- **YouTube transcripts** -- Pulls and summarizes video transcripts via the audio tool
- **Link summaries** -- Fetches and condenses shared articles
- **Three memory types** -- Episodic (500 episodes), semantic (1000 memories), procedural (100 procedures) with auto-consolidation after each session
- **Date/time awareness** -- Answers time-sensitive questions accurately
- **Mobile-optimized** -- Short, scannable responses with bullet points

## Access control

By default the bot responds to everyone. Lock it down in `role.yaml`:

```yaml
triggers:
  - type: telegram
    token_env: TELEGRAM_BOT_TOKEN
    allowed_users: ["alice", "bob"]
    allowed_user_ids: [123456789]
```

Prefer `allowed_user_ids` over `allowed_users` -- usernames can change, IDs are permanent. Find your ID via [@userinfobot](https://t.me/userinfobot).

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
