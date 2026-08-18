# Setup Wizard

`initrunner setup` configures a model provider, API key, and `~/.initrunner/run.yaml` in three steps. It does not generate a role file. After keys work, a TTY offers Chat, a starter, or `initrunner new`.

> **You don't need to run `setup` first.** If you skip it and run an agent with `initrunner run path/to/role.yaml`, the CLI prompts for the missing API key in an interactive terminal and saves it to `~/.initrunner/.env`. Use `setup` when you want guided provider and model selection.

> **Prefer a browser?** `initrunner dashboard` configures providers and keys in the web UI. That command is separate from setup.

## Quick Start

```bash
# Interactive: provider, key, model
initrunner setup

# Non-interactive
initrunner setup --provider openai --model gpt-5-mini --skip-test -y

# Local Ollama (no API key)
initrunner setup --provider ollama --skip-test -y

# Skip the connectivity check
initrunner setup --skip-test
```

`-y` / `--accept-risks` skips the security notice **and** the post-setup jobs menu. Scripted or non-TTY runs print a next-steps panel instead of prompting.

## Options Reference

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--provider` | `str` | *(interactive)* | Provider name. Skips the interactive selection prompt. |
| `--name` | `str` | `my-agent` | Name stored in `run.yaml` for ephemeral chat. |
| `--model` | `str` | *(interactive)* | Model name (e.g. `gpt-5-mini`, `claude-sonnet-4-6`). |
| `--skip-test` | `bool` | `false` | Skip the connectivity check after setup. |
| `-y, --accept-risks` | `bool` | `false` | Accept the security notice and skip the jobs menu. |
| `--skip-run-yaml` | `bool` | `false` | Skip `run.yaml` generation. |

## Supported Providers

| Provider | Env Var | Install Extra | Default Model |
|----------|---------|---------------|---------------|
| `openai` | `OPENAI_API_KEY` | *(included in core)* | `gpt-5.4` |
| `anthropic` | `ANTHROPIC_API_KEY` | `initrunner[anthropic]` | `claude-sonnet-4-6` |
| `google` | `GOOGLE_API_KEY` | `initrunner[google]` | `gemini-3.7-flash` |
| `groq` | `GROQ_API_KEY` | `initrunner[groq]` | `llama-4-scout-17b-16e` |
| `mistral` | `MISTRAL_API_KEY` | `initrunner[mistral]` | `mistral-large-latest` |
| `cohere` | `CO_API_KEY` | `initrunner[all-models]` | `command-a` |
| `bedrock` | `AWS_ACCESS_KEY_ID` | `initrunner[all-models]` | `us.anthropic.claude-sonnet-4-6-v1:0` |
| `xai` | `XAI_API_KEY` | *(uses openai SDK)* | `grok-4` |
| `ollama` | *(none)* | *(included in core)* | `llama3.2` |

Default Model is the entry the wizard preselects. It shows a curated list per provider and also accepts any custom model name you type. For `ollama`, `llama3.2` is the default only when no local models are detected; if the Ollama server responds, the wizard lists the models you have installed and defaults to the first one.

## How It Works

### 1. Provider and model

The wizard scans environment variables and `~/.initrunner/.env` for existing keys (Anthropic, OpenAI, Google, Groq, Mistral, Cohere, xAI, OpenRouter, Ollama).

- **One provider detected** — confirm it, or pick another.
- **Several detected** — numbered list of those only.
- **None detected** — full cloud + Ollama menu.

It then checks the provider SDK (and offers to install the extra), records the API key (skipped for Ollama; Bedrock uses AWS credentials + region), and asks for a model.

OpenRouter is stored as `provider: openai` with `base_url: https://openrouter.ai/api/v1` and `api_key_env: OPENROUTER_API_KEY`.

### 2. Save

Writes `~/.initrunner/run.yaml` unless you passed `--skip-run-yaml`. Keys go to `~/.initrunner/.env` with `0600` permissions.

### 3. Verify

A light connectivity check for OpenAI and Anthropic. Skip with `--skip-test`.

### After setup

In a TTY, without `-y`:

```
  1. Chat
  2. Try a starter
  3. Create an agent
```

Enter selects Chat. Dashboard is not in this list; run `initrunner dashboard` if you want the web UI.

Non-TTY and `-y` print:

```
initrunner run -i
initrunner run memory -i
initrunner new
```

To build a role, use `initrunner new` (describe, template, example, or offline form). Browse examples with `initrunner examples list`.

## Non-Interactive Usage

```bash
export OPENAI_API_KEY="sk-..."
initrunner setup --provider openai --model gpt-5-mini --skip-test -y

initrunner setup --provider ollama --model llama3.2 --skip-test -y

initrunner setup --provider openai --skip-test --skip-run-yaml -y
```

The API key must already be in the environment or `~/.initrunner/.env`. Without a TTY and without a key, setup fails.

## Configuration Files

### Global `.env`

```
OPENAI_API_KEY=sk-...
```

Path: `INITRUNNER_HOME` > `XDG_DATA_HOME/initrunner` > `~/.initrunner`.

### Run config

`~/.initrunner/run.yaml`:

```yaml
provider: openai
model: gpt-5-mini
tool_profile: minimal
memory: true
name: ephemeral
```

Custom endpoint (e.g. OpenRouter):

```yaml
provider: openai
model: anthropic/claude-sonnet-4
base_url: https://openrouter.ai/api/v1
api_key_env: OPENROUTER_API_KEY
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | string | *null* | Provider name |
| `model` | string | *null* | Model identifier |
| `base_url` | string | *null* | Custom endpoint URL (OpenAI-compatible) |
| `api_key_env` | string | *null* | Environment variable containing the API key |
| `tool_profile` | string | `minimal` | `none`, `minimal`, or `all` |
| `memory` | bool | `true` | Enable long-term memory |
| `tools` | list | `[]` | Extra tool types |
| `ingest` | list | `[]` | Paths to ingest for RAG |
| `personality` | string | *null* | Custom system prompt |
| `name` | string | `ephemeral` | Ephemeral agent name |

`initrunner run` (ephemeral), `initrunner new`, `flow new`, and `doctor` read this file. CLI `--provider` / `--model` override it.

## Troubleshooting

### Unknown provider

```
Error: Unknown provider 'foo'. Choose from: openai, anthropic, google, groq, mistral, cohere, bedrock, xai, ollama
```

Include presets such as `openrouter` when you have that key.

### Key validation failed

The key is wrong or the provider API is unreachable. Re-run `setup` or set the env var and try `initrunner doctor`.
