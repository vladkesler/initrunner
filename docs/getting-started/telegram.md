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
name: telegram-assistant
description: A Telegram bot that responds to messages via long-polling
model: openai:gpt-5-mini
prompt: |
  You are a helpful assistant responding to Telegram messages.
  Keep responses concise and well-formatted for mobile reading.
triggers:
  - type: telegram
    token_env: TELEGRAM_BOT_TOKEN
guardrails:
  max_tokens_per_run: 50000
  daemon_daily_token_budget: 200000
```

Start the daemon:

```bash
initrunner run role.yaml --daemon
```

You should see `Telegram bot started polling` in the logs.

### Quick Alternative

To try one without writing a role file, run the bundled starter:

```bash
initrunner run telegram --daemon
```

It auto-detects your provider and ships with search, web reading, audio
transcription, and persistent memory.

> **It answers anyone who messages it.** The starter has no allowlist, so add
> `allowed_user_ids` before you share the bot's handle. Each message is one
> agent run, not an autonomous loop.

To change its tools, budgets, or access control, copy it and edit the YAML:

```bash
initrunner examples copy telegram --output ./my-bot
initrunner run ./my-bot/role.yaml --daemon
```

Access control, tools, and budgets all live in that file:

```yaml
triggers:
  - type: telegram
    # By ID (recommended) or username
    allowed_user_ids: [123456789]
    allowed_users: [alice, bob]
```

Run `initrunner run --help` to see the tool types available to ephemeral mode
(`--tools`), which is separate from what a role file can use.

## Testing

- Send a plain text message to your bot in Telegram.
- Long responses are automatically chunked at 4096-character boundaries.
- `/start`, `/help`, and other commands are ignored — only plain text messages are processed.

## Configuration Options

All options go under `triggers[]` in the role file:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `token_env` | `str` | `"TELEGRAM_BOT_TOKEN"` | Environment variable holding the bot token. |
| `allowed_users` | `list[str]` | `[]` | Telegram usernames allowed to interact. Empty = allow everyone. |
| `allowed_user_ids` | `list[int]` | `[]` | Telegram user IDs allowed to interact. Empty = allow everyone. |
| `allow_all` | `bool` | `false` | Explicitly opt in to responding to **anyone** when no allowlist is set. Without it, an unconfigured bot logs a loud startup warning (a future release will reject unconfigured bots by default). |
| `prompt_template` | `str` | `"{message}"` | Template for the prompt. `{message}` is replaced with the user's text. |

Example with restrictions:

```yaml
triggers:
  - type: telegram
    token_env: TELEGRAM_BOT_TOKEN
    allowed_users: ["alice", "bob"]
    allowed_user_ids: [123456789, 987654321]
    prompt_template: "Telegram user asks: {message}"
```

## Security and Public Access

By default the bot responds to **anyone** who messages it, and logs a loud startup warning saying so. Lock it down before making it available to others (a future release will reject unconfigured bots by default; set `allow_all: true` to keep open access and silence the warning):

- **Prefer `allowed_user_ids` over `allowed_users`.** Usernames are mutable — users can change them at any time. User IDs are permanent. Find your ID via [@userinfobot](https://t.me/userinfobot).
- **Use `allowed_users`** to restrict access by Telegram username. When either `allowed_users` or `allowed_user_ids` is non-empty, messages from unmatched users are silently ignored.
- **Union semantics:** access is granted if the user matches **either** `allowed_users` or `allowed_user_ids`. Both fields can be set together.
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

- [Triggers Reference](../core/triggers.md) — full reference for all trigger types
- [Guardrails](../configuration/guardrails.md) — token budgets, timeouts, and request limits
- [Discord Quickstart](discord.md) — similar setup for Discord bots
