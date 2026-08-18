# Structured Output

InitRunner's structured output feature lets agents return validated JSON instead of free-form text. Define a JSON Schema in `output` and the agent's response is guaranteed to match your schema — parsed, validated, and returned as JSON.

This is useful for pipelines, automation, and any scenario where downstream code needs to consume agent output programmatically.

## Quick Start

```yaml
name: invoice-classifier
description: Classifies invoices and extracts structured data
model:
  provider: openai
  name: gpt-5-mini
  temperature: 0.0
prompt: |
  You are an invoice classifier. Given a description of an invoice,
  extract the relevant fields and return structured JSON.
output:
  type: json_schema
  schema:
    type: object
    properties:
      status:
        type: string
        enum: [approved, rejected, needs_review]
      amount:
        type: number
        description: Invoice amount in USD
      vendor:
        type: string
    required: [status, amount, vendor]
```

```bash
initrunner run invoice-classifier.yaml -p "Acme Corp invoice for $250 for office supplies"
# → {"status": "approved", "amount": 250.0, "vendor": "Acme Corp"}
```

## Configuration

Structured output is configured in the `output` section:

```yaml
output:
  type: json_schema        # "text" (default) or "json_schema"
  mode: auto               # how structured output is requested (see below)
  schema: { ... }          # inline JSON Schema (mutually exclusive with schema_file)
  schema_file: schema.json # path to external JSON Schema file
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `str` | `"text"` | Output type. `"text"` for free-form text, `"json_schema"` for validated JSON. |
| `mode` | `str` | `"auto"` | Strategy used to obtain structured output. One of `auto`, `tool`, `native`, `prompted`, `text`. See [Output Modes](#output-modes). |
| `schema` | `dict` | `null` | Inline JSON Schema definition. Required when `type` is `json_schema` (unless `schema_file` is set). |
| `schema_file` | `str` | `null` | Path to an external JSON Schema file. Relative paths are resolved from the role file's directory. |

When `type` is `json_schema`, exactly one of `schema` or `schema_file` must be provided.

## Output Modes

`mode` controls how InitRunner asks the model for structured output. It maps onto PydanticAI's output markers, which decide whether the schema is enforced through a tool call, the provider's native structured-output API, or a prompt instruction.

| Mode | Behavior | When to use |
|------|----------|-------------|
| `auto` (default) | Defers to PydanticAI, which picks a strategy from the model's `ModelProfile.default_structured_output_mode` (typically `tool`). | The safe default. Works with every provider and matches prior InitRunner behavior. |
| `tool` | Forces structured output through a tool call, regardless of model capabilities. | Maximum compatibility, or to pin the strategy so it does not change if you switch models. |
| `native` | Uses the provider's native structured-output API (for example OpenAI Structured Outputs). Faster and cheaper on models that support it. | Models with native JSON-schema support and a high structured-output volume. |
| `prompted` | Describes the schema in the prompt and asks the model to reply with matching JSON. | A fallback for providers that lack native or tool-based structured output. |
| `text` | Plain unstructured text. | Only valid with `type: text`; this is the implicit mode for text roles. |

Validation rules:

- `mode: native`, `tool`, and `prompted` require `type: json_schema`.
- `mode: text` requires `type: text`.
- With `type: text`, only `auto` or `text` are accepted.

```yaml
output:
  type: json_schema
  mode: native             # opt into the provider's native structured-output API
  schema:
    type: object
    properties:
      status: { type: string, enum: [approved, rejected] }
    required: [status]
```

When a role uses a `FallbackModel` (a primary plus fallbacks across providers), a pinned `native` mode applies to every model in the chain. If a fallback provider does not support native structured output, that request fails over to the next model rather than silently degrading. Pin `tool` (or keep `auto`) for mixed-provider fallback chains.

## Inline Schema

Define the schema directly in your role YAML. The supported JSON Schema subset:

| JSON Schema Type | Python Type | Notes |
|-----------------|-------------|-------|
| `string` | `str` | Plain string |
| `string` + `enum` | `Literal[...]` | Constrained to listed values |
| `number` | `float` | Floating-point number |
| `integer` | `int` | Integer number |
| `boolean` | `bool` | True/false |
| `object` | nested `BaseModel` | Recursive — nested objects become nested models |
| `array` | `list[ItemType]` | Item type resolved from `items` schema |

### Schema keywords

- **`properties`** — defines the fields of an object
- **`required`** — list of field names that must be present (non-required fields become `Optional` with `None` default)
- **`description`** — field-level documentation passed to the model
- **`enum`** — constrains a string field to specific values
- **`items`** — defines the element type for arrays

### Example with nested objects and arrays

```yaml
output:
  type: json_schema
  schema:
    type: object
    properties:
      title:
        type: string
        description: Report title
      sections:
        type: array
        items:
          type: object
          properties:
            heading:
              type: string
            body:
              type: string
          required: [heading, body]
      metadata:
        type: object
        properties:
          author:
            type: string
          tags:
            type: array
            items:
              type: string
    required: [title, sections]
```

## External Schema File

For larger schemas, use `schema_file` to reference a separate JSON file:

```yaml
output:
  type: json_schema
  schema_file: schemas/invoice.json
```

The file must contain a valid JSON Schema object. Relative paths are resolved from the role YAML file's directory. Absolute paths are used as-is.

```json
{
  "type": "object",
  "properties": {
    "status": { "type": "string", "enum": ["approved", "rejected"] },
    "amount": { "type": "number" }
  },
  "required": ["status", "amount"]
}
```

## Output Precedence

The role-level `output` config applies to every run of the role. No YAML key overrides it per flow step or per composed child. `AgentChild` and `ThenConfig` (`initrunner/agent/schema/v3.py`) are `extra="forbid"`, so adding `output` (or `output_format`) to a child under `agents:` fails validation with `extra_forbidden`. On a legacy `flow.yaml` agent block the key is silently ignored instead.

Programmatic callers can override the role's output type by passing an explicit `output_type` to `build_agent()` (`initrunner/agent/loader.py`). It takes precedence over the type resolved from the role's `output` block.

The CLI's `-f/--format` flag (`auto`, `json`, `text`, `rich`) controls only how the result is rendered. It does not change the agent's output type.

## Streaming Structured Output

Structured output roles stream just like text roles, but the signal you receive is different: you get progressively-validated partial models, not text deltas.

- `initrunner run role.yaml -p "..."` prints the final validated JSON.
- The dashboard SSE stream emits `partial_output` frames whose `data` field is the latest partial dict as the model builds the object. Text-mode roles continue to emit `token` frames.
- Programmatic callers pass `on_partial=<callable>` to `execute_run_stream_sync` / `execute_run_stream_async`. The callback receives each partial (a Pydantic model instance) as it grows toward the final validated object.

The forbid that previously raised `ValueError("Streaming is not supported with structured output")` was removed once `StreamedRunResultSync.stream_output()` became the canonical source of progressive partials.

## Example

See [`examples/roles/invoice-classifier.yaml`](../../examples/roles/invoice-classifier.yaml) for a complete working example that classifies invoices into structured categories with status, amount, vendor, category, and reason fields.

```bash
initrunner run examples/roles/invoice-classifier.yaml \
  -p "AWS bill for $8,500 for cloud hosting services, monthly recurring"
```
