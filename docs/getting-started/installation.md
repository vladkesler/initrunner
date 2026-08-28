# Installation

## Quick install

The install script auto-detects `uv`, `pipx`, or `pip` (and installs `uv` if none are found). It includes web search, document ingestion, MCP, the vector store, and the dashboard by default:

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

The core install is the agent runtime and nothing optional: OpenAI and Ollama models,
every built-in tool that needs no extra dependency, triggers, the OpenAI-compatible
`--serve` API, flows, teams and groups. It leaves out MCP servers and the vector store,
which together are roughly a third of a running agent's memory, so this is the install
to reach for when you are packing many agents onto one box.

A role that uses `type: mcp`, `memory:`, `ingest:` or the `web_scraper` tool still
validates here; it fails at load naming what it needs, and offers to install it.

```bash
# shell installer
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --extras none

# uv
uv pip install initrunner

# pip
pip install initrunner
```

## Install everything

Install every provider, feature, and interface:

```bash
# shell installer
curl -fsSL https://initrunner.ai/install.sh | sh -s -- --extras all

# uv
uv pip install "initrunner[all]"

# pip
pip install "initrunner[all]"
```

## What to install

Four names cover it. Everything else in `pyproject.toml` is there for packagers.

| Install | Gets you |
|---------|----------|
| `initrunner` | The core runtime: OpenAI and Ollama models, every tool that needs no extra dependency, triggers, flows, teams, groups, and the OpenAI-compatible `--serve` API. |
| `initrunner[recommended]` | Core plus web search, document ingestion, the vector store behind `memory:` and `ingest:`, MCP, and the dashboard. This is what the install script gives you. |
| `initrunner[all]` | Everything above plus every provider SDK, YouTube transcripts, the profanity filter, OpenTelemetry, the Telegram/Discord/Slack triggers, the A2A server, and the credential vault. |
| `initrunner[anthropic]` and friends | One provider SDK. Also `google`, `groq`, `mistral`, `cohere`, `bedrock`, `xai`, or `all-models` for all seven. |

Two things are deliberately outside `[all]`, because both are large and neither
is worth carrying by default: the desktop app (`desktop`, which needs a system
GUI toolkit) and local fastembed embeddings (`local-embeddings`, which pulls in
the ONNX runtime). Both install on demand, like everything else below.

## Missing something?

Nothing is a dead end. A role or command that needs something this install does
not have says so by name and offers to fix it:

```
$ initrunner run scout -p "state of the RISC-V ecosystem"
Error: the scout starter needs initrunner[search]
Install now? [Y/n]
```

Answer yes and InitRunner runs the installer that put it there in the first
place, keeping the extras you already have, then reruns your command.

Where that is not safe or not possible, it prints the exact command for your
install instead of guessing. That covers pipx (which rebuilds the whole
environment), containers, a `uv sync` checkout, `uvx`, Windows, and any script
or CI job with no terminal attached. To get ahead of it, `initrunner doctor
--fix --role agent.yaml --yes` installs whatever a role asks for without
prompting.

## Development setup

```bash
git clone https://github.com/vladkesler/initrunner.git
cd initrunner
# The full suite exercises every optional dependency; plain `uv sync --dev`
# gives you the lean environment CI's test-lean job uses.
uv sync --dev --extra dashboard --extra a2a --extra mcp --extra vector
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
- **Windows** works but systemd-related flow features (`flow install/start/stop`) are unavailable.
- **Docker**: if using Ollama on the host from inside a container, set `base_url: http://host.docker.internal:11434/v1` in your role YAML.
