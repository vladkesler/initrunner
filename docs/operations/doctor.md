# Doctor

The `doctor` command checks your InitRunner environment — API keys, provider SDKs, and service connectivity — in a single command. With `--quickstart`, it runs a real agent prompt to verify the entire stack end-to-end.

## Quick Start

```bash
# Check provider configuration
initrunner doctor

# Full end-to-end smoke test (makes a real API call)
initrunner doctor --quickstart

# Test a specific role file
initrunner doctor --quickstart --role role.yaml
```

## CLI Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--quickstart` | `bool` | `false` | Run a smoke prompt to verify end-to-end connectivity. |
| `--role` | `Path` | — | Role file to test. Used for `.env` loading and as the agent for `--quickstart`. |

## Config Scan

The config scan runs automatically on every `doctor` invocation. It checks:

| Check | What it verifies |
|-------|------------------|
| **API Key** | Whether the provider's environment variable is set (e.g. `OPENAI_API_KEY`) |
| **SDK** | Whether the provider's Python SDK is importable (only checked when key is set) |
| **Ollama** | Whether the Ollama server is reachable at `localhost:11434` |

Example output:

```
               Provider Status
┏━━━━━━━━━━━┳━━━━━━━━━┳━━━━━┳━━━━━━━━━━━━━━━━┓
┃ Provider  ┃ API Key ┃ SDK ┃ Status         ┃
┡━━━━━━━━━━━╇━━━━━━━━━╇━━━━━╇━━━━━━━━━━━━━━━━┩
│ openai    │ Set     │ OK  │ Ready          │
│ anthropic │ Missing │ —   │ Not configured │
│ google    │ Missing │ —   │ Not configured │
│ groq      │ Missing │ —   │ Not configured │
│ mistral   │ Missing │ —   │ Not configured │
│ cohere    │ Missing │ —   │ Not configured │
│ ollama    │ —       │ —   │ Ready          │
└───────────┴─────────┴─────┴────────────────┘
```

The scan loads `.env` files before checking, so keys defined in `.env` files (project-local or `~/.initrunner/.env`) are detected. If `--role` is provided, the `.env` in the role's directory is loaded first.

## Embedding Providers

After the provider table, `doctor` shows an **Embedding Providers** section that checks whether the API keys needed for embeddings (RAG and memory) are configured. This is separate from the LLM provider table because embedding keys can differ from LLM keys.

| Check | What it verifies |
|-------|------------------|
| **Embedding Key Env** | The environment variable name used for embedding API keys for each provider |
| **Status** | Whether the embedding key is set (`Set`), missing (`Missing`), or not needed (`No key needed` for Ollama) |

Example output:

```
               Embedding Providers
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ Provider  ┃ Embedding Key Env ┃ Status        ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ openai    │ OPENAI_API_KEY    │ Set           │
│ anthropic │ OPENAI_API_KEY    │ Set           │
│ google    │ GOOGLE_API_KEY    │ Missing       │
│ ollama    │ —                 │ No key needed │
└───────────┴───────────────────┴───────────────┘
Note: Anthropic uses OpenAI embeddings (OPENAI_API_KEY) for RAG/memory.
```

> **Important:** Anthropic does not offer an embeddings API. If your agent uses `provider: anthropic` with RAG or memory, you need `OPENAI_API_KEY` set for embeddings — even though `ANTHROPIC_API_KEY` handles the LLM. The doctor output makes this explicit.

## Quickstart Smoke Test

With `--quickstart`, the doctor runs a real agent prompt after the config scan:

```bash
initrunner doctor --quickstart
```

**What it does:**

1. Detects the available provider (or uses the one from `--role`)
2. Builds a minimal agent (or loads the role file if `--role` is given)
3. Sends a single prompt: "Say hello in one sentence."
4. Reports success or failure with response preview, token count, and duration

**On success:**

```
╭───────────────────────────── Quickstart Result ──────────────────────────────╮
│ Smoke test passed!                                                           │
│                                                                              │
│ Response: Hello!                                                             │
│ Tokens: 97 | Duration: 2229ms                                                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

**On failure**, the error is displayed and the command exits with code 1:

```
╭───────────────────────────── Quickstart Result ──────────────────────────────╮
│ Smoke test failed: Model API error: 401 Unauthorized                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### Testing a specific role

Use `--role` to test a specific role file. This loads the role's `.env`, builds the role's agent (with its model, tools, and system prompt), and runs the smoke prompt against it.

```bash
initrunner doctor --quickstart --role examples/roles/code-reviewer.yaml
```

This is useful for verifying that a role's provider, model, and SDK configuration work before deploying it.

## Use Cases

- **First-time setup**: Run `initrunner doctor` after `initrunner setup` to verify everything is configured.
- **CI/CD validation**: Add `initrunner doctor --quickstart` to your CI pipeline to catch provider configuration issues early.
- **Debugging**: When a role isn't working, `doctor` quickly shows whether the issue is a missing API key, missing SDK, or unreachable service.
- **Multi-provider environments**: See at a glance which providers are configured and ready.

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Config scan passed (without `--quickstart`), or smoke test passed |
| `1` | Smoke test failed or encountered an error |
