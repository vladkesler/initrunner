# Role Generation

InitRunner provides three ways to create `role.yaml` files: an interactive CLI wizard, an AI-powered generator, and the web dashboard. All three produce validated YAML that can be used immediately with `initrunner run`.

## Interactive Wizard

Launch the guided wizard with the `-i` flag:

```bash
initrunner init -i
```

The wizard walks through each section of a role definition, building a complete `role.yaml` step by step.

### Wizard Flow

1. **Agent name** — lowercase with hyphens (e.g. `my-agent`)
2. **Description** — optional free-text
3. **Provider** — choose from `openai`, `anthropic`, `google`, `groq`, `mistral`, `cohere`, `ollama`
4. **Model** — choose from a curated list of models for the selected provider, or type a custom model name
5. **Base template** — pre-populates system prompt, tools, and features (see table below)
6. **Tool selection** — pick tools by number or name, then configure each one
7. **Memory** — enable/disable long-term memory
8. **Ingestion** — enable/disable RAG with source glob and chunking config
9. **Output file** — path to write (default: `role.yaml`)

### Templates

| Template | Description |
|----------|-------------|
| `basic` | Simple assistant |
| `rag` | Answers from your documents |
| `memory` | Remembers across sessions |
| `daemon` | Runs on schedule / watches files |
| `api` | Declarative REST API tools |
| `blank` | Just the essentials, add everything yourself |

### Available Tools

| Tool | Description |
|------|-------------|
| `filesystem` | Read/write files |
| `git` | Git operations |
| `python` | Execute Python code |
| `shell` | Run shell commands |
| `http` | HTTP requests |
| `web_reader` | Fetch web pages |
| `sql` | Query SQLite databases |
| `datetime` | Date/time utilities |
| `mcp` | MCP server integration |
| `slack` | Send Slack messages |

Each selected tool prompts for its key configuration fields. For example, `filesystem` asks for `root_path` and `read_only`; `shell` asks for `require_confirmation` and `timeout_seconds`.

The wizard validates the generated YAML against the `RoleDefinition` schema before writing and warns if there are issues.

### Anthropic Embedding Warning

When the wizard detects that `anthropic` is selected as the provider **and** memory or ingestion is enabled, it displays a warning:

> **Warning:** Anthropic does not provide an embeddings API. RAG and memory features require `OPENAI_API_KEY` for embeddings.

The warning also mentions that the embedding provider can be overridden via `spec.ingest.embeddings` or `spec.memory.embeddings` in the generated role file.

## AI-Powered Generation

Generate a complete `role.yaml` from a natural language description:

```bash
initrunner create "A code review assistant that reads git diffs and suggests improvements"
```

### CLI Flags

| Flag | Description |
|------|-------------|
| `--provider TEXT` | Model provider for generation (auto-detected if omitted) |
| `--output PATH` | Output file path (default: `role.yaml`) |
| `--name TEXT` | Agent name (auto-derived from description if omitted) |
| `--model TEXT` | Model name for the generated role (e.g. `gpt-4o`, `claude-sonnet-4-5-20250929`) |
| `--no-confirm` | Skip the YAML preview and write immediately |

### How It Works

1. Builds a dynamic schema reference by introspecting Pydantic models (`build_schema_reference()` in `role_generator.py`). This includes all tool types from the registry, trigger types, sink types, and every configurable field with defaults.
2. Sends the description plus schema reference to the configured LLM.
3. Validates the returned YAML against `RoleDefinition`.
4. If validation fails, retries once by sending the error back to the LLM for correction.

### Provider Auto-Detection

When `--provider` is omitted, `services.py` checks for available API keys in the environment (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) and uses the first provider found. Falls back to `openai`.

## Dashboard — Create Role

The web dashboard at `/roles/new` offers two tabs for role creation.

### Form Builder Tab

A structured form with fields for:

- Name, description
- Provider, model (dropdown with curated per-provider options and custom input)
- System prompt
- Tool checkboxes
- Memory and ingestion toggles
- Live YAML preview that updates as you fill in the form

Submitting the form calls `POST /api/roles` with the generated YAML.

### AI Generate Tab

- Enter a natural language description
- Click **Generate** to produce a `role.yaml` via AI
- Review and edit the generated YAML
- Click **Save** to persist

This calls `POST /api/roles/generate` to get the YAML, then `POST /api/roles` to save.

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/roles` | Create a new role from YAML content (`RoleCreateRequest`) |
| `POST` | `/api/roles/generate` | Generate YAML from a description (`RoleGenerateRequest`) |

`POST /api/roles` returns `409` if a role file with the same name already exists.

## Dashboard — Edit Existing Roles

The role detail page (`/roles/{role_id}`) includes an editable YAML tab with **Save** and **Reset** buttons.

- **Save** calls `PUT /api/roles/{role_id}` with the updated YAML content
- Creates a `.bak` backup of the existing file before overwriting
- Validates the YAML against `RoleDefinition` before writing

| Method | Endpoint | Description |
|--------|----------|-------------|
| `PUT` | `/api/roles/{role_id}` | Update an existing role's YAML (`RoleYamlUpdateRequest`) |

## Programmatic Usage

All role creation logic lives in `services.py` for use by CLI, API, and TUI:

| Function | Description |
|----------|-------------|
| `build_role_yaml_sync()` | Build YAML from structured parameters (name, provider, tools, etc.) |
| `generate_role_sync()` | Generate YAML from a natural language description via LLM |
| `save_role_yaml_sync()` | Validate YAML, create `.bak` backup if overwriting, and write to disk |

Example:

```python
from initrunner.services import build_role_yaml_sync, save_role_yaml_sync
from pathlib import Path

yaml_text = build_role_yaml_sync(
    name="my-agent",
    provider="openai",
    model_name="gpt-4o",
    tools=[{"type": "filesystem", "root_path": ".", "read_only": True}],
    memory=True,
)

role = save_role_yaml_sync(Path("role.yaml"), yaml_text)
```

## Security

- **Name validation**: `metadata.name` must match `^[a-z0-9][a-z0-9-]*[a-z0-9]$`
- **Directory restrictions**: API writes are restricted to configured role directories; path traversal (`..`) is rejected
- **Overwrite protection**: `POST /api/roles` returns `409` if the file exists; `PUT` and `save_role_yaml_sync()` create a `.bak` backup before overwriting
- **Validation before write**: YAML is parsed and validated against `RoleDefinition` before being written to disk

## See Also

- [CLI Reference](../getting-started/cli.md) — full list of `init` and `create` flags
- [Tool Creation](tool_creation.md) — writing custom tool modules
- [Web Dashboard](../interfaces/dashboard.md) — dashboard setup and features
- [Security Model](../security/security.md) — guardrails and access controls
