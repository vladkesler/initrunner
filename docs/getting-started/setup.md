# Setup Wizard

The `initrunner setup` command is a guided, intent-driven wizard that configures your model provider, API key, and first agent role in one step. It detects existing configuration, installs missing SDKs, validates API keys, and creates a ready-to-run `role.yaml` plus a `~/.initrunner/chat.yaml` for `initrunner chat`.

> **Prefer a browser?** Run `initrunner dashboard` to configure providers, add API keys, and create agents from the web UI. The dashboard's System page provides full provider management, and the launchpad offers inline key setup for first-time users.

## Quick Start

```bash
# Interactive setup (prompts for intent, provider, key, tools)
initrunner setup

# Non-interactive with all options specified
initrunner setup --provider openai --model gpt-4o --intent chatbot --name my-agent --skip-test -y

# RAG agent with knowledge base
initrunner setup --intent knowledge --provider openai --skip-test -y

# Telegram bot
initrunner setup --intent telegram-bot --provider anthropic --skip-test -y

# Browse and copy a bundled example
initrunner setup --intent from-example -y

# Local Ollama setup (no API key needed)
initrunner setup --provider ollama --intent chatbot -y

# Skip the connectivity test
initrunner setup --skip-test
```

## Options Reference

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--provider` | `str` | *(interactive)* | Provider name. Skips the interactive selection prompt. |
| `--name` | `str` | `my-agent` | Agent name used in the generated role YAML. |
| `--intent` | `str` | *(interactive)* | What to build: `chatbot`, `knowledge`, `memory`, `telegram-bot`, `discord-bot`, `api-agent`, `daemon`, or `from-example`. |
| `--model` | `str` | *(interactive)* | Model name. Skips the interactive model selection prompt. |
| `--skip-test` | `bool` | `false` | Skip the connectivity test after setup. |
| `--output` | `Path` | `role.yaml` | Output path for the generated role file. |
| `-y, --accept-risks` | `bool` | `false` | Accept security disclaimer without prompting. |
| `--skip-chat-yaml` | `bool` | `false` | Skip `chat.yaml` generation. |

## Supported Providers

| Provider | Env Var | Install Extra | Default Model |
|----------|---------|---------------|---------------|
| `openai` | `OPENAI_API_KEY` | *(included in core)* | `gpt-5-mini` |
| `anthropic` | `ANTHROPIC_API_KEY` | `initrunner[anthropic]` | `claude-sonnet-4-5-20250929` |
| `google` | `GOOGLE_API_KEY` | `initrunner[google]` | `gemini-2.0-flash` |
| `groq` | `GROQ_API_KEY` | `initrunner[groq]` | `llama-3.3-70b-versatile` |
| `mistral` | `MISTRAL_API_KEY` | `initrunner[mistral]` | `mistral-large-latest` |
| `cohere` | `CO_API_KEY` | `initrunner[all-models]` | `command-r-plus` |
| `bedrock` | `AWS_ACCESS_KEY_ID` | `initrunner[all-models]` | `us.anthropic.claude-sonnet-4-20250514-v1:0` |
| `xai` | `XAI_API_KEY` | *(uses openai SDK)* | `grok-3` |
| `ollama` | *(none)* | *(included in core)* | `llama3.2` |

## How It Works

### 1. Already-Configured Detection

The wizard checks whether any known provider API key is already set, looking in two places:

1. **Environment variables** -- checks each provider's env var (e.g. `OPENAI_API_KEY`).
2. **Global `.env` file** -- reads `~/.initrunner/.env` via `dotenv_values()`.

If a key is found, the wizard reports which variable was detected and uses that provider as the default.

### 2. Intent Selection

The first interactive question is "What do you want to build?":

| # | Intent | Description |
|---|--------|-------------|
| 1 | `chatbot` | Conversational AI assistant |
| 2 | `knowledge` | Answer questions from your documents (RAG) |
| 3 | `memory` | Assistant that remembers across conversations |
| 4 | `telegram-bot` | Telegram bot powered by AI |
| 5 | `discord-bot` | Discord bot powered by AI |
| 6 | `api-agent` | Agent with REST API tool access |
| 7 | `daemon` | Runs on a schedule or watches for changes |
| 8 | `from-example` | Browse and copy a bundled example |

The intent determines which subsequent steps are shown, which tools are pre-selected, and what role YAML template is generated.

### 3. Provider Selection

When `--provider` is not passed, an interactive prompt lists all 9 supported providers. When `--provider` is passed, the value is validated against the supported list. Unknown providers cause an immediate error.

### 4. SDK Check + Auto-Install

For **Ollama**, the wizard checks that the server is running and queries for available models.

For **Bedrock**, the wizard checks for `boto3` and provides guidance on AWS CLI configuration.

For all other providers, the wizard checks whether the provider SDK is importable and offers to install it automatically.

### 5. API Key / Credentials Entry

Skipped for Ollama (no API key required). For Bedrock, prompts for AWS region. For other providers:

1. Checks for an existing key in the environment, then in `~/.initrunner/.env`.
2. If found, asks whether to keep it. If not found, prompts for entry (masked input).
3. For OpenAI and Anthropic, validates the key with a lightweight API call.
4. Saves the key to `~/.initrunner/.env` with `0600` permissions.

### 6. Model Selection

After the API key is configured, the wizard prompts for a model from a curated list.

### 7. Embedding Config (Conditional)

When `intent=knowledge` or `intent=memory` **and** the provider doesn't offer an embeddings API (Anthropic, Groq, Cohere, Bedrock, xAI, Ollama), the wizard warns the user and optionally prompts for an `OPENAI_API_KEY` for embeddings.

### 8. Tool Selection + Configure

A numbered tool menu is shown with intent-specific defaults pre-marked with `*`. Users pick tools by comma-separated numbers or press Enter for defaults. After selection, per-tool config prompts are shown (e.g., `filesystem` asks for `root_path` and `read_only`).

### 9. Intent-Specific Config

- **knowledge**: Prompts for document sources glob (default: `./docs/**/*.md`)
- **telegram-bot**: Prompts for `TELEGRAM_BOT_TOKEN`
- **discord-bot**: Prompts for `DISCORD_BOT_TOKEN`
- **daemon**: Prompts for trigger type (file_watch or cron) and schedule/paths

### 10. Role + Chat YAML Generation

Generates `role.yaml` at the `--output` path and `~/.initrunner/chat.yaml` for `initrunner chat`. Use `--skip-chat-yaml` to skip chat.yaml generation.

### 11. Post-Generation Actions

- **knowledge**: Offers to run `initrunner ingest` immediately
- **All intents**: Connectivity test (skippable with `--skip-test`)

### 12. Summary + Next Steps

A summary panel shows the configured intent, provider, model, and file paths. Next-step commands are tailored to the chosen intent.

## "from-example" Flow

When selecting intent 8 (`from-example`), the wizard enters a separate flow:

1. Displays a numbered table of bundled examples (roles, compose files, skills)
2. User selects an example by number or name
3. Example files are copied to the current directory
4. **No provider/key/model/role-generation steps** -- the example includes everything
5. Summary shows copied files and next steps (validate, run)

## Intents

| Intent | Template Key | Description |
|--------|-------------|-------------|
| `chatbot` | `basic` | Minimal assistant with guardrails. Pre-selects datetime + web_reader tools. |
| `knowledge` | `rag` | Knowledge assistant with `ingest` config and `search_documents` tool. Prompts for document sources. |
| `memory` | `memory` | Assistant with `memory` config. Auto-registers `remember()`, `recall()`, and `list_memories()` tools. |
| `telegram-bot` | `telegram` | Telegram bot with telegram trigger. Prompts for bot token. |
| `discord-bot` | `discord` | Discord bot with discord trigger. Prompts for bot token. |
| `api-agent` | `api` | Agent with declarative REST API tools. Pre-selects http + datetime tools. |
| `daemon` | `daemon` | Event-driven agent with triggers. Prompts for trigger type and schedule. |
| `from-example` | — | Browse and copy bundled examples. Separate flow. |

All generated roles include guardrails (`max_tokens_per_run`, `max_tool_calls`, `timeout_seconds`, `max_request_limit`) and use the default model for the selected provider.

## Non-Interactive Usage

For CI, automation, or scripting, pass all options as flags to skip all prompts:

```bash
# Fully non-interactive OpenAI chatbot
export OPENAI_API_KEY="sk-..."
initrunner setup --provider openai --model gpt-4o --intent chatbot --name my-agent --skip-test -y

# Knowledge agent with Ollama
initrunner setup --provider ollama --model llama3.2 --intent knowledge --skip-test -y

# Skip chat.yaml generation
initrunner setup --provider openai --intent chatbot --skip-test --skip-chat-yaml -y
```

The wizard still requires the API key to be available either in the environment or in `~/.initrunner/.env`. If no key is found and no TTY is available, the prompt will fail.

## Configuration Files

### Global `.env`

API keys are stored in `~/.initrunner/.env`:

```
OPENAI_API_KEY=sk-...
```

The file is created with `0600` permissions (owner read/write only). The path is determined by:

1. `INITRUNNER_HOME` environment variable (if set).
2. `XDG_DATA_HOME/initrunner` (if `XDG_DATA_HOME` is set).
3. `~/.initrunner` (default fallback).

### Chat Config

`~/.initrunner/chat.yaml` is generated during setup:

```yaml
provider: openai
model: gpt-5-mini
tool_profile: minimal
memory: true
name: ephemeral-chat
```

This file is loaded by `initrunner chat` to pre-configure the ephemeral chat session. See `cli/chat_config.py` for the full schema.

### Generated Role

The generated `role.yaml` (or custom `--output` path) is a standard InitRunner role definition. See `initrunner validate <path>` to check it, or edit it directly to add tools, triggers, or ingestion config.

## Troubleshooting

### Unknown provider

```
Error: Unknown provider 'foo'. Choose from: openai, anthropic, google, groq, mistral, cohere, bedrock, xai, ollama
```

### Unknown intent

```
Error: Unknown intent 'foo'. Choose from: chatbot, knowledge, memory, telegram-bot, discord-bot, api-agent, daemon, from-example
```

### SDK installation failed

```
Warning: Could not install initrunner[anthropic]: ...
Install manually: uv pip install initrunner[anthropic]
```

### Embedding warning

```
Warning: anthropic does not provide an embeddings API.
RAG and memory features require OPENAI_API_KEY for embeddings.
```

This appears when using a provider without embeddings support with the `knowledge` or `memory` intent. Set `OPENAI_API_KEY` for embeddings, or configure a custom embedding provider in your role.yaml.

### API key validation failed

```
Warning: API key validation failed.
```

Re-enter the key when prompted, or continue with the current key and troubleshoot later.

### Test run failed

```
Warning: Test run failed: ...
Setup is still complete -- check your configuration and try again.
```

The connectivity test failed but setup is still considered complete. Run `initrunner run role.yaml -p "hello"` manually to debug.
