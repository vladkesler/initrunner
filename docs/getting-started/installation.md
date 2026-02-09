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

| Extra | Install command | What it adds |
|-------|----------------|--------------|
| `anthropic` | `pip install initrunner[anthropic]` | Anthropic provider |
| `google` | `pip install initrunner[google]` | Google provider |
| `groq` | `pip install initrunner[groq]` | Groq provider |
| `mistral` | `pip install initrunner[mistral]` | Mistral provider |
| `all-models` | `pip install initrunner[all-models]` | All providers |
| `ingest` | `pip install initrunner[ingest]` | Additional formats: PDF, DOCX, XLSX (base text ingestion is built-in) |
| `local-embeddings` | `pip install initrunner[local-embeddings]` | Local embeddings via fastembed (no API key needed) |
| `safety` | `pip install initrunner[safety]` | Profanity filter for content policy |
| `dashboard` | `pip install initrunner[dashboard]` | Web dashboard (FastAPI + Next.js) |
| `tui` | `pip install initrunner[tui]` | Terminal TUI dashboard (Textual) |

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
