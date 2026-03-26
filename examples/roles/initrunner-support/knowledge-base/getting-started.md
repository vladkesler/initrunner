# Getting Started with InitRunner

InitRunner is a YAML-first AI agent platform. You define agents as declarative `role.yaml` files and run them as one-shot commands, interactive REPLs, trigger-driven daemons, or API servers.


## Installation

Install with pip, uv, or pipx:

```bash
# pip
pip install initrunner

# uv (recommended)
uv pip install initrunner

# pipx (isolated global install)
pipx install initrunner
```

For optional features, install extras:

```bash
# All model providers
pip install initrunner[anthropic,google,groq,mistral]

# Document ingestion (PDF, DOCX, XLSX support)
pip install initrunner[ingest]

# Everything
pip install initrunner[all-models,ingest]
```


## First-time setup

Run the setup wizard to configure your default provider:

```bash
initrunner setup
```

This walks you through selecting a provider, entering your API key, and running a quick smoke test. Your key is saved to `~/.initrunner/.env`.

Alternatively, export your API key directly:

```bash
export OPENAI_API_KEY="sk-..."
# or
export ANTHROPIC_API_KEY="sk-ant-..."
```


## Creating your first agent

### Quick chat (no role file needed)

```bash
# One-shot prompt
initrunner run -p "Explain Python decorators in 3 sentences"

# Interactive REPL
initrunner run
```

The `chat` command auto-detects your provider from available API keys. It checks in order: Anthropic, OpenAI, Google, Groq, Mistral, Cohere, Ollama.

### Scaffolding a new agent

```bash
# From a natural language description
initrunner new "A code reviewer that checks for security issues"

# From a built-in template
initrunner new --template rag
initrunner new --template memory
initrunner new --template ollama

# Minimal blank template
initrunner new --blank
```

### Running an agent

```bash
# Single-shot with a prompt
initrunner run role.yaml -p "Summarize the README"

# Interactive REPL
initrunner run role.yaml -i

# Resume a previous session
initrunner run role.yaml -i --resume

# Dry run (validate without calling the model)
initrunner run role.yaml -p "test" --dry-run
```


## Validating a role file

Check that your role definition is valid before running:

```bash
initrunner validate role.yaml
```

This validates the YAML structure, checks tool types, and verifies that referenced files and paths exist.


## Doctor command

Diagnose provider configuration and connectivity:

```bash
# Check all providers
initrunner doctor

# Full smoke test (sends a test prompt)
initrunner doctor --quickstart

# Smoke test with a specific role
initrunner doctor --quickstart --role role.yaml
```

Doctor checks API key presence, SDK availability, and Ollama reachability. The `--quickstart` flag sends a test prompt to verify end-to-end connectivity.


## Core CLI commands

| Command | Purpose |
|---------|---------|
| `chat [PATH]` | Ephemeral chat REPL or bot launcher |
| `run <PATH>` | Single-shot or interactive agent run |
| `validate <PATH>` | Validate a role definition |
| `new [DESCRIPTION]` | Scaffolding wizard for new agents |
| `setup` | Guided provider configuration |
| `ingest <PATH>` | Ingest documents into the vector store |
| `doctor` | Check provider config and connectivity |
| `run <PATH> --serve` | Launch an OpenAI-compatible API server |
| `run <PATH> --daemon` | Run a trigger-driven daemon |
| `memory <subcommand>` | Manage agent memory (list, clear, export, import) |
| `install <SOURCE>` | Install a role from InitHub or OCI registry |
| `publish [PATH]` | Publish a role to InitHub or OCI registry |
| `search [QUERY]` | Search InitHub for published agents |


## Environment variables

| Variable | Effect |
|----------|--------|
| `INITRUNNER_MODEL` | Override the model at runtime |
| `INITRUNNER_DEFAULT_MODEL` | Model for intent sensing tiebreaker |
| `INITRUNNER_AUDIT_DB` | Custom audit database path |
| `INITRUNNER_SKILL_DIR` | Extra skill search directory |


## Directory path resolution

When you pass a directory instead of a file, InitRunner looks for `role.yaml` or the first `*.yaml` file with `apiVersion: initrunner/v1` and `kind: Agent`. This means you can run:

```bash
cd my-agent/
initrunner run .
```
