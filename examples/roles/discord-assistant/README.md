# Discord Community Assistant

A Discord bot that searches the web, summarizes YouTube videos, reads shared links, and builds a living knowledge base from your server conversations. Remembers context across sessions.

## Quick start

```bash
# Install
initrunner install vladkesler/discord-assistant

# Set your tokens
export DISCORD_BOT_TOKEN="your-token-here"
export OPENAI_API_KEY="your-api-key"

# Start the bot
initrunner daemon role.yaml
```

You should see `Discord bot connected` in the logs.

## Prerequisites

1. **Discord bot** -- Create one at the [Developer Portal](https://discord.com/developers/applications). See the [Discord quickstart](https://initrunner.dev/docs/getting-started/discord) for step-by-step instructions.
2. **Message Content Intent** -- Enable it under Bot > Privileged Gateway Intents. Without it the bot connects but receives empty messages.
3. **Invite the bot** -- OAuth2 > URL Generator > select `bot` scope > Send Messages + Read Message History.
4. **Discord extra** -- `pip install initrunner[discord]` or `uv sync --extra discord`.

## Example messages

```
tl;dr https://youtube.com/watch?v=dQw4w9WgXcQ
What is the difference between gRPC and REST?
Summarize this article: https://example.com/some-post
Remember that our standup is at 10am ET
What did I ask you to remember?
```

## What's inside

- **Web search** -- DuckDuckGo search for factual questions and current events
- **YouTube transcripts** -- Pulls and summarizes video transcripts via the audio tool
- **Link summaries** -- Fetches and condenses articles shared in chat
- **Three memory types** -- Episodic (1000 episodes), semantic (2000 memories), procedural (200 procedures) with auto-consolidation after each session
- **Date/time awareness** -- Answers time-sensitive questions accurately

## Access control

By default the bot responds to everyone. Lock it down in `role.yaml`:

```yaml
triggers:
  - type: discord
    token_env: DISCORD_BOT_TOKEN
    channel_ids: ["1234567890"]       # restrict to specific channels
    allowed_roles: ["Bot-User"]       # restrict to specific server roles
    allowed_user_ids: ["111222333"]   # restrict to specific users (works in DMs)
```

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
