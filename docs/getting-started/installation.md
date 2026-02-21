# Installation

## Quick install

The install script auto-detects `uv`, `pipx`, or `pip` (and installs `uv` if none are found):

```bash
curl -fsSL https://initrunner.ai/install.sh | sh
```

### Install with extras

```bash
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --extras ingest
```

### Pin a specific version

```bash
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --version 0.2.0
```

## Package managers

```bash
pip install initrunner
uv tool install initrunner
pipx install initrunner
```

## Extras

> **Tip:** Not sure which extras you need? Install `[all]` — it includes every provider, feature, and interface so everything just works out of the box.

### Install all extras (recommended)

```bash
# pip
pip install "initrunner[all]"

# uv
uv tool install "initrunner[all]"
# or in a venv:
uv pip install "initrunner[all]"

# pipx
pipx install "initrunner[all]"

# shell installer
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --extras all
```

### Pick and choose

You can combine specific extras with commas:

```bash
# pip
pip install "initrunner[ingest,search,dashboard]"

# uv
uv tool install "initrunner[ingest,search,dashboard]"

# pipx
pipx install "initrunner[ingest,search,dashboard]"

# shell installer (comma-separated)
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --extras ingest,search,dashboard
```

### Available extras

#### LLM Providers

| Extra | What it adds |
|-------|--------------|
| `all-models` | All LLM providers (Anthropic, Google, Groq, Mistral, Cohere, Bedrock, xAI) |
| `anthropic` | Anthropic provider (Claude) |
| `google` | Google provider (Gemini) |
| `groq` | Groq provider |
| `mistral` | Mistral provider |

#### Features

| Extra | What it adds |
|-------|--------------|
| `ingest` | PDF, DOCX, XLSX ingestion (base text ingestion is built-in) |
| `search` | Web search via DuckDuckGo (free, no API key) |
| `audio` | YouTube transcript extraction |
| `safety` | Profanity filter for content policy |
| `observability` | OpenTelemetry tracing and metrics export |

#### Messaging Triggers

| Extra | What it adds |
|-------|--------------|
| `telegram` | Telegram bot trigger |
| `discord` | Discord bot trigger |
| `channels` | Both Telegram and Discord |

#### Interfaces

| Extra | What it adds |
|-------|--------------|
| `tui` | Terminal TUI dashboard (Textual) |
| `dashboard` | Web dashboard (FastAPI + HTMX + DaisyUI) |

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
