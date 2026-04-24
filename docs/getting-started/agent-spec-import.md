# Importing PydanticAI Agent Specs

PydanticAI 1.71 added [Agent Spec](https://pydantic.dev/docs/ai/core-concepts/agent-spec): a declarative YAML/JSON format for agents, loaded via `Agent.from_file()` / `Agent.from_spec()`. InitRunner can import these directly and export back to the same format.

## Importing

```bash
initrunner new greeter --agent-spec ./greeter.agent-spec.yaml
```

Given this PydanticAI agent-spec file:

```yaml
# greeter.agent-spec.yaml
model: anthropic:claude-sonnet-4-5
name: greeter
description: Friendly greeter with templated instructions.
instructions: "You are greeting {{name}} from {{city}}."
deps_schema:
  type: object
  properties:
    name: {type: string}
    city: {type: string}
  required: [name, city]
retries: 3
end_strategy: exhaustive
tool_timeout: 15.0
```

InitRunner writes a valid `role.yaml`:

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: greeter
  description: Friendly greeter with templated instructions.
spec:
  role: "You are greeting {{name}} from {{city}}."
  model:
    provider: anthropic
    name: claude-sonnet-4-5
  execution:
    retries: 3
    end_strategy: exhaustive
    tool_timeout_seconds: 15.0
  deps_schema:
    type: object
    properties:
      name: {type: string}
      city: {type: string}
    required: [name, city]
```

### Field mapping

| PydanticAI Agent Spec | InitRunner role.yaml |
|---|---|
| `model` | `spec.model` (parses `provider:name`) |
| `instructions` | `spec.role` |
| `name` / `metadata.name` / filename stem | `metadata.name` (in that precedence) |
| `description` | `metadata.description` |
| `model_settings.max_tokens` / `temperature` | `spec.model.max_tokens` / `temperature` |
| `capabilities` | `spec.capabilities` (same `NamedSpec` format) |
| `retries`, `output_retries`, `end_strategy`, `tool_timeout` | `spec.execution.*` |
| `deps_schema` | `spec.deps_schema` (verbatim) |
| `output_schema` | `spec.output` with `type: json_schema` |

Dropped with a warning: `instrument` (use `spec.observability` instead), `json_schema_path` (InitRunner doesn't need the companion schema path), and any `model_settings` keys beyond `max_tokens` / `temperature`.

## Running with template variables

If the role prompt contains `{{var}}` placeholders, declare them in `spec.deps_schema` (flat scalar object: `string`, `integer`, `number`, `boolean`) and supply values at run time:

```bash
initrunner run greeter/role.yaml "be polite" --var name=Alice --var city=Berlin
```

`--var` is repeatable. Missing required variables raise an error at run time; undeclared variables raise at load time. Rendering happens through a dynamic system-prompt hook so the raw `{{...}}` never reaches the model.

**v1 scope**: `deps_schema` is enforced as a flat-scalar object. Nested objects, arrays, `$ref`, and `oneOf` raise `RoleLoadError`. The `--var` flag is wired into single-shot `initrunner run` only; interactive, autonomous, and daemon modes do not thread variables yet.

## Exporting

```bash
initrunner export agent-spec ./greeter/role.yaml
```

Writes `greeter.agent-spec.yaml` plus a companion JSON Schema (`.schema.json`) in the same directory. The schema covers only the overlap between our role schema and PydanticAI's Agent Spec -- fields like triggers, ingest, memory, skills, sinks, autonomy, reasoning, guardrails, and security are dropped (the CLI prints a warning table showing which ones). This is lossy by design: Agent Spec models a smaller surface area than role.yaml.

Round-trip validation:

```bash
uv run python -c "
from pydantic_ai.agent.spec import AgentSpec
import yaml
AgentSpec.model_validate(yaml.safe_load(open('greeter.agent-spec.yaml')))
"
```

Passes on any export -- the emitted spec is always upstream-valid, minus `pydantic-handlebars` for templated instructions (that's an optional extra on the upstream package).

## When to use this

Reach for Agent Spec import when you're starting from someone else's PydanticAI YAML and want to adopt InitRunner's triggers, memory, RAG, or sandbox on top of it. Reach for export when you need to hand off to a pure-PydanticAI runtime -- CI, a non-InitRunner service, or a colleague who doesn't use InitRunner yet.

For tool-heavy custom agents, `--pydantic-ai` (Python file) and `--langchain` give you richer imports. Agent Spec is the pure-declarative path.
