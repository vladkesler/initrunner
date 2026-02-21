# Telegram Bot Quickstart

Get a Telegram bot agent running in three steps. For the full trigger reference, see [Triggers](../core/triggers.md).

## Prerequisites

- InitRunner installed (`pip install initrunner` or `uv tool install initrunner`)
- An API key for your provider (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.)
- The Telegram optional dependency: `uv sync --extra telegram` (or `pip install initrunner[telegram]`)

## Step 1: Create a Bot with BotFather

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot` and follow the prompts to choose a name and username.
3. BotFather replies with a token — copy it. You'll need it in Step 2.

## Step 2: Set Environment Variables

```bash
export TELEGRAM_BOT_TOKEN="your-token-here"
export OPENAI_API_KEY="your-api-key"   # or your provider's key
```

Or, to persist keys across sessions, add them to `~/.initrunner/.env`:

```dotenv
TELEGRAM_BOT_TOKEN=your-token-here
OPENAI_API_KEY=your-api-key
```

A `.env` file next to your `role.yaml` also works. Running `initrunner setup` writes the provider key there automatically. Existing environment variables always take precedence over `.env` values.

## Step 3: Create a Role and Run

Create a `role.yaml`:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: telegram-assistant
  description: A Telegram bot that responds to messages via long-polling
spec:
  role: |
    You are a helpful assistant responding to Telegram messages.
    Keep responses concise and well-formatted for mobile reading.
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.1
    max_tokens: 4096
  triggers:
    - type: telegram
      token_env: TELEGRAM_BOT_TOKEN
  guardrails:
    max_tokens_per_run: 50000
    daemon_daily_token_budget: 200000
```

Start the daemon:

```bash
initrunner daemon role.yaml
```

You should see `Telegram bot started polling` in the logs.

### Quick Alternative

To test without creating a role file:

```bash
initrunner chat --telegram
```

Auto-detects your provider, launches an ephemeral bot with minimal tools. Use `--tool-profile all` for everything, or add individual tools with `--tools`:

```bash
# Enable every available tool
SLACK_WEBHOOK_URL="https://hooks.slack.com/..." initrunner chat --telegram --tool-profile all

# Or add specific extras
initrunner chat --telegram --tools git --tools shell
```

Run `initrunner chat --list-tools` to see all available tool types.

For production, use the `role.yaml` approach above for access control and budgets. See [Chat & Quick Start](chat.md).

## Testing

- Send a plain text message to your bot in Telegram.
- Long responses are automatically chunked at 4096-character boundaries.
- `/start`, `/help`, and other commands are ignored — only plain text messages are processed.

## Configuration Options

All options go under `spec.triggers[].`:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `token_env` | `str` | `"TELEGRAM_BOT_TOKEN"` | Environment variable holding the bot token. |
| `allowed_users` | `list[str]` | `[]` | Telegram usernames allowed to interact. Empty = allow everyone. |
| `prompt_template` | `str` | `"{message}"` | Template for the prompt. `{message}` is replaced with the user's text. |

Example with restrictions:

```yaml
triggers:
  - type: telegram
    token_env: TELEGRAM_BOT_TOKEN
    allowed_users: ["alice", "bob"]
    prompt_template: "Telegram user asks: {message}"
```

## Security and Public Access

By default the bot responds to **anyone** who messages it. Lock it down before making it available to others:

- **Use `allowed_users`** to restrict access to specific Telegram usernames. When the list is non-empty, messages from all other users are silently ignored.
- **Set `daemon_daily_token_budget`** in guardrails to cap API costs. Without a budget, a public bot can run up unlimited charges.
- **Keep the bot token secret.** Anyone with the token can impersonate the bot. Never commit it to version control — use environment variables or a secrets manager.
- If the bot has access to tools (filesystem, HTTP, shell, etc.), **restrict to known users only**. An unrestricted bot lets strangers invoke those tools through the bot.

## Troubleshooting

### `ModuleNotFoundError: No module named 'telegram'`

The optional dependency is not installed. Run:

```bash
uv sync --extra telegram
# or
pip install initrunner[telegram]
```

### `Env var TELEGRAM_BOT_TOKEN not set`

Export the token before starting the daemon:

```bash
export TELEGRAM_BOT_TOKEN="your-token-here"
```

### Bot ignores messages

Only plain text messages are processed. `/start`, `/help`, and other slash commands are filtered out. Make sure you're sending a regular text message.

## What's Next

- [Chat & Quick Start](chat.md) — zero-config chat and one-command bot shortcuts
- [Triggers Reference](../core/triggers.md) — full reference for all trigger types
- [Guardrails](../configuration/guardrails.md) — token budgets, timeouts, and request limits
- [Discord Quickstart](discord.md) — similar setup for Discord bots
