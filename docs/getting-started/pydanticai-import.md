# Importing PydanticAI Agents

Convert existing PydanticAI Python agents into InitRunner `role.yaml` files via the CLI or the dashboard.

## Before / After

### Before: PydanticAI script

```python
# weather_agent.py
import httpx
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.settings import ModelSettings


class WeatherReport(BaseModel):
    city: str
    temperature_f: float
    condition: str
    summary: str


agent = Agent(
    "openai:gpt-4o-mini",
    output_type=WeatherReport,
    system_prompt="You are a weather assistant. Use the provided tools to fetch real weather data, then return a structured report.",
    model_settings=ModelSettings(temperature=0.1),
)


@agent.tool
async def get_weather(ctx: RunContext[None], city: str) -> str:
    """Fetch current weather for a city from wttr.in."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://wttr.in/{city}?format=j1", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        current = data["current_condition"][0]
        return (
            f"City: {city}, "
            f"Temp: {current['temp_F']}F, "
            f"Condition: {current['weatherDesc'][0]['value']}"
        )


@agent.tool_plain
def fahrenheit_to_celsius(temp_f: float) -> str:
    """Convert Fahrenheit to Celsius."""
    celsius = (temp_f - 32) * 5 / 9
    return f"{temp_f}F = {celsius:.1f}C"
```

### Import it

```bash
initrunner new --pydantic-ai weather_agent.py
```

### After: InitRunner role + sidecar

Two files are generated -- a declarative `role.yaml` and a `weather_agent_tools.py` sidecar with the extracted tool functions.

```yaml
# weather-bot.yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: weather-assistant
  spec_version: 2
spec:
  role: >-
    You are a weather assistant. Use the provided tools to fetch real weather
    data, then return a structured weather report.
  model:
    provider: openai
    name: gpt-4o-mini
  output:
    type: json_schema
    schema:
      type: object
      additionalProperties: false
      properties:
        city:
          type: string
        temperature_f:
          type: number
        condition:
          type: string
        summary:
          type: string
      required:
        - city
        - temperature_f
        - condition
        - summary
  tools:
    - type: custom
      module: weather_bot_tools
```

```python
# weather_bot_tools.py (generated)
"""Custom tools extracted from PydanticAI agent."""

import httpx
from pydantic import BaseModel


async def get_weather(city: str) -> str:
    """Fetch current weather for a city from wttr.in."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://wttr.in/{city}?format=j1", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        current = data["current_condition"][0]
        return (
            f"City: {city}, "
            f"Temp: {current['temp_F']}F, "
            f"Condition: {current['weatherDesc'][0]['value']}"
        )


def fahrenheit_to_celsius(temp_f: float) -> str:
    """Convert Fahrenheit to Celsius."""
    celsius = (temp_f - 32) * 5 / 9
    return f"{temp_f}F = {celsius:.1f}C"
```

What changed:

- `Agent("openai:gpt-4o-mini")` became `spec.model: {provider: openai, name: gpt-4o-mini}`
- `system_prompt=` became `spec.role`
- `ModelSettings(temperature=0.1)` became `spec.model.temperature` (omitted since 0.1 is the default)
- `output_type=WeatherReport` became `spec.output` with the full JSON schema
- `@agent.tool` and `@agent.tool_plain` decorators were stripped
- `ctx: RunContext[None]` was removed from the async tool signature
- `pydantic_ai` imports were filtered out; `httpx` and `pydantic` imports were kept
- The sidecar module name was derived from the output YAML filename

### Run it

```
$ initrunner run weather-bot.yaml -p "What's the weather in Tokyo?"
{"city":"Tokyo","temperature_f":58.0,"condition":"Light rain","summary":"The current weather in Tokyo is 58F with light rain."}
```

## How It Works

The converter uses a two-phase approach:

1. **AST extraction (deterministic)** -- parses the Python source and extracts model config, prompts, tools, output type, usage limits, and unsupported features into a structured intermediate representation. No LLM calls.

2. **LLM normalization** -- sends the structured summary to an LLM that produces minimal, valid InitRunner YAML following the role schema.

## Mapping Reference

| PydanticAI Construct | InitRunner role.yaml |
|---|---|
| `Agent("openai:gpt-5")` | `spec.model: {provider: openai, name: gpt-5}` |
| `Agent(OpenAIModel("gpt-5"))` | `spec.model: {provider: openai, name: gpt-5}` |
| `system_prompt="..."` | `spec.role` |
| `instructions="..."` | `spec.role` (combined with system_prompt) |
| `@agent.system_prompt` decorator | `spec.role` (static return extracted) |
| `@agent.instructions` decorator | `spec.role` (static return extracted) |
| `ModelSettings(temperature=0.7)` | `spec.model.temperature: 0.7` |
| `ModelSettings(max_tokens=4096)` | `spec.model.max_tokens: 4096` |
| `output_type=MySchema` | `spec.output: {type: json_schema}` |
| `output_type=NativeOutput(MySchema)` | `spec.output: {type: json_schema}` |
| `@agent.tool` / `@agent.tool_plain` | `type: custom` + sidecar module |
| `FunctionToolset` tools | `type: custom` + sidecar module |
| `tools=[func]` kwarg | `type: custom` + sidecar module |
| `UsageLimits(request_limit=10)` | `spec.guardrails.max_request_limit: 10` |

## Tool Extraction and RunContext

PydanticAI tools often take a `RunContext[Deps]` first parameter for dependency injection. InitRunner manages tool context differently, so the converter:

1. **Strips the `RunContext` parameter** from the function signature
2. **Checks if the parameter name is referenced in the body** -- if `ctx.deps` or similar is used, it inserts a `# TODO` comment and sets a warning

Tools that only use `RunContext` for typing (not in the body) convert cleanly. Tools that depend on `ctx.deps` need manual adjustment.

## Supported Model Classes

The converter recognizes these PydanticAI model classes and maps them to InitRunner providers:

| Model Class | Provider |
|---|---|
| `OpenAIModel`, `OpenAIChatModel`, `OpenAIResponsesModel` | `openai` |
| `AnthropicModel` | `anthropic` |
| `GeminiModel`, `GoogleModel` | `google` |
| `GroqModel` | `groq` |
| `MistralModel` | `mistral` |
| `BedrockConverseModel` | `bedrock` |
| `CohereModel` | `cohere` |
| `XAIModel` | `xai` |

## Unsupported Features

These PydanticAI features are detected and produce warnings:

| Feature | Recommendation |
|---|---|
| `pydantic_graph` | Use InitRunner `flow.yaml` |
| `logfire` / `instrument=` | Use `spec.observability` |
| `MCPServerStdio` / `MCPServerHTTP` | Use `type: mcp` in tools |
| `builtin_tools=[...]` | Add equivalent InitRunner tools manually |
| `@agent.output_validator` | Not portable -- validate in tool logic |
| `TextOutput` / `StructuredDict` output types | Not directly portable |
| Dynamic `@agent.instructions` with `RunContext` | Warning with function source |

## Multiple Agents

If the file contains multiple `Agent()` assignments, the converter imports the first one (in source order) and warns about skipped agents.

## CLI Options

```bash
initrunner new --pydantic-ai <file> [options]

Options:
  --provider TEXT    Model provider (auto-detected if omitted)
  --model TEXT       Model name
  --output PATH     Output file path (default: role.yaml)
  --force            Overwrite existing file
  --no-refine        Skip interactive refinement loop
```

## Dashboard

In the dashboard agent builder:

1. Click the **Import** card
2. Toggle the framework pill to **PydanticAI**
3. Paste your agent source code into the textarea
4. Click **Import**

The dashboard uses the same two-phase pipeline (AST extraction + LLM normalization) and shows import warnings inline in the editor. Switching between LangChain and PydanticAI preserves each textarea's content independently.
