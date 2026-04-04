# Importing LangChain Agents

Convert existing LangChain Python agents into InitRunner `role.yaml` files via the CLI or the dashboard.

## Quick Example

Given a LangChain agent:

```python
# my_agent.py
from langchain.agents import create_agent
from langchain.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return f"Sunny in {city}"

agent = create_agent(
    model="anthropic:claude-sonnet-4-6",
    tools=[get_weather],
    system_prompt="You are a helpful weather assistant.",
)
```

Import it:

```bash
initrunner new --langchain my_agent.py
```

This produces two files:

- **`role.yaml`** -- the InitRunner agent definition
- **`role_tools.py`** -- extracted custom tool functions

```yaml
# role.yaml (generated)
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: weather-bot
  description: Imported from LangChain weather agent
  spec_version: 2
spec:
  role: You are a helpful weather assistant.
  model:
    provider: anthropic
    name: claude-sonnet-4-6
  tools:
    - type: custom
      module: role_tools
```

```python
# role_tools.py (generated)
"""Custom tools extracted from LangChain agent."""

def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return f"Sunny in {city}"
```

Run it immediately:

```bash
initrunner run role.yaml -p "What's the weather in Tokyo?"
```

## How It Works

The importer uses a two-phase approach:

1. **AST extraction** -- Parses your Python file deterministically (no LLM) to extract model config, system prompt, tools, agent kind, output schema, and guardrails.
2. **LLM normalization** -- Sends the extracted structure to an LLM that produces minimal, valid InitRunner YAML.

After import, the standard refinement loop runs so you can adjust the result interactively.

## What Gets Imported

| LangChain Construct | InitRunner Equivalent |
|---|---|
| `create_agent("openai:gpt-5")` | `spec.model: {provider: openai, name: gpt-5}` |
| `ChatAnthropic(model="...", temperature=0.7)` | `spec.model: {provider: anthropic, name: ..., temperature: 0.7}` |
| `init_chat_model("...", max_tokens=1000)` | `spec.model: {max_tokens: 1000}` |
| `system_prompt="..."` | `spec.role: \|` |
| `@tool` functions | `type: custom` + sidecar `.py` module |
| `DuckDuckGoSearchRun()` | `type: search` |
| `PythonREPLTool()` | `type: python` |
| `ShellTool()` | `type: shell` |
| `ReadFileTool()` / `WriteFileTool()` | `type: filesystem` |
| `create_agent` (ReAct pattern) | `spec.reasoning: {pattern: react}` |
| `CallLimitMiddleware(max_calls=15)` | `spec.guardrails: {max_iterations: 15}` |
| `response_format=MySchema` | `spec.output: {type: json_schema}` |
| Custom `AgentState` subclass | Noted in import warnings |

## Custom Tools

`@tool`-decorated functions are extracted into a sidecar Python module placed next to the YAML file. The `@tool` decorator is stripped (InitRunner discovers functions by name, not decorator), and non-LangChain imports from the original file are carried over.

The sidecar filename is derived from the YAML output filename. Hyphens are converted to underscores so the module name is a valid Python identifier:

| Output YAML | Sidecar Module |
|---|---|
| `role.yaml` | `role_tools.py` |
| `weather-agent.yaml` | `weather_agent_tools.py` |
| `calc-agent.yaml` | `calc_agent_tools.py` |

InitRunner's custom tool loader auto-discovers all public functions in the module. No need to list individual functions in the YAML.

### Sandbox Validation

If extracted tools import modules blocked by the default sandbox policy (`os`, `subprocess`, `shutil`, `sys`, `socket`, etc.), you'll see a warning:

```
Import warnings:
  - Sidecar tool module imports 'os' which is blocked by default sandbox policy.
    Review security.sandbox.blocked_custom_modules.
```

The import still succeeds -- you decide whether to adjust the tool code or relax the sandbox in your role's `security` block.

## Known Tool Mapping

The importer recognizes common LangChain tool classes and maps them to built-in InitRunner tool types:

| LangChain Class | InitRunner Type |
|---|---|
| `DuckDuckGoSearchRun`, `DuckDuckGoSearchResults` | `search` |
| `TavilySearchResults`, `BraveSearchResults` | `search` |
| `WikipediaQueryRun` | `web_reader` |
| `PythonREPLTool`, `PythonAstREPLTool` | `python` |
| `ShellTool` | `shell` |
| `ReadFileTool`, `WriteFileTool`, `ListDirectoryTool` | `filesystem` |
| `RequestsGetTool`, `RequestsPostTool` | `http` |

Unrecognized tool classes produce a warning and are skipped. Add them manually via `type: custom` or the appropriate built-in type.

## What Is Not Imported

Some LangChain features have no direct equivalent and produce explicit warnings instead of silent conversions:

| Feature | Warning | Recommendation |
|---|---|---|
| `ConversationBufferMemory` | "LangChain memory not imported" | Configure `spec.memory` manually |
| LCEL pipelines (`prompt \| model \| parser`) | "LCEL pipeline detected but not importable" | Describe chain logic in `spec.role` |
| LangGraph state machines | "LangGraph state machine detected" | Use `flow.yaml` for orchestration |
| Retrievers / VectorStores | "Retriever/VectorStore detected" | Configure `spec.ingest` for RAG |
| Callback handlers | "LangChain callbacks not imported" | Use `spec.observability` for tracing |
| `HumanInTheLoopMiddleware` | "Human-in-the-loop middleware not imported" | Use `confirmation: true` on tool permissions |

These warnings appear in both the CLI output and the dashboard's editor screen. They are never silently swallowed.

## Dashboard

The dashboard builder supports LangChain import as a seed mode. Navigate to **Agents > New** and select the **Import** card.

1. Paste your LangChain Python source into the code textarea
2. Select a provider/model (used by the builder LLM, not your agent)
3. Click **Import**
4. Review the generated YAML in the editor -- import warnings appear in an amber banner above the editor
5. Click **Save** -- both the YAML and sidecar tool module are written

The dashboard carries the sidecar source through the API payloads, so no server-side state is needed between seed and save.

## CLI Options

```bash
initrunner new --langchain <file> [options]
```

| Option | Description |
|---|---|
| `--langchain <file>` | Path to LangChain Python file |
| `--provider <name>` | Model provider for the builder LLM (auto-detected if omitted) |
| `--model <name>` | Model name for the builder LLM |
| `--output <path>` | Output file path (default: `role.yaml`) |
| `--force` | Overwrite existing files |
| `--no-refine` | Skip the interactive refinement loop |

`--langchain` is mutually exclusive with other seed modes (`--blank`, `--template`, `--from`, description argument).

## Refining After Import

Unless `--no-refine` is passed, the importer drops you into the standard refinement loop where you can adjust the generated YAML:

```
Refine (empty to save, "quit" to discard): add memory support
```

This is useful for adding InitRunner-specific features (memory, triggers, autonomy, ingestion) that have no LangChain equivalent.

## Scope

The importer targets **classic LangChain agents** built with `create_agent`, `init_chat_model`, or provider-specific chat model classes. It handles `@tool` functions, known tool classes, structured output, and basic middleware.

LangGraph workflows, LCEL chains, multi-agent handoff patterns, and advanced streaming configurations are out of scope for automatic conversion. These require manual migration using [flow.yaml](../orchestration/delegation.md) or [team mode](../orchestration/team_mode.md).

## See Also

- [CLI Reference](cli.md) -- full command reference including `--langchain` flag
- [Dashboard](../interfaces/dashboard.md) -- web UI for agent creation and management
- [Tool Creation Guide](../agents/tool_creation.md) -- creating custom tools
- [Choosing Features](choosing-features.md) -- goal-to-config mapping
- [Multi-agent Guide](../orchestration/multi-agent-guide.md) -- migration path for LangGraph workflows
