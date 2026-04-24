# Structured Output

InitRunner's structured output feature lets agents return validated JSON instead of free-form text. Define a JSON Schema in `spec.output` and the agent's response is guaranteed to match your schema — parsed, validated, and returned as JSON.

This is useful for pipelines, automation, and any scenario where downstream code needs to consume agent output programmatically.

## Quick Start

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: invoice-classifier
  description: Classifies invoices and extracts structured data
spec:
  role: |
    You are an invoice classifier. Given a description of an invoice,
    extract the relevant fields and return structured JSON.
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.0
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

Structured output is configured in the `spec.output` section:

```yaml
spec:
  output:
    type: json_schema        # "text" (default) or "json_schema"
    schema: { ... }          # inline JSON Schema (mutually exclusive with schema_file)
    schema_file: schema.json # path to external JSON Schema file
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `str` | `"text"` | Output type. `"text"` for free-form text, `"json_schema"` for validated JSON. |
| `schema` | `dict` | `null` | Inline JSON Schema definition. Required when `type` is `json_schema` (unless `schema_file` is set). |
| `schema_file` | `str` | `null` | Path to an external JSON Schema file. Relative paths are resolved from the role file's directory. |

When `type` is `json_schema`, exactly one of `schema` or `schema_file` must be provided.

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
spec:
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
spec:
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

## Pipeline Precedence

When using flow pipelines, a pipeline step's `output_format` overrides the role-level `spec.output` config. This allows the same role to produce different output formats depending on the pipeline context.

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
