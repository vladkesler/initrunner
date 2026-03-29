# Installation

## Quick install

The install script auto-detects `uv`, `pipx`, or `pip` (and installs `uv` if none are found). It includes web search, document ingestion, and the dashboard by default:

```bash
curl -fsSL https://initrunner.ai/install.sh | sh
```

Your LLM provider SDK is installed automatically during [`initrunner setup`](setup.md). OpenAI and Ollama are built-in.

### Pin a specific version

```bash
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --version 0.2.0
```

## Package managers

```bash
# uv (recommended)
uv pip install "initrunner[recommended]"

# uv global tool
uv tool install "initrunner[recommended]"

# pipx
pipx install "initrunner[recommended]"

# pip
pip install "initrunner[recommended]"
```

## Minimal install

If you only need the core agent runtime (OpenAI + Ollama, text ingestion, vector search):

```bash
# shell installer
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --extras none

# uv
uv pip install initrunner

# pip
pip install initrunner
```

## Install everything

Install all providers, features, and interfaces:

```bash
# shell installer
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --extras all

# uv
uv pip install "initrunner[all]"

# pip
pip install "initrunner[all]"
```

## Available extras

The `[recommended]` bundle includes `search`, `ingest`, and `dashboard`. The `[all]` bundle includes everything below.

| Extra | What it adds |
|-------|--------------|
| **Bundles** | |
| `recommended` | Search + document ingestion + dashboard |
| `all` | Every extra below |
| **LLM Providers** | |
| `all-models` | All LLM providers (Anthropic, Google, Groq, Mistral, Cohere, Bedrock, xAI) |
| `anthropic` | Anthropic provider (Claude) |
| `google` | Google provider (Gemini) |
| `groq` | Groq provider |
| `mistral` | Mistral provider |
| **Features** | |
| `ingest` | PDF, DOCX, XLSX ingestion (base text ingestion is built-in) |
| `search` | Web search via DuckDuckGo (free, no API key) |
| `audio` | YouTube transcript extraction |
| `safety` | Profanity filter for content policy |
| `observability` | OpenTelemetry tracing and metrics export |
| **Messaging Triggers** | |
| `telegram` | Telegram bot trigger |
| `discord` | Discord bot trigger |
| `channels` | Both Telegram and Discord |
| **Interfaces** | |
| `dashboard` | Web UI (FastAPI + Uvicorn) |
| `desktop` | Desktop app (dashboard + PyWebView) |

Combine specific extras with commas: `uv pip install "initrunner[ingest,search,anthropic]"`.

> **Note:** `local-embeddings` (fastembed) is defined but **not yet implemented**. Use [Ollama](../configuration/ollama.md) for local embeddings instead.

## Development setup

```bash
git clone https://github.com/vladkesler/initrunner.git
cd initrunner
uv sync
uv run pytest tests/ -v
uv run ruff check .
uv run initrunner --version
```

## Environment variables

By default, InitRunner stores data in `~/.initrunner/`. Override this with the `INITRUNNER_HOME` environment variable:

```bash
export INITRUNNER_HOME=/data/initrunner
initrunner run role.yaml -p "hello"
```

Resolution order: `INITRUNNER_HOME` > `XDG_DATA_HOME/initrunner` > `~/.initrunner`.

This is useful for container deployments or CI environments where the home directory may not be writable.

## Platform notes

- **Python 3.11+** is required.
- **Linux / macOS / WSL** are fully supported.
- **Windows** works but systemd-related compose features (`compose install/start/stop`) are unavailable.
- **Docker**: if using Ollama on the host from inside a container, set `base_url: http://host.docker.internal:11434/v1` in your role YAML.
