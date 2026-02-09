# Tool Creation Guide

This guide covers the four ways to extend InitRunner with tools: built-in tools (contributing to InitRunner itself), custom tools (Python modules), declarative API tools (YAML-only), and the plugin registry (distributable packages).

## Built-in Tools

Built-in tools ship with InitRunner. Each one lives in a single file and self-registers using the `@register_tool` decorator. Use this pattern when contributing a new tool to the InitRunner codebase itself. For external/third-party tools, use [Custom Tools](#custom-tools) or the [Plugin Registry](#plugin-registry) instead.

### Single-file pattern

A built-in tool is one Python file containing a config class, a builder function, and the `@register_tool` decorator:

```python
# initrunner/agent/tools/redis.py

from typing import Literal
from pydantic_ai.toolsets.function import FunctionToolset
from initrunner.agent.schema import ToolConfigBase
from initrunner.agent.tools._registry import register_tool, ToolBuildContext


class RedisToolConfig(ToolConfigBase):
    type: Literal["redis"] = "redis"
    host: str = "localhost"
    port: int = 6379

    def summary(self) -> str:
        return f"redis: {self.host}:{self.port}"


@register_tool("redis", RedisToolConfig)
def build_redis_toolset(config: RedisToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    toolset = FunctionToolset()

    @toolset.tool
    def redis_get(key: str) -> str:
        """Get a value from Redis."""
        import redis
        r = redis.Redis(host=config.host, port=config.port)
        return r.get(key) or ""

    return toolset
```

The tool is immediately available in role YAML as `type: redis` — no other files need editing.

Tools use [PydanticAI's FunctionToolset](https://ai.pydantic.dev/tools/) under the hood. The `@toolset.tool` decorator registers individual functions, and PydanticAI handles parameter schema generation from type annotations and docstrings.

### ToolConfigBase

All tool config classes inherit from `ToolConfigBase` (defined in `agent/schema.py`):

- **`type: str`** — discriminator field; use `Literal["your_type"]` with a matching default
- **`summary() -> str`** — human-readable description shown in validation output

### ToolBuildContext

Every builder receives a `ToolBuildContext` instance as its second argument:

| Field | Type | Description |
|-------|------|-------------|
| `role` | `RoleDefinition` | The full parsed role definition |
| `role_dir` | `Path \| None` | Directory containing the role YAML file |

### Auto-discovery

At first access, `_ensure_discovered()` imports every module under `initrunner/agent/tools/` via `pkgutil.iter_modules()`. Modules with `_`-prefixed names (like `_registry.py`) are skipped. Import errors are silently ignored so missing optional dependencies don't crash discovery.

### Legacy modules

Tool modules that live outside the `tools/` package (e.g. `agent/git_tools.py`, `agent/python_tools.py`) are listed in `_LEGACY_TOOL_MODULES` in `_registry.py` and imported during discovery alongside the package modules.

### Checklist

1. Create a file in `initrunner/agent/tools/` (e.g. `redis.py`)
2. Define a config class inheriting `ToolConfigBase` with a `Literal` type field
3. Decorate the builder function with `@register_tool("type_name", ConfigClass)`
4. Run `uv run pytest tests/ -v` to verify

---

## Custom Tools

Custom tools load Python functions from a module and register them as agent tools. Each function's name, docstring, and type annotations become the tool's name, description, and parameter schema.

### Scaffolding

```bash
initrunner init --template tool --name my_tools
```

This creates a `my_tools.py` file with example functions. Reference it in a role YAML:

```yaml
tools:
  - type: custom
    module: my_tools
```

### Single Function vs. Module Discovery

**Single function** — specify `function` to load exactly one tool:

```yaml
tools:
  - type: custom
    module: my_tools
    function: search_db
```

**Auto-discovery** — omit `function` to register all public callables in the module:

```yaml
tools:
  - type: custom
    module: my_tools
```

Auto-discovery scans the module with `dir()` and collects every object that is:

- A function (`inspect.isfunction`)
- Public (name does not start with `_`)
- Not a class, module, or builtin

If the module has no qualifying functions, loading fails with a clear error.

### Config Injection

The `config` dict in the YAML is passed to any function that declares a `tool_config` parameter. The parameter is stripped from the tool schema so the LLM never sees it.

```yaml
tools:
  - type: custom
    module: my_tools
    config:
      api_key: ${MY_API_KEY}
      base_url: https://api.example.com
```

```python
# my_tools.py

def search(query: str, tool_config: dict) -> str:
    """Search an external service."""
    api_key = tool_config["api_key"]
    base_url = tool_config["base_url"]
    # ... use api_key and base_url
    return results
```

The LLM sees `search(query: str) -> str` — only the `query` parameter is exposed.

Internally, config injection uses `functools.partial` to bind `tool_config`. PydanticAI resolves type hints against the original function while the partial supplies the config value.

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `module` | `str` | *(required)* | Python module path (e.g. `my_tools` or `pkg.utils`). Must be importable. |
| `function` | `str \| null` | `null` | Function name to load. `null` auto-discovers all public functions. |
| `config` | `dict` | `{}` | Config dict injected into functions that accept a `tool_config` parameter. |

### Writing Tool Functions

Rules for tool functions:

1. **Return `str`** — tool results are always strings.
2. **Use type annotations** — PydanticAI builds the parameter schema from annotations.
3. **Write a docstring** — it becomes the tool description the LLM reads.
4. **Keep it sync** — InitRunner uses sync execution. PydanticAI auto-wraps sync tools with `run_in_executor`.

```python
def get_weather(city: str, units: str = "metric") -> str:
    """Get current weather for a city.

    Args:
        city: City name (e.g. "London").
        units: Temperature units — "metric" or "imperial".
    """
    # implementation ...
    return f"Weather in {city}: 22°C, sunny"
```

### Error Handling

| Scenario | Error Message |
|----------|---------------|
| Module not found | `Could not load module 'xyz': missing dependency 'xyz'. Install it with: pip install xyz` |
| Function not found | `Function 'foo' not found in module 'bar'` |
| No public functions (auto-discover) | `No public callable functions found in module 'bar'. Add public functions or specify 'function' explicitly.` |

### Security

Custom tools go through the same sandbox checks as before:

- **AST import analysis** validates imports against the blocklist/allowlist in `security.tools`.
- **PEP 578 audit hooks** (when `audit_hooks_enabled: true`) wrap each function in a sandbox scope.

---

## Declarative API Tools

API tools let you expose REST API endpoints as agent tools using pure YAML — no Python required. Each endpoint becomes a separate tool with typed parameters.

### Scaffolding

```bash
initrunner init --template api --name weather-agent
```

### Full Example

```yaml
tools:
  - type: api
    name: github
    description: GitHub REST API
    base_url: https://api.github.com
    headers:
      Accept: application/vnd.github.v3+json
    auth:
      Authorization: "Bearer ${GITHUB_TOKEN}"
    endpoints:
      - name: get_repo
        method: GET
        path: "/repos/{owner}/{repo}"
        description: Get repository information
        parameters:
          - name: owner
            type: string
            required: true
            description: Repository owner
          - name: repo
            type: string
            required: true
            description: Repository name
        response_extract: "$.full_name"

      - name: create_issue
        method: POST
        path: "/repos/{owner}/{repo}/issues"
        description: Create an issue
        parameters:
          - name: owner
            type: string
            required: true
          - name: repo
            type: string
            required: true
          - name: title
            type: string
            required: true
            description: Issue title
          - name: body
            type: string
            required: false
            default: ""
            description: Issue body
        body_template:
          title: "{title}"
          body: "{body}"
        response_extract: "$.html_url"
```

This registers two tools: `get_repo(owner, repo)` and `create_issue(owner, repo, title, body)`.

### API Tool Config

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | *(required)* | Name for this API group (used in `summary()`). |
| `description` | `str` | `""` | Description of the API. |
| `base_url` | `str` | *(required)* | Base URL for all endpoints. |
| `headers` | `dict[str, str]` | `{}` | Headers sent with every request. Supports `${VAR}` env var syntax. |
| `auth` | `dict[str, str]` | `{}` | Auth headers merged into `headers`. Supports `${VAR}` env var syntax. |
| `endpoints` | `list[ApiEndpoint]` | *(required)* | Endpoint definitions. |

### Endpoint Config

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | *(required)* | Tool function name. |
| `method` | `GET \| POST \| PUT \| PATCH \| DELETE` | `GET` | HTTP method. |
| `path` | `str` | *(required)* | URL path appended to `base_url`. Supports `{param}` placeholders. |
| `description` | `str` | `""` | Tool description. Falls back to `"{method} {path}"`. |
| `parameters` | `list[ApiParameter]` | `[]` | Typed parameters exposed to the LLM. |
| `headers` | `dict[str, str]` | `{}` | Endpoint-specific headers (merged with API-level headers). |
| `body_template` | `dict \| null` | `null` | JSON body template. String values support `{param}` substitution. |
| `query_params` | `dict[str, str]` | `{}` | Query parameters. String values support `{param}` substitution. |
| `response_extract` | `str \| null` | `null` | JSONPath expression (e.g. `$.data.id`) to extract from the response. `null` returns the full response text. |
| `timeout` | `int` | `30` | Request timeout in seconds. |

### Parameter Config

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | *(required)* | Parameter name. Must be a valid Python identifier. |
| `type` | `string \| integer \| number \| boolean` | *(required)* | JSON Schema type, mapped to Python (`str`, `int`, `float`, `bool`). |
| `required` | `bool` | `false` | Whether the parameter is required. |
| `default` | `any` | `null` | Default value for optional parameters. |
| `description` | `str` | `""` | Parameter description for the LLM. |

### Environment Variables

Headers and auth values support `${VAR}` syntax for environment variable resolution:

```yaml
headers:
  Authorization: "Bearer ${API_TOKEN}"
  X-Custom: "static-value"
```

If `API_TOKEN` is set, it is substituted. If not, the literal `${API_TOKEN}` string is kept (which will likely cause an auth error — this is intentional so you can debug missing env vars).

### Response Extraction

Use `response_extract` with simple JSONPath to pull a specific field from JSON responses:

```yaml
response_extract: "$.data.results"     # nested field
response_extract: "$.items.0.name"     # array index
```

Supported syntax: `$.field.subfield.0.nested` — dot-separated path starting with `$`. Array indices are numeric segments. If the path is not found, the tool returns an error message. If the response is not valid JSON, the raw text is returned.

### How It Works

Each endpoint generates a Python function at agent build time with:

- A proper `inspect.Signature` so PydanticAI can introspect parameters.
- `__annotations__` mapping parameter names to Python types.
- `__doc__` set from the endpoint description.

Requests use `httpx.Client` (sync). HTTP errors are caught and returned as strings so the agent can recover.

---

## Plugin Registry

The plugin registry lets third-party packages register tool types that work like builtins. Users install a package and reference the new type in their role YAML.

### Using Plugins

```bash
pip install initrunner-slack    # hypothetical plugin package
```

```yaml
tools:
  - type: slack
    channel: "#alerts"
    token: ${SLACK_TOKEN}
```

Unknown tool types are automatically routed to the plugin registry. Any keys besides `type` are passed as the plugin's `config` dict.

List installed plugins:

```bash
initrunner plugins
```

### Creating a Plugin

A plugin package needs two things: a `ToolPlugin` definition and an entry point.

#### 1. Define the Plugin

```python
# initrunner_slack/plugin.py

from pydantic import BaseModel
from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.plugins import ToolPlugin


class SlackToolConfig(BaseModel):
    type: str = "slack"
    channel: str = "#general"
    token: str = ""


def build_slack_toolset(config: SlackToolConfig, **kwargs) -> FunctionToolset:
    toolset = FunctionToolset()

    @toolset.tool
    def send_message(text: str) -> str:
        """Send a message to the configured Slack channel."""
        # ... implementation using config.token and config.channel
        return f"Sent to {config.channel}"

    return toolset


def create_plugin() -> ToolPlugin:
    return ToolPlugin(
        type="slack",
        config_class=SlackToolConfig,
        builder=build_slack_toolset,
        description="Send messages to Slack channels",
    )
```

#### 2. Register the Entry Point

In your package's `pyproject.toml`:

```toml
[project.entry-points."initrunner.tools"]
slack = "initrunner_slack.plugin:create_plugin"
```

The entry point must be a callable that returns a `ToolPlugin` instance.

#### ToolPlugin Fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | `str` | Discriminator value used in role YAML (e.g. `"slack"`). |
| `config_class` | `type[BaseModel]` | Pydantic model for validating the tool config. |
| `builder` | `Callable` | `(validated_config, **kwargs) -> AbstractToolset` — builds the toolset. |
| `description` | `str` | Human-readable description shown in `initrunner plugins`. |

### Discovery

Plugin discovery uses `importlib.metadata.entry_points(group="initrunner.tools")`. It is **lazy** — entry points are only scanned the first time a non-builtin tool type is encountered, keeping `--help` and validation fast.

Broken entry points (import errors, invalid return types) are silently skipped so one bad plugin cannot break the entire CLI.

### Error Messages

When a tool type is not found:

- **No plugins installed:** `Tool type 'slack' not found. No plugins installed. Install one with: pip install initrunner-slack`
- **Plugins installed but not this one:** `Tool type 'slack' not found. Installed plugins: ['jira', 'pagerduty']. Did you forget to pip install initrunner-slack?`

### Config Validation

The config dict from the YAML is validated against the plugin's `config_class` using `model_validate()`. If required fields are missing or types are wrong, Pydantic raises a validation error at role load time.

---

## Builtin Tool Types

For reference, the builtin tool types that are always available:

| Type | Description | Docs |
|------|-------------|------|
| `filesystem` | Sandboxed file read/write | [tools.md](tools.md#filesystem-tool) |
| `http` | HTTP requests to a base URL | [tools.md](tools.md#http-tool) |
| `mcp` | MCP server connection | [tools.md](tools.md#mcp-tool) |
| `custom` | Python module tools | This page |
| `delegate` | Agent-to-agent delegation | [delegation.md](../orchestration/delegation.md) |
| `api` | Declarative REST API tools | This page |
| `web_reader` | Fetch web pages as markdown | [tools.md](tools.md#web-reader-tool) |
| `python` | Subprocess Python execution | [tools.md](tools.md#python-tool) |
| `datetime` | Current time and date parsing | [tools.md](tools.md#datetime-tool) |
| `sql` | SQLite query execution | [tools.md](tools.md#sql-tool) |
| `git` | Git operations (log, diff, blame, etc.) | [tools.md](tools.md#git-tool) |
| `shell` | Subprocess shell with allowlist/blocklist | [tools.md](tools.md#shell-tool) |
| `slack` | Slack webhook messaging with Block Kit | [tools.md](tools.md#slack-tool) |
| `web_scraper` | Scrape, chunk, embed, and store web pages | [tools.md](tools.md#web-scraper-tool) |

Any other `type` value is routed to the plugin registry.
