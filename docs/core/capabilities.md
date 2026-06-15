# Capabilities

Capabilities are PydanticAI's composable extension point for cross-cutting agent behavior. A capability bundles tools, lifecycle hooks, instructions, and model settings into a single unit that attaches to an agent. InitRunner exposes PydanticAI's built-in capabilities via `spec.capabilities` in role YAML.

## YAML Syntax

Capabilities use PydanticAI's native spec format with three forms:

```yaml
spec:
  capabilities:
    # Bare string (no arguments)
    - WebSearch

    # Single positional argument
    - Thinking: high

    # Keyword arguments
    - MCP:
        url: https://mcp.example.com
    - WebSearch:
        allowed_domains: [docs.python.org, pydantic.dev]
        search_context_size: high
```

Names are CamelCase class names matching PydanticAI's capability registry. For custom pack-local capabilities, see [Custom Capabilities](#custom-capabilities-pack-bundled) below.

## Supported Capabilities

| Capability | Arguments | Purpose |
|---|---|---|
| `Thinking` | `effort`: `minimal`, `low`, `medium`, `high`, `xhigh` | Enable model-level extended thinking |
| `WebSearch` | `allowed_domains`, `blocked_domains`, `search_context_size`, `max_uses` | Web search with provider-adaptive fallback |
| `WebFetch` | `allowed_domains`, `blocked_domains`, `max_uses` | URL fetching with local fallback |
| `ImageGeneration` | `fallback_model`, `image_model`, `quality`, `size`, `output_format`, `action`, `background`, `moderation` | Provider-native image generation (OpenAI Responses, Google) with optional `fallback_model` delegation on providers that lack it |
| `MCP` | `url` (required), `id`, `authorization_token`, `headers`, `allowed_tools` | PydanticAI-native MCP server connection |
| `BuiltinTool` | `tool` (builtin tool spec) | Register individual builtin tools |
| `PrefixTools` | `prefix`, `capability` (nested spec) | Namespace tool names to avoid conflicts |

## Examples

### Extended thinking

```yaml
spec:
  capabilities:
    - Thinking: high
```

### Web search with domain filtering

```yaml
spec:
  capabilities:
    - WebSearch:
        allowed_domains: [docs.python.org, github.com]
        search_context_size: medium
```

### Image generation with fallback

`ImageGeneration` uses the provider's native image tool on OpenAI Responses and Google. On a provider that has no native image tool, set `fallback_model` to delegate generation to a subagent running that model, so the same role works across providers without code:

```yaml
spec:
  model:
    provider: anthropic          # no native image tool
    name: claude-sonnet-4-5-20250929
  capabilities:
    - ImageGeneration:
        fallback_model: openai:gpt-5   # delegate image gen here
        size: "1024x1024"
        quality: high
```

This is the native PydanticAI capability. It is distinct from the `image_gen` **tool** (`spec.tools`), which wraps the OpenAI / Stability image APIs as an explicit callable that saves files to disk. Declaring both at once is rejected; pick the capability for in-conversation generation, the tool for file-output workflows.

### Remote MCP server

```yaml
spec:
  capabilities:
    - MCP:
        url: https://mcp.example.com/api
        authorization_token: ${MCP_TOKEN}
```

### Prefixed capabilities (namespace tools)

```yaml
spec:
  capabilities:
    - PrefixTools:
        prefix: search
        capability:
          WebSearch:
            allowed_domains: [example.com]
```

### Combined

```yaml
spec:
  capabilities:
    - Thinking: high
    - WebSearch:
        allowed_domains: [docs.python.org]
    - MCP:
        url: https://tools.example.com/mcp
```

## Guardrail Capabilities

InitRunner auto-constructs an `InputGuardCapability` from `spec.security.content` when any input validation is configured (blocked patterns, profanity filter, LLM classifier, or non-default max prompt length). This capability fires in `before_run` -- before the agent starts -- and raises `ContentBlockedError` to abort the run when the user prompt violates the content policy.

### How it works

The `InputGuardCapability` delegates to the same `validate_input_async()` function used by the executor. It uses `ctx.model` as the LLM classifier model override and `ctx.prompt` to extract the user's text. When the API server has already validated the input (pre-flight HTTP 400 check), it passes `metadata={"input_validated": True}` to skip double-validation.

### What stays in the executor

- **Output validation** -- operates on serialized strings after `_process_agent_output()` and handles both streaming and non-streaming paths
- **PII redaction** -- applies only to the audit trail (not user-visible output)
- **Timeout** -- wall-clock timeout wraps the entire run

### Example

Input validation fires automatically from `security.content` config:

```yaml
spec:
  security:
    content:
      blocked_input_patterns:
        - "ignore.*instructions"
        - "reveal.*system.*prompt"
      profanity_filter: true
      max_prompt_length: 10000
```

No `capabilities:` entry is needed -- the `InputGuardCapability` is auto-constructed from the security config and prepended to any user-declared capabilities.

## Relationship to Existing Features

### Capabilities vs Tools

Capabilities are PydanticAI's native abstraction. InitRunner tools (`spec.tools`) go through the tool registry and builder pipeline. Both can coexist. Use native capabilities for PydanticAI built-ins (thinking, web search, MCP), custom capabilities for cross-cutting behavior that combines hooks + tools + instructions, and tools for InitRunner-managed integrations (filesystem, sql, shell, etc.).

### Thinking vs Reasoning

The `Thinking` capability controls **model-level extended thinking** (how much the LLM reasons internally before responding). InitRunner's `spec.reasoning` controls **orchestration patterns** (react, reflexion, todo_driven, plan_execute) that structure multi-step agent runs. These are orthogonal.

If both are declared, InitRunner logs a warning since the combination may be confusing, but both remain active.

### MCP Capability vs MCP Tool

The `MCP` capability is PydanticAI's native MCP integration (`pydantic_ai.capabilities.MCP`). InitRunner's `type: mcp` tool goes through the tool registry and supports stdio/sse/streamable-http transports with tool filtering.

Both can coexist. InitRunner logs a warning when both are present to flag potential duplication.

## Dashboard

Agents with capabilities show:

- A **capabilities** dot in the capability glyph (2x4 grid)
- An **Enhanced** filter in the capability filter bar
- A **Capabilities** section in the agent detail config panel listing each capability's type and configuration
