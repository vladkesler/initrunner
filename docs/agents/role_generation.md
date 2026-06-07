# Role Generation

InitRunner provides a single `initrunner new` command for creating `role.yaml` files. It supports multiple seed modes (templates, AI generation, examples, hub bundles, or local files) and an interactive refinement loop for iterating on the YAML before saving. Run with no arguments in a terminal and it shows a guided start menu; a deterministic offline form is available for building a role with no AI/API key at all.

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

# Guided start menu (describe / template / example / offline / import)
initrunner new

# Build a role with no AI -- a deterministic structured form
initrunner new --offline
```

## CLI Flags

| Flag | Description |
|------|-------------|
| `DESCRIPTION` | Natural language description (generates via LLM) |
| `--from SOURCE` | Local file path, bundled example name, or `hub:ref` |
| `--template TEXT` | Start from a named template |
| `--blank` | Start from minimal blank template |
| `--offline` | Build via a deterministic structured form (no AI/LLM call) |
| `--provider TEXT` | Model provider (auto-detected if omitted) |
| `--model TEXT` | Model name (uses provider default if omitted) |
| `--output PATH` | Output file path (default: `role.yaml`) |
| `--force` | Overwrite existing file without prompting |
| `--no-refine` | Skip the interactive refinement loop |
| `--run PROMPT` | After creating, execute the agent immediately with `PROMPT`. Bypasses the post-creation confirmation. |
| `--no-run` | Skip the post-creation `Run it now?` confirmation. |

Seed modes are mutually exclusive: specify at most one of `DESCRIPTION`, `--from`, `--template`, `--blank`, `--offline`, `--langchain`, `--pydantic-ai`, or `--agent-spec`. `--run` and `--no-run` are also mutually exclusive.

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

### No Seed (Guided Menu)

```bash
initrunner new
```

In an interactive terminal, no seed shows a guided start menu. Each option is annotated with its credential implication so you know which paths need an API key:

```
How would you like to start?

  1. Describe it in natural language   (AI generates it)   (default)
  2. Start from a template             (no API key needed)
  3. Start from a bundled example      (no API key needed)
  4. Build it manually, no AI          (no API key needed)
  5. Import LangChain / PydanticAI / Agent Spec   (AI assists)
```

The default (option 1) is the AI describe-then-refine flow. Options 2-4 need no API key. When stdin is not a TTY (pipes/CI), the menu is skipped and the LLM starts a conversation asking what to build, as before.

### Offline (no API key)

```bash
initrunner new --offline
```

A deterministic, no-LLM structured form. It walks you through agent name, description, system prompt, provider/model, a tool multi-select (with required config prompted per tool), and feature toggles (memory, document ingestion, a cron trigger), then assembles a valid `role.yaml` with zero network calls. The result flows into the same preview, refinement, and save path as any other seed. This is also the natural fallback offered by the credential preflight when no API key is configured.

## Refinement Loop

After the initial seed, the builder shows a syntax-highlighted YAML panel with the agent name and validation status, then a refinement prompt:

```
+-- code-reviewer -------------------- VALID --+
| apiVersion: initrunner/v1                     |
| kind: Agent                                   |
| ...                                           |
+-----------------------------------------------+

Refine: describe a change, :help for commands, Enter to save, :quit to discard >
```

- Type plain text to ask the AI to refine the YAML (e.g. `add memory and switch to claude`)
- Press Enter (empty input) or type `save` to write the file
- Type `quit` or `q` to discard without saving
- Use `--no-refine` to skip the loop entirely

After each AI refinement, a one-line change summary (`+adds -removes`) is printed.

#### Commands

Input starting with `:` (or a bare `?` for help) runs a deterministic command -- no LLM call:

| Command | Description |
|---------|-------------|
| `:help` (or `?`) | Show the command list |
| `:yaml` | Show the full current YAML |
| `:validate` | Show the validation panel (errors / warnings / notes) |
| `:explain` | Plain-English summary of each section |
| `:tools` | List available tool types and the role's current tools |
| `:diff` | Unified diff vs the previous turn |
| `:model [provider:name]` | Change the model deterministically; bare `:model` opens a picker |
| `:undo` | Revert the last change (AI refinement or `:model`) |
| `:save` | Save and exit (also: empty line) |
| `:quit` | Discard and exit (also: `q`) |

`:undo` reverts the YAML to the previous turn; `:model` and `:undo` preserve the tailored test prompt, so the post-creation `Run it now?` offer still appears after using them.

The refinement LLM has the full schema reference and tool registry, so it can add tools, triggers, memory, ingest, reasoning, autonomy, security, and observability sections by name. The schema reference includes field-level details for all sections, so the LLM knows which fields are required (e.g. `sources` for ingest) and which can be omitted for defaults.

**No API key configured?** Template, example, and offline seeds work without a key. In that case the refinement loop runs in command-only mode: the `:` commands (including `:model`) still work, but plain-text AI refinement prints a hint instead of failing with an authentication error.

## Provider Auto-Detection

When `--provider` is omitted, `initrunner new` resolves the builder model using the standard precedence:

1. `INITRUNNER_MODEL` env var
2. `~/.initrunner/run.yaml` (saved by `initrunner setup`)
3. API key env-var auto-detection (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.)
4. Falls back to `openai`

If your saved `run.yaml` specifies a provider, that provider is used even if other API keys exist in the environment. Custom endpoint fields (`base_url`, `api_key_env`) from `run.yaml` are also injected into the generated YAML, so OpenRouter and other custom-endpoint setups work out of the box.

### Credential preflight

Before an AI-backed seed in the guided menu, `initrunner new` resolves the key (via the vault and environment) and prints the model it is about to use:

```
Using openai:gpt-5-mini
```

If no key is configured (in an interactive terminal), it offers to enter a key inline, switch provider, or build offline -- instead of failing with a 401 partway through generation. Switching provider re-resolves the model and any custom-endpoint preset. When stdin is not a TTY, the preflight is skipped and a missing key surfaces as the usual authentication error from the model call.

## Post-Creation Output

After saving, the builder shows contextual next-step hints based on the role's features:

```
Created role.yaml

Next steps:
  initrunner ingest role.yaml
  initrunner run role.yaml -p 'hello'
  initrunner validate role.yaml
```

### Run it now?

For runnable one-shot agents (no triggers, no `ingest` block, valid YAML), `initrunner new` then asks whether to execute the agent immediately:

```
Run it now with prompt: 'explain what `^[a-z]+$` matches'? [Y/n]
```

The suggested prompt is generated by the builder LLM as part of the same call that produced the YAML. The builder's system prompt asks for a single `Test prompt: ...` line in the explanation; that line is parsed out and surfaced here. If the LLM omits it (e.g. because the agent is daemon-only), the confirmation is skipped.

Press Enter to execute. The agent runs through the same code path as `initrunner run role.yaml -p '...'`, including streaming, audit logging, and report export.

The confirmation is skipped when:
- `--run PROMPT` was given (the prompt is used directly, no question)
- `--no-run` was given
- the role has triggers or an `ingest` block
- the saved YAML is invalid
- no tailored prompt was produced (blank/template seeds without refinement, imports)
- stdin is not a TTY (piped input, CI)

For scripting, `--run PROMPT` collapses generation and execution into a single command:

```bash
initrunner new "a regex explainer" --run "what does ^[a-z]+$ match?"
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
