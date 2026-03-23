# Role Generation

InitRunner provides a single `initrunner new` command for creating `role.yaml` files. It supports multiple seed modes (templates, AI generation, examples, hub bundles, or local files) and an interactive refinement loop for iterating on the YAML before saving.

## Quick Start

```bash
# Generate from a description with interactive refinement
initrunner new "A code review assistant that reads git diffs"

# Start from a template, skip refinement
initrunner new --template rag --no-refine

# Blank template with a specific provider
initrunner new --blank --provider anthropic

# Load from a bundled example
initrunner new --from hello-world

# Fully interactive (no seed -- LLM asks what to build)
initrunner new
```

## CLI Flags

| Flag | Description |
|------|-------------|
| `DESCRIPTION` | Natural language description (generates via LLM) |
| `--from SOURCE` | Local file path, bundled example name, or `hub:ref` |
| `--template TEXT` | Start from a named template |
| `--blank` | Start from minimal blank template |
| `--provider TEXT` | Model provider (auto-detected if omitted) |
| `--model TEXT` | Model name (uses provider default if omitted) |
| `--output PATH` | Output file path (default: `role.yaml`) |
| `--force` | Overwrite existing file without prompting |
| `--no-refine` | Skip the interactive refinement loop |

Seed modes are mutually exclusive: specify at most one of `DESCRIPTION`, `--from`, `--template`, or `--blank`.

## Seed Modes

### Description (AI-powered)

```bash
initrunner new "A knowledge assistant that searches company docs"
```

Sends the description plus a dynamic schema reference to the configured LLM. The schema reference is built by introspecting Pydantic models (`build_schema_reference()`) and the live tool registry (`build_tool_summary()`), so it always stays in sync with the code.

If the generated YAML has validation errors, the builder automatically retries once by sending the errors back to the LLM.

### Template

```bash
initrunner new --template rag
```

Available templates: `basic`, `rag`, `daemon`, `memory`, `ollama`, `api`, `telegram`, `discord`.

### Blank

```bash
initrunner new --blank
```

Produces a minimal valid role YAML with sensible defaults.

### From Source

```bash
initrunner new --from ./existing-role.yaml   # local file
initrunner new --from hello-world            # bundled example
initrunner new --from hub:owner/package      # hub bundle
```

Resolution order for `--from SOURCE`:
1. Starts with `hub:` -- fetches from the hub (role YAML only)
2. Exists as a filesystem path -- loads the local file
3. Otherwise -- looks up as a bundled example name

For multi-file example/hub bundles, only the primary role YAML is loaded into the builder. Omitted sidecar files (skills, configs, etc.) are listed as a warning. Use `initrunner examples copy <name>` to get all files.

### No Seed (Interactive)

```bash
initrunner new
```

When no seed is specified, the LLM starts a conversation asking what kind of agent to build.

## Refinement Loop

After the initial seed, the builder shows a syntax-highlighted YAML panel with the agent name and validation status:

```
+-- code-reviewer -------------------- VALID --+
| apiVersion: initrunner/v1                     |
| kind: Agent                                   |
| ...                                           |
+-----------------------------------------------+

Refine (empty to save, "quit" to discard):
> add memory and change model to claude
```

- Type a refinement request to iterate on the YAML
- Press Enter (empty input) or type `save` to write the file
- Type `quit` or `q` to discard without saving
- Use `--no-refine` to skip the loop entirely

The refinement LLM has the full schema reference and tool registry, so it can add tools, triggers, memory, and other features by name.

## Provider Auto-Detection

When `--provider` is omitted, InitRunner checks for available API keys in the environment (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) and uses the first provider found. Falls back to `openai`.

## Post-Creation Output

After saving, the builder shows contextual next-step hints based on the role's features:

```
Created role.yaml

Next steps:
  initrunner ingest role.yaml
  initrunner run role.yaml -p 'hello'
  initrunner validate role.yaml
```

## Scaffolding Tools and Skills

Tool and skill scaffolds use dedicated sub-commands instead of `new`:

```bash
# Scaffold a custom tool module
initrunner new --template tool

# Scaffold a skill directory
initrunner skill new my-skill
```

## Programmatic Usage

The builder service layer (`services/agent_builder.py`) is UI-agnostic and can be used programmatically:

```python
from initrunner.services.agent_builder import BuilderSession
from pathlib import Path

session = BuilderSession()

# Seed from description
turn = session.seed_description("a code review bot", "openai")

# Refine
turn = session.refine("add git and filesystem tools", "openai")

# Save
result = session.save(Path("role.yaml"))
print(result.next_steps)
```

Legacy one-shot generation is still available via `generate_role()` and `generate_role_sync()`, which now delegate to `BuilderSession` internally.

## Security

- **Name validation**: `metadata.name` must match `^[a-z0-9][a-z0-9-]*[a-z0-9]$`
- **Directory restrictions**: API writes are restricted to configured role directories; path traversal (`..`) is rejected
- **Overwrite protection**: CLI prompts before overwriting; `POST /api/roles` returns `409` if the file exists; `save_role_yaml_sync()` creates a `.bak` backup before overwriting
- **Validation before write**: YAML is parsed and validated against `RoleDefinition` before being written to disk

## See Also

- [CLI Reference](../getting-started/cli.md) -- full list of `new` command flags
- [Tool Creation](tool_creation.md) -- writing custom tool modules
- [Security Model](../security/security.md) -- guardrails and access controls
