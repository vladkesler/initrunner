# Setup Wizard

The `initrunner setup` command is a guided wizard that configures your model provider, API key, and first agent role in one step. It detects existing configuration, installs missing SDKs, validates API keys, and creates a ready-to-run `role.yaml`.

## Quick Start

```bash
# Interactive setup (prompts for provider, key, and template)
initrunner setup

# Non-interactive with all options specified
initrunner setup --provider openai --template chatbot --name my-agent

# Local Ollama setup (no API key needed)
initrunner setup --provider ollama

# Skip the connectivity test
initrunner setup --skip-test
```

## Options Reference

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--provider` | `str` | *(interactive)* | Provider name. Skips the interactive selection prompt. |
| `--name` | `str` | `my-agent` | Agent name used in the generated role YAML. |
| `--template` | `str` | *(interactive)* | Starter template: `chatbot`, `rag`, `memory`, or `daemon`. |
| `--skip-test` | `bool` | `false` | Skip the connectivity test after setup. |
| `--output` | `Path` | `role.yaml` | Output path for the generated role file. |

## Supported Providers

| Provider | Env Var | Install Extra | Default Model |
|----------|---------|---------------|---------------|
| `openai` | `OPENAI_API_KEY` | *(included in core)* | `gpt-4o-mini` |
| `anthropic` | `ANTHROPIC_API_KEY` | `initrunner[anthropic]` | `claude-sonnet-4-5-20250929` |
| `google` | `GOOGLE_API_KEY` | `initrunner[google]` | `claude-sonnet-4-5-20250929` |
| `groq` | `GROQ_API_KEY` | `initrunner[groq]` | `claude-sonnet-4-5-20250929` |
| `mistral` | `MISTRAL_API_KEY` | `initrunner[mistral]` | `claude-sonnet-4-5-20250929` |
| `cohere` | `CO_API_KEY` | `initrunner[all-models]` | `claude-sonnet-4-5-20250929` |
| `ollama` | *(none)* | *(included in core)* | `llama3.2` |

## How It Works

### 1. Already-Configured Detection

The wizard checks whether any known provider API key is already set, looking in two places:

1. **Environment variables** — checks each provider's env var (e.g. `OPENAI_API_KEY`).
2. **Global `.env` file** — reads `~/.initrunner/.env` via `dotenv_values()`.

If a key is found, the wizard reports which variable was detected and asks whether to run setup again. If declined, the wizard exits.

### 2. Provider Selection

When `--provider` is not passed, an interactive prompt lists all supported providers with `openai` as the default. When `--provider` is passed, the value is validated against the supported list. Unknown providers cause an immediate error.

### 3. Dependency Check

For **Ollama**, the wizard checks that the Ollama server is running and queries `http://localhost:11434/api/tags` for available models. If no models are found, it suggests running `ollama pull llama3.2`.

For all other providers, the wizard checks whether the provider SDK is importable. If not:

1. Prompts to install it automatically (via `uv pip install` or `pip install`).
2. If installation fails, offers to continue anyway.
3. If declined, prints a manual install hint and exits.

### 4. API Key Configuration

Skipped for Ollama (no API key required). For other providers:

1. Checks for an existing key in the environment, then in `~/.initrunner/.env`.
2. If found, asks whether to keep it. If not found, prompts for entry (masked input).
3. For OpenAI and Anthropic, validates the key with a lightweight API call.
4. If validation fails, offers to re-enter the key.
5. Saves the key to `~/.initrunner/.env` with `0600` permissions.

### 5. Role Creation

If the output file already exists, role creation is skipped. Otherwise:

When `--template` is not passed, an interactive menu presents four options:

1. **chatbot** — Simple assistant, great for getting started.
2. **rag** — Answers questions from your documents.
3. **memory** — Remembers things across conversations.
4. **daemon** — Runs on a schedule or watches files for changes.

When `--provider ollama` is used, the wizard always uses the Ollama-specific template regardless of the template selection.

The generated role YAML is written to the `--output` path (default: `role.yaml`).

### 6. Connectivity Test

Unless `--skip-test` is passed, the wizard loads the generated role, builds an agent, and sends a test prompt (`"Hello, respond in one sentence."`). The first 200 characters of the response are displayed.

If the test fails, a warning is printed but setup is still considered complete.

### 7. Summary

A summary panel is displayed showing the configured provider, default model, config file path, and role file path. Next-step commands are printed:

```
initrunner run role.yaml -p "Ask me anything"
initrunner run role.yaml -i          # interactive REPL
initrunner validate role.yaml
initrunner init --template rag       # more templates
initrunner tui                       # terminal dashboard
```

## Templates

| Template | Internal Key | Description |
|----------|-------------|-------------|
| `chatbot` | `basic` | Minimal assistant with guardrails. No tools, ingestion, or triggers. |
| `rag` | `rag` | Knowledge assistant with `ingest` config and `search_documents` tool. Sources default to `./docs/**/*.md` and `./docs/**/*.txt`. |
| `memory` | `memory` | Assistant with `memory` config. Auto-registers `remember()`, `recall()`, and `list_memories()` tools. |
| `daemon` | `daemon` | Event-driven agent with `triggers` config. Includes a file watcher and a cron schedule. |

All templates include guardrails (`max_tokens_per_run`, `max_tool_calls`, `timeout_seconds`, `max_request_limit`) and use the default model for the selected provider.

When `--provider ollama` is used, the `ollama` template is always used instead, which sets `provider: ollama` and `name: llama3.2` regardless of the template selection.

## Non-Interactive Usage

For CI, automation, or scripting, pass all options as flags to skip all prompts:

```bash
# Fully non-interactive OpenAI setup
export OPENAI_API_KEY="sk-..."
initrunner setup --provider openai --template chatbot --name my-agent --skip-test

# Ollama (no API key needed)
initrunner setup --provider ollama --template chatbot --skip-test

# Custom output path
initrunner setup --provider anthropic --template rag --output agents/researcher.yaml --skip-test
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

The `.env` file is loaded automatically by `initrunner run` and other commands via `dotenv`. Keys set directly in the environment take precedence over `.env` values.

### Generated Role

The generated `role.yaml` (or custom `--output` path) is a standard InitRunner role definition. See `initrunner validate <role.yaml>` to check it, or edit it directly to add tools, triggers, or ingestion config.

## Troubleshooting

### Unknown provider

```
Error: Unknown provider 'foo'. Choose from: openai, anthropic, google, groq, mistral, cohere, ollama
```

The `--provider` value must be one of the supported providers listed above.

### Unknown template

```
Error: Unknown template 'foo'. Choose from: chatbot, rag, memory, daemon
```

The `--template` value must be one of the four setup templates.

### SDK installation failed

```
Warning: Could not install initrunner[anthropic]: ...
Install manually: uv pip install initrunner[anthropic]
```

The automatic SDK installation failed. Install the provider extra manually using the printed command, then re-run setup.

### API key validation failed

```
Warning: API key validation failed.
```

The API key could not be verified against the provider's API. This can happen if:

- The key is invalid or expired.
- The provider API is temporarily unreachable.
- A proxy or firewall is blocking the request.

You can re-enter the key when prompted, or continue with the current key and troubleshoot later.

### Could not write .env file

```
Warning: Could not write ~/.initrunner/.env: [Errno 13] Permission denied
Set it manually: export OPENAI_API_KEY=sk-...
```

The wizard could not write the API key to the global `.env` file. Set the environment variable manually in your shell profile instead.

### Test run failed

```
Warning: Test run failed: ...
Setup is still complete -- check your configuration and try again.
```

The connectivity test after setup failed. This does not invalidate the setup. Common causes:

- API key is incorrect.
- Provider SDK is not installed.
- Ollama server is not running.
- Network issues.

Run `initrunner run role.yaml -p "hello"` manually to debug.

### Output file already exists

```
role.yaml already exists, skipping role creation.
```

The wizard does not overwrite existing role files. Use `--output` to specify a different path, or delete the existing file first.
