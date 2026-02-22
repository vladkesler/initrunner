# Discord Bot Quickstart

Get a Discord bot agent running in five steps. For the full trigger reference, see [Triggers](../core/triggers.md).

## Prerequisites

- InitRunner installed (`pip install initrunner` or `uv tool install initrunner`)
- An API key for your provider (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.)
- The Discord optional dependency: `uv sync --extra discord` (or `pip install initrunner[discord]`)

## Step 1: Create a Discord Application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application**, give it a name, and click **Create**.
3. Go to the **Bot** tab in the left sidebar.
4. Click **Reset Token** and copy the token — you'll need it in Step 3.

## Step 2: Enable Message Content Intent

Still on the **Bot** tab:

1. Scroll down to **Privileged Gateway Intents**.
2. Enable **Message Content Intent**.
3. Click **Save Changes**.

Without this intent the bot connects but silently receives empty message bodies.

## Step 3: Set Environment Variables

```bash
export DISCORD_BOT_TOKEN="your-token-here"
export OPENAI_API_KEY="your-api-key"   # or your provider's key
```

Or, to persist keys across sessions, add them to `~/.initrunner/.env`:

```dotenv
DISCORD_BOT_TOKEN=your-token-here
OPENAI_API_KEY=your-api-key
```

A `.env` file next to your `role.yaml` also works. Running `initrunner setup` writes the provider key there automatically. Existing environment variables always take precedence over `.env` values.

## Step 4: Invite the Bot to Your Server

1. Go to the **OAuth2** tab in the Developer Portal.
2. Under **OAuth2 URL Generator**, select the `bot` scope.
3. Under **Bot Permissions**, select:
   - **Send Messages**
   - **Read Message History**
4. Copy the generated URL and open it in your browser.
5. Select the server you want to add the bot to and click **Authorize**.

## Step 5: Create a Role and Run

Create a `role.yaml`:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: discord-assistant
  description: A Discord bot that responds to DMs and @mentions
spec:
  role: |
    You are a helpful assistant responding to Discord messages.
    Keep responses concise.
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.1
    max_tokens: 4096
  triggers:
    - type: discord
      token_env: DISCORD_BOT_TOKEN
  guardrails:
    max_tokens_per_run: 50000
    daemon_daily_token_budget: 200000
```

Start the daemon:

```bash
initrunner daemon role.yaml
```

You should see `Discord bot connected` in the logs.

### Quick Alternative

To test without creating a role file:

```bash
initrunner chat --discord
```

Auto-detects your provider, launches an ephemeral bot with minimal tools and persistent memory enabled by default. Use `--tool-profile all` for everything, or add individual tools with `--tools`:

```bash
# Enable every available tool
SLACK_WEBHOOK_URL="https://hooks.slack.com/..." initrunner chat --discord --tool-profile all

# Or add specific extras
initrunner chat --discord --tools git --tools shell

# Restrict to specific users by ID (works in DMs and guild channels)
initrunner chat --discord --allowed-user-ids 111222333444555666

# Disable memory if not needed
initrunner chat --discord --no-memory
```

Run `initrunner chat --list-tools` to see all available tool types.

For production, use the `role.yaml` approach above for access control and budgets. See [Chat & Quick Start](chat.md).

## Testing

- **@mention** — In a server channel, type `@YourBot what time is it?`
- **DM** — Open a direct message with the bot and send any text.
- **Long responses** — Responses over 2000 characters are automatically chunked at newline boundaries.

## Configuration Options

All options go under `spec.triggers[].`:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `token_env` | `str` | `"DISCORD_BOT_TOKEN"` | Environment variable holding the bot token. |
| `channel_ids` | `list[str]` | `[]` | Channel IDs to respond in. Empty = all channels. Does not affect DMs. |
| `allowed_roles` | `list[str]` | `[]` | Server role names required to interact. Empty = allow everyone. DMs are denied when only roles are configured. |
| `allowed_user_ids` | `list[str]` | `[]` | Discord user IDs allowed to interact. Works in both guild channels and DMs. |
| `prompt_template` | `str` | `"{message}"` | Template for the prompt. `{message}` is replaced with the user's text. |

Example with restrictions:

```yaml
triggers:
  - type: discord
    token_env: DISCORD_BOT_TOKEN
    channel_ids: ["1234567890"]
    allowed_roles: ["Bot-User", "Admin"]
    allowed_user_ids: ["111222333444555666"]
    prompt_template: "Discord user asks: {message}"
```

## Security and Public Access

By default the bot responds to **anyone** who can DM it or @mention it in a shared server. This means every member of every server the bot is in can use it. Lock it down before making it available to others:

- **Use `allowed_user_ids`** for the most reliable access control. Unlike `allowed_roles`, user IDs work in DMs. When both `allowed_roles` and `allowed_user_ids` are set, a user ID match grants DM access. To find a user ID: enable Developer Mode (Settings > Advanced), right-click a user > Copy User ID.
- **Use `allowed_roles`** to restrict access to specific server roles. When only roles are configured, DMs are automatically denied (DMs have no role context).
- **Use `channel_ids`** to confine the bot to specific guild channels. `channel_ids` restricts guild channels only — DMs are not affected.
- **Set `daemon_daily_token_budget`** in guardrails to cap API costs. Without a budget, a public bot can run up unlimited charges.
- **Keep the bot token secret.** Anyone with the token can impersonate the bot. Never commit it to version control — use environment variables or a secrets manager.
- **Limit server exposure.** If the bot has access to tools (filesystem, HTTP, shell, etc.), keep it in a private server only. A public server lets strangers invoke those tools through the bot.

## Troubleshooting

### Bot connects but never responds

The **Message Content Intent** is not enabled. Go to the Developer Portal > Bot > Privileged Gateway Intents and enable it (see Step 2).

### `ModuleNotFoundError: No module named 'discord'`

The optional dependency is not installed. Run:

```bash
uv sync --extra discord
# or
pip install initrunner[discord]
```

### `Env var DISCORD_BOT_TOKEN not set`

Export the token before starting the daemon:

```bash
export DISCORD_BOT_TOKEN="your-token-here"
```

### Bot responds in wrong channels

Set `channel_ids` to a list of channel ID strings. To get a channel ID, enable Developer Mode in Discord (Settings > Advanced > Developer Mode), then right-click a channel and select **Copy Channel ID**.

## What's Next

- [Chat & Quick Start](chat.md) — zero-config chat and one-command bot shortcuts
- [Triggers Reference](../core/triggers.md) — full reference for all trigger types
- [Guardrails](../configuration/guardrails.md) — token budgets, timeouts, and request limits
- [Telegram Quickstart](telegram.md) — similar setup for Telegram bots
