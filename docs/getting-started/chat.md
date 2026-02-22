# Chat & Quick Start

Zero-config chat, role-based chat, and one-command bot launching. For the full CLI reference, see [CLI Reference](cli.md).

## Prerequisites

- InitRunner installed (`pip install initrunner` or `uv tool install initrunner`)
- An API key for any supported provider (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.) **or** Ollama running locally
- For bot mode: the platform optional dependency (`pip install initrunner[telegram]` or `pip install initrunner[discord]`)

## Zero-Config Chat

The fastest way to start chatting. InitRunner auto-detects your API provider and launches a REPL.

### Just run `initrunner`

With no arguments in a terminal, InitRunner picks the right action automatically:

| Condition | Behavior |
|-----------|----------|
| TTY + configured (API key present) | Starts ephemeral chat REPL |
| TTY + unconfigured (no API key) | Runs setup wizard |
| Non-TTY (piped/scripted) | Shows help text |

```bash
# Auto-detect provider, start chatting
initrunner
```

### Explicit `chat` subcommand

```bash
# Same as bare `initrunner` but explicit
initrunner chat
```

### Send a prompt then continue interactively

```bash
# Send a question, then stay in the REPL for follow-ups
initrunner chat -p "Explain Python decorators"
```

### Override provider and model

```bash
# Use a specific provider and model
initrunner chat --provider anthropic --model claude-sonnet-4-5-20250929
```

### Persistent memory (enabled by default)

Memory is on by default — the agent remembers facts across sessions:

```bash
# Memory is automatic — just chat
initrunner chat
> Remember that I prefer dark mode
> What are my preferences?   # agent recalls "dark mode" from memory

# Resume a previous session
initrunner chat --resume

# Disable memory for a clean session
initrunner chat --no-memory
```

### Document Q&A without a role file

Ingest documents into the chat session for instant RAG:

```bash
# Chat with your docs
initrunner chat --ingest "./docs/**/*.md"

# Combine with tools
initrunner chat --ingest ./notes/ --tool-profile all
```

The `--ingest` flag runs the ingestion pipeline before the REPL starts and auto-registers the `search_documents` tool.

## Role-Based Chat

Load an existing role file with tools, memory, guardrails, and everything else defined in YAML:

```bash
initrunner chat role.yaml
```

When a role file is provided, the `--provider`, `--model`, `--tool-profile`, and `--tools` flags are ignored — the role file controls everything. The `--resume` flag works with role files too.

Combine with `-p` to send an initial prompt then continue interactively:

```bash
initrunner chat role.yaml -p "Summarize today's news"

# Resume a previous role-based session
initrunner chat role.yaml --resume
```

## One-Command Bot Mode

Launch a Telegram or Discord bot with a single command:

```bash
# Telegram bot
export TELEGRAM_BOT_TOKEN="your-token"
initrunner chat --telegram

# Discord bot
export DISCORD_BOT_TOKEN="your-token"
initrunner chat --discord

# Restrict access by user ID
initrunner chat --telegram --allowed-user-ids 123456789
initrunner chat --discord --allowed-user-ids 111222333444555666
```

### What it creates

Bot mode builds an ephemeral role in memory with:

- Name: `telegram-bot` or `discord-bot`
- Provider and model: auto-detected from environment
- Tools: `minimal` profile (datetime + web_reader) by default
- Daily token budget: 200,000
- Autonomous mode: enabled (responds to messages without confirmation)

### `chat --telegram` vs `daemon role.yaml`

| | `chat --telegram` / `--discord` | `daemon role.yaml` |
|---|---|---|
| **Config** | Auto-generated in memory | Full YAML with all options |
| **Tools** | Tool profile + `--tools` extras | Any tools from the registry |
| **Access control** | `--allowed-users` / `--allowed-user-ids` flags | `allowed_users` / `allowed_roles` / `allowed_user_ids` |
| **Token budget** | 200k daily (hardcoded) | Configurable in guardrails |
| **Memory** | Enabled by default (opt out with `--no-memory`) | Configurable |
| **Use case** | Prototyping, personal use | Production, shared bots |

**Recommendation:** Use `chat --telegram` / `--discord` for quick testing. Switch to a `role.yaml` with `initrunner daemon` for anything shared or long-running.

## CLI Options

Synopsis: `initrunner chat [role.yaml] [OPTIONS]`

| Flag | Description |
|------|-------------|
| `role_file` | Path to `role.yaml` (positional, optional). Omit for auto-detect mode. |
| `--provider TEXT` | Model provider — overrides auto-detection. |
| `--model TEXT` | Model name — overrides auto-detection. |
| `-p, --prompt TEXT` | Send a prompt then enter REPL (or launch bot with this context). |
| `--telegram` | Launch as a Telegram bot daemon. |
| `--discord` | Launch as a Discord bot daemon. |
| `--allowed-users TEXT` | Restrict bot to these usernames (repeatable). Requires `--telegram` or `--discord`. |
| `--allowed-user-ids TEXT` | Restrict bot to these user IDs (repeatable). Requires `--telegram` or `--discord`. |
| `--tool-profile TEXT` | Tool profile: `none`, `minimal` (default), `all`. |
| `--tools TEXT` | Extra tool types to enable (repeatable). See [Extra Tools](#extra-tools). |
| `--memory / --no-memory` | Enable or disable persistent memory. Default: enabled. |
| `--resume` | Resume the previous session (loads history + recalls relevant memories). |
| `--ingest PATH` | Paths or globs to ingest for document Q&A (repeatable). |
| `--list-tools` | List available extra tool types and exit. |
| `--audit-db PATH` | Path to audit database. |
| `--no-audit` | Disable audit logging. |

## Tool Profiles

Tool profiles control which tools are available in auto-detect and bot modes. When a role file is provided, it defines its own tools and the profile is ignored.

| Profile | Tools | Notes |
|---------|-------|-------|
| `none` | *(none)* | Safest — pure text chat, no tool access. |
| `minimal` | `datetime`, `web_reader` | Default. Time awareness and web page reading. |
| `all` | All tools from [Extra Tools](#extra-tools) table | Includes `shell`, `python`, and `slack` — see Security. Requires env vars for `slack`. |

```bash
# Chat with no tools
initrunner chat --tool-profile none

# Chat with every available tool
SLACK_WEBHOOK_URL="https://hooks.slack.com/..." initrunner chat --tool-profile all
```

### Tool search

All profiles automatically include the `search_tools` meta-tool, which lets the agent discover tools that aren't in its always-visible set. This means even `--tool-profile none` isn't completely unarmed — the agent can find and use tools on demand when the conversation requires them.

With `minimal`, the agent always sees datetime and web_reader tools; if the user asks something that needs `python` or `git`, the agent calls `search_tools()` to discover them. With `all`, every tool is always-visible so search has nothing to discover.

For details on how tool search works, see [Tool Search](../core/tool-search.md).

## Extra Tools

Use `--tools` to add individual tools on top of the selected profile, or use `--tool-profile all` to enable everything at once. This is how you enable outbound integrations (like Slack) without writing a full `role.yaml`.

```bash
# Add slack to the default minimal profile
SLACK_WEBHOOK_URL="https://hooks.slack.com/..." initrunner chat --telegram --tools slack

# Add multiple tools
initrunner chat --tools git --tools shell

# Combine with a profile
initrunner chat --tool-profile all --tools slack
```

Duplicates are ignored — `--tool-profile all --tools search` won't add `search` twice.

### Supported extra tools

| Tool | Required env vars | Notes |
|------|-------------------|-------|
| `datetime` | — | Time awareness (included in `minimal`). |
| `web_reader` | — | Fetch and read web pages (included in `minimal`). |
| `search` | — | Web search (included in `all`). |
| `python` | — | Execute Python code (included in `all`). |
| `filesystem` | — | Read-only filesystem access (included in `all`). |
| `slack` | `SLACK_WEBHOOK_URL` | Send messages to a Slack channel. |
| `git` | — | Read-only git operations in current directory. |
| `shell` | — | Execute shell commands. |

Run `initrunner chat --list-tools` to see this list from the CLI.

### Fail-fast behavior

If a tool requires an environment variable that isn't set, the command exits immediately with an actionable error. This applies to both `--tools` and `--tool-profile all`:

```
Error: Tool 'slack' requires SLACK_WEBHOOK_URL.
  Export it or add it to your .env file:
  export SLACK_WEBHOOK_URL=your-value
```

### Role-file mode

When a role file is provided (`initrunner chat role.yaml --tools slack`), the `--tools` flag is ignored with an info message. The role file defines its own tools.

## Provider Auto-Detection

When `--provider` is not specified, InitRunner checks environment variables in this order:

| Priority | Provider | Environment Variable | Default Model |
|----------|----------|---------------------|---------------|
| 1 | anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-5-20250929` |
| 2 | openai | `OPENAI_API_KEY` | `gpt-5-mini` |
| 3 | google | `GOOGLE_API_KEY` | `gemini-2.0-flash` |
| 4 | groq | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| 5 | mistral | `MISTRAL_API_KEY` | `mistral-large-latest` |
| 6 | cohere | `CO_API_KEY` | `command-r-plus` |
| 7 | ollama | *(localhost:11434 reachable)* | First available model or `llama3.2` |

The first key found wins. Ollama is used as a fallback only when no API keys are set and Ollama is running locally.

To override auto-detection:

```bash
# Force a specific provider (uses its default model)
initrunner chat --provider google

# Force both provider and model
initrunner chat --provider openai --model gpt-4o
```

Environment variables can also be set in `~/.initrunner/.env` or a `.env` file in the current directory. Running `initrunner setup` writes the provider key there automatically.

## Persistent Memory

Memory is enabled by default in ephemeral chat mode. The agent gets `remember()`, `recall()`, `learn_procedure()`, `record_episode()`, and `list_memories()` tools automatically.

### How it works

1. The agent's system prompt includes instructions to use `recall()` before answering and `remember()` when the user shares preferences or important facts.
2. Memories are stored at `~/.initrunner/memory/<agent-name>.zvec` (default name: `ephemeral-chat`).
3. On `--resume`, the previous session's message history is loaded **and** relevant long-term memories are automatically recalled and injected into the system prompt.

### Disable memory

```bash
initrunner chat --no-memory
```

No memory tools are registered, no files are written to `~/.initrunner/memory/`.

### Resume a session

```bash
initrunner chat --resume
```

This loads the most recent session (up to `max_resume_messages` messages) and performs an auto-recall: it searches long-term memory for context relevant to the resumed conversation and injects matching memories into the system prompt.

## Document Q&A (`--ingest`)

Ingest files directly from the command line for instant RAG:

```bash
initrunner chat --ingest "./docs/**/*.md"
initrunner chat --ingest ./notes/ --ingest ./data/*.csv
```

The ingestion pipeline runs before the REPL starts:
- Files are extracted, chunked, embedded, and stored in a local vector database.
- A `search_documents` tool is auto-registered on the agent.
- If the embedding model has changed since a previous ingestion, the store is automatically wiped and re-ingested (no interactive prompt in ephemeral mode).

Paths are resolved relative to the current working directory.

## Chat Configuration File

Create `~/.initrunner/chat.yaml` to set persistent defaults for ephemeral chat:

```yaml
# ~/.initrunner/chat.yaml
provider: anthropic            # default provider (overridden by --provider)
model: claude-sonnet-4-5-20250929  # default model (overridden by --model)
tool_profile: all              # default tool profile (overridden by --tool-profile)
tools: [git, shell]            # extra tools always enabled
memory: true                   # enable persistent memory (default: true)
ingest:                        # auto-ingest these paths every session
  - "./my-docs/**/*.md"
personality: |                 # custom system prompt personality
  You are a friendly coding assistant.
name: my-assistant             # agent name (affects memory store path)
```

### Precedence

CLI flags always win over `chat.yaml` values, which win over built-in defaults:

```
CLI flags  >  chat.yaml  >  built-in defaults
```

### When chat.yaml is ignored

`chat.yaml` is **not** applied when a role file is provided:

```bash
initrunner chat role.yaml   # chat.yaml ignored — role file controls everything
initrunner chat              # chat.yaml applied
```

### Ingest path resolution

Relative paths in `chat.yaml`'s `ingest` list are resolved from the config file directory (`~/.initrunner/`), not the current working directory. CLI `--ingest` paths are resolved from the current directory.

## Security

- **Tool profiles control agent capabilities.** The `none` profile is safest for untrusted environments. The `minimal` default gives time and web reading. The `all` profile enables every tool including `python`, `shell`, and `slack`.
- **`all` profile includes `python` and `shell` = full host access.** Both tools can execute arbitrary code on the host. Never use `all` in public-facing bots without access control.
- **`--tools shell` grants shell access.** Like `python`, the `shell` tool allows arbitrary command execution. Only use it in trusted, local contexts.
- **`--tools slack` sends messages to a real channel.** The Slack webhook URL is a secret — treat it like a token. Anyone with the URL can post to the channel.
- **Bot tokens are secrets.** Store them in environment variables or `.env` files. Never commit tokens to version control. Anyone with the token can impersonate the bot.
- **Ephemeral bots respond to everyone by default.** Use `--allowed-users` or `--allowed-user-ids` to restrict access. Without these flags, every user who can message the bot can use it — and invoke its tools.
- **Daily token budget is a cost firewall.** Bot mode defaults to 200,000 tokens/day. For production, tune `daemon_daily_token_budget` in your role's `spec.guardrails` to match expected usage and budget.
- **Use `role.yaml` for production bots.** The `chat` shortcuts are designed for prototyping and personal use. Production bots should use a role file with explicit access control, token budgets, and tool configuration.

## Troubleshooting

### No API key found

```
Error: No API key found. Run initrunner setup or set an API key environment variable.
```

No provider was detected. Either export an API key or start Ollama locally:

```bash
export ANTHROPIC_API_KEY="sk-..."
# or
ollama serve
```

### Unknown tool profile

```
Error: Unknown tool profile 'foo'. Use: none, minimal, all
```

The `--tool-profile` value must be one of `none`, `minimal`, or `all`.

### Unknown tool type

```
Error: Unknown tool type 'foo'.
  Supported: datetime, filesystem, git, python, search, shell, slack, web_reader
```

The `--tools` value must be one of the supported extra tool types. Run `initrunner chat --list-tools` to see the full list.

### Missing required environment variable for tool

```
Error: Tool 'slack' requires SLACK_WEBHOOK_URL.
  Export it or add it to your .env file:
  export SLACK_WEBHOOK_URL=your-value
```

Some tools require environment variables. Set the variable before running the command.

### --allowed-users/--allowed-user-ids requires --telegram or --discord

```
Error: --allowed-users/--allowed-user-ids requires --telegram or --discord.
```

The `--allowed-users` and `--allowed-user-ids` flags only apply to bot mode. Add `--telegram` or `--discord` to use them.

### --telegram and --discord are mutually exclusive

```
Error: --telegram and --discord are mutually exclusive.
```

You can only launch one bot platform at a time. To run both, use two separate role files with `initrunner daemon`.

### TELEGRAM_BOT_TOKEN / DISCORD_BOT_TOKEN not set

```
Error: TELEGRAM_BOT_TOKEN not set. Export it or add it to your .env file:
  export TELEGRAM_BOT_TOKEN=your-bot-token
```

Export the token or add it to `~/.initrunner/.env`:

```bash
export TELEGRAM_BOT_TOKEN="your-token-here"
```

### Module not found (telegram / discord)

```
Error: python-telegram-bot is not installed.
  Install it: pip install initrunner[telegram]
```

Install the platform's optional dependency:

```bash
# For Telegram
pip install initrunner[telegram]
# or
uv sync --extra telegram

# For Discord
pip install initrunner[discord]
# or
uv sync --extra discord
```

### Wrong provider auto-detected

Auto-detection uses the priority order listed above. If you have multiple API keys set and the wrong provider is picked, override explicitly:

```bash
initrunner chat --provider anthropic
```

## What's Next

- [CLI Reference](cli.md) — full command and flag reference
- [Discord Quickstart](discord.md) — full Discord bot setup with role file and access control
- [Telegram Quickstart](telegram.md) — full Telegram bot setup with role file and access control
- [Guardrails](../configuration/guardrails.md) — token budgets, timeouts, and request limits
- [Triggers Reference](../core/triggers.md) — cron, file watcher, webhook, and messaging triggers
- [Provider Configuration](../configuration/providers.md) — detailed provider setup and options
