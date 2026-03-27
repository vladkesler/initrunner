# Model Aliases & Runtime Model Override

Define semantic model aliases (`fast`, `smart`, `local`) in a global config file and override models at runtime without editing role YAML files.

## Quick start

1. Create `~/.initrunner/models.yaml`:

```yaml
aliases:
  fast: openai:gpt-4o-mini
  smart: anthropic:claude-sonnet-4-5-20250929
  local: ollama:llama3.2:latest
  cheap: groq:llama-3.3-70b-versatile
```

2. Use aliases anywhere:

```bash
# CLI --model flag
initrunner run role.yaml -p "Summarize this" --model fast
initrunner run --model smart
initrunner run role.yaml --serve --model local

# Environment variable
export INITRUNNER_MODEL=fast
initrunner run role.yaml -p "Summarize this"

# In role.yaml (provider becomes optional)
spec:
  model:
    name: fast
```

## Alias file format

The alias file lives at `~/.initrunner/models.yaml` (or `$INITRUNNER_HOME/models.yaml`):

```yaml
aliases:
  <alias-name>: <provider>:<model-name>
```

Each alias target **must** contain at least one `:` separator. Additional colons stay in the model name (e.g. `ollama:llama3.2:latest` is valid — provider is `ollama`, model is `llama3.2:latest`).

Invalid alias targets (missing `:`) are skipped with a warning.

If the file is missing, empty, or unparseable, no aliases are loaded and everything works via explicit `provider:model` strings as before.

## Runtime model override

The `--model` flag (or `INITRUNNER_MODEL` env var) overrides the model defined in the role file. Available on these commands:

| Command | Flag | Env var |
|---------|------|---------|
| `run` | `--model` | `INITRUNNER_MODEL` |
| `run --daemon` | `--model` | `INITRUNNER_MODEL` |
| `run --serve` | `--model` | `INITRUNNER_MODEL` |
| `test` | `--model` | `INITRUNNER_MODEL` |
| `run` (ephemeral) | `--model` | `INITRUNNER_MODEL` |

The flag accepts either an alias name or an explicit `provider:model` string:

```bash
# Alias
initrunner run role.yaml -p "hello" --model fast

# Explicit provider:model
initrunner run role.yaml -p "hello" --model openai:gpt-4o
```

When the override is applied, `temperature` and `max_tokens` from the original role config are preserved. If the provider changes, `base_url` and `api_key_env` are cleared (since they're typically provider-specific).

## Precedence

Model resolution follows this order (highest to lowest):

1. `--model` CLI flag / `INITRUNNER_MODEL` env var
2. Role YAML `spec.model` (with alias resolution)
3. `run.yaml` defaults (ephemeral mode only)
4. Auto-detection (ephemeral mode only)

The `--dry-run` flag operates at a different layer: the agent is built with the real model (alias/override applied), then `TestModel` replaces it at runner execution time.

## Role YAML aliases

When `provider` is omitted (or empty) in a role YAML, the `name` field is treated as either:

- An alias (looked up in `models.yaml`)
- An inline `provider:model` string (split on first colon)

```yaml
# Using an alias — provider is resolved from models.yaml
spec:
  model:
    name: fast
    temperature: 0.3

# Using inline provider:model — no alias lookup needed
spec:
  model:
    name: openai:gpt-4o-mini
    temperature: 0.3

# Explicit provider — no alias resolution, "fast" is the model name
spec:
  model:
    provider: openai
    name: fast
```

If `provider` is explicitly set, no alias resolution occurs — the `name` is used as-is.

## Ephemeral run aliases

The `run` command's `--model` flag and `run.yaml` `model` field both support aliases:

```bash
# CLI
initrunner run --model fast

# run.yaml
model: fast
```

When an alias resolves to `provider:model`, the provider is extracted automatically -- you don't need to specify `--provider` separately.

## Edge cases

| Scenario | Behavior |
|----------|----------|
| Alias not found, no colon in name | Error: "Could not resolve provider" |
| `--model` + `--dry-run` | Agent built with override model, then TestModel used at execution |
| `--model openai:gpt-4o` (explicit) | Parsed directly, no alias lookup |
| `--model ollama:llama3.2:latest` | Split on first colon: provider=`ollama`, name=`llama3.2:latest` |
| Role YAML `name: fast` with explicit `provider: openai` | Provider already set — no alias resolution, model named "fast" on OpenAI |
| Missing/empty `models.yaml` | No aliases — everything works via explicit `provider:model` |
| Compose mode | Not affected — each service uses its own role file |
| Alias-dependent role files | Machine-local; may fail on systems without matching `models.yaml` |
