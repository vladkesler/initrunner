# MCP Gateway & Toolkit -- Expose Agents and Tools as MCP Servers

InitRunner offers two ways to expose capabilities via [MCP (Model Context Protocol)](https://modelcontextprotocol.io/), plus a visual management hub in the [dashboard](dashboard.md#mcp-hub-mcp):

| Command | What it exposes | LLM required? | Use case |
|---------|----------------|----------------|----------|
| `initrunner mcp serve` | Agents (full LLM reasoning) | Yes — each tool call triggers an agent run | Expose specialized agents to MCP clients |
| `initrunner mcp toolkit` | Raw tools (web search, CSV, SQL, etc.) | **No** — tools execute directly | Give AI coding assistants extra capabilities |

---

## MCP Toolkit — Direct Tool Server

The `initrunner mcp toolkit` command exposes InitRunner's built-in tools directly as MCP tools — no agent, no LLM, no API key required (for default tools). AI coding assistants like Claude Code, Claude Desktop, Gemini CLI, Codex CLI, Cursor, and Windsurf already have their own LLM — they just need additional **capabilities**.

### Quick Start

```bash
# Expose default tools (search, web reader, CSV analysis, datetime)
initrunner mcp toolkit

# Expose specific tools
initrunner mcp toolkit --tools search,csv_analysis,sql

# Use a config file for advanced options
initrunner mcp toolkit --config toolkit.yaml

# Network mode
initrunner mcp toolkit --transport sse --port 8080
```

### Client Configuration

#### Claude Code / Cursor / Windsurf

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "initrunner-toolkit": {
      "command": "initrunner",
      "args": ["mcp", "toolkit"]
    }
  }
}
```

With specific tools:

```json
{
  "mcpServers": {
    "initrunner-toolkit": {
      "command": "initrunner",
      "args": ["mcp", "toolkit", "--tools", "search,csv_analysis,datetime"]
    }
  }
}
```

#### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "initrunner-toolkit": {
      "command": "initrunner",
      "args": ["mcp", "toolkit"]
    }
  }
}
```

#### Gemini CLI

Add to your `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "initrunner-toolkit": {
      "command": "initrunner",
      "args": ["mcp", "toolkit"]
    }
  }
}
```

#### Codex CLI

Add to your `~/.codex/config.json`:

```json
{
  "mcpServers": {
    "initrunner-toolkit": {
      "command": "initrunner",
      "args": ["mcp", "toolkit"]
    }
  }
}
```

### Available Tools

**Default tools** (free, no API key, no external state):

| Tool | MCP Functions | Description |
|------|---------------|-------------|
| `search` | `web_search`, `news_search` | DuckDuckGo search (free, no key). |
| `web_reader` | `fetch_page` | Fetch URLs and return clean markdown with SSRF protection. |
| `csv_analysis` | `inspect_csv`, `query_csv`, `summarize_csv` | CSV analysis without writing Python. |
| `datetime` | `current_time`, `parse_date` | Timezone-aware time and date parsing. |

**Opt-in tools** (require config/credentials):

| Tool | MCP Functions | Requires |
|------|---------------|----------|
| `sql` | `sql_query` | `database` path in config |
| `http` | `http_request` | `base_url` in config |
| `email` | `search_inbox`, `read_email`, `list_folders`, `send_email` | IMAP/SMTP credentials |
| `audio` | `get_youtube_transcript` | `youtube-transcript-api` package |

### CLI Options

Synopsis: `initrunner mcp toolkit [OPTIONS]`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--tools, -T` | `str` | *(defaults)* | Comma-separated list of tools to expose. |
| `--config, -c` | `Path` | `None` | Path to `toolkit.yaml` config file. |
| `--transport, -t` | `str` | `stdio` | Transport: `stdio`, `sse`, or `streamable-http`. |
| `--host` | `str` | `127.0.0.1` | Host to bind to (sse/http only). |
| `--port` | `int` | `8080` | Port to listen on (sse/http only). |
| `--server-name` | `str` | `initrunner-toolkit` | MCP server name (overrides config). |

### Config File Format

For opt-in tools or customized defaults, create a `toolkit.yaml`:

```yaml
server_name: initrunner-toolkit
tools:
  search:
    provider: duckduckgo        # or serpapi, brave, tavily
  web_reader: {}                # empty = defaults
  csv_analysis:
    root_path: ./data
  datetime:
    default_timezone: America/New_York
  sql:
    database: ./myapp.db
    read_only: true
  email:
    imap_host: imap.gmail.com
    username: ${EMAIL_USER}     # env var interpolation
    password: ${EMAIL_PASS}
```

Environment variable interpolation (`${VAR}`) works in config values — the same `resolve_env_vars()` pattern used elsewhere in InitRunner.

### Programmatic API

```python
from initrunner.mcp.toolkit import ToolkitConfig, build_toolkit
from initrunner.mcp.gateway import run_mcp_gateway

# Default tools
mcp = build_toolkit()

# Selective tools
mcp = build_toolkit(tool_names=["search", "datetime"])

# With config
config = ToolkitConfig(tools={"sql": {"database": "app.db"}})
mcp = build_toolkit(config)

run_mcp_gateway(mcp, transport="stdio")
```

Or via the services layer:

```python
from initrunner.services.operations import build_toolkit_sync

mcp = build_toolkit_sync(tool_names=["search", "csv_analysis"])
```

---

## MCP Gateway — Expose Agents as MCP Tools

The `initrunner mcp serve` command exposes one or more InitRunner agents as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server. This lets Claude Code, Claude Desktop, Gemini CLI, Codex CLI, Cursor, Windsurf, and any other MCP client call your agents directly as tools.

InitRunner already supports MCP as a **client** (consuming external MCP servers as agent tools). The gateway adds the reverse direction — your agents become the server.

## Quick Start

```bash
# Expose a single agent over stdio (for Claude Desktop / Claude Code)
initrunner mcp serve examples/roles/hello-world.yaml

# Expose multiple agents
initrunner mcp serve roles/researcher.yaml roles/writer.yaml roles/reviewer.yaml

# Use SSE transport for network clients
initrunner mcp serve roles/agent.yaml --transport sse --host 0.0.0.0 --port 8080
```

Each role becomes an MCP tool. The tool name is derived from `metadata.name` in the role YAML. When names collide, suffixes (`_2`, `_3`, ...) are appended automatically.

## CLI Options

Synopsis: `initrunner mcp serve ROLE_FILES... [OPTIONS]`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `ROLE_FILES` | `Path...` | *(required)* | One or more role YAML files to expose as MCP tools. |
| `--transport, -t` | `str` | `stdio` | Transport protocol: `stdio`, `sse`, or `streamable-http`. |
| `--host` | `str` | `127.0.0.1` | Host to bind to (sse/streamable-http only). |
| `--port` | `int` | `8080` | Port to listen on (sse/streamable-http only). |
| `--server-name` | `str` | `initrunner` | MCP server name reported to clients. |
| `--pass-through` | `bool` | `false` | Also expose the agents' own MCP tools directly (see [Pass-Through Mode](#pass-through-mode)). |
| `--audit-db` | `Path` | `~/.initrunner/audit.db` | Path to audit database. |
| `--no-audit` | `bool` | `false` | Disable audit logging. |
| `--skill-dir` | `Path` | `None` | Extra skill search directory. |

## Transports

### stdio (default)

The standard transport for local MCP integrations. The MCP client launches `initrunner mcp serve` as a subprocess and communicates over stdin/stdout.

All status output (agent listing, errors) is printed to stderr to keep stdout clean for the MCP protocol.

```bash
initrunner mcp serve roles/agent.yaml
```

### SSE (Server-Sent Events)

For network-accessible servers. The MCP client connects via HTTP.

```bash
initrunner mcp serve roles/agent.yaml --transport sse --host 0.0.0.0 --port 8080
```

### Streamable HTTP

Modern HTTP-based transport with bidirectional streaming.

```bash
initrunner mcp serve roles/agent.yaml --transport streamable-http --port 9090
```

## How It Works

1. At startup, the gateway loads and builds all specified roles (using `load_and_build`).
2. Each agent is registered as an MCP tool with the name from `metadata.name`.
3. When an MCP client calls a tool, the gateway runs the agent with the provided `prompt` string and returns the output.
4. Agent execution errors are returned as error strings — they never crash the MCP server.
5. Audit logging works the same as in other execution modes.

### Tool Naming

Tool names are derived from the role's `metadata.name` field. Characters that are not alphanumeric, hyphens, or underscores are replaced with `_`. When multiple roles share the same name, suffixes are appended:

| Role Name | Tool Name |
|-----------|-----------|
| `researcher` | `researcher` |
| `writer` | `writer` |
| `writer` (duplicate) | `writer_2` |
| `my agent!` | `my_agent_` |

### Tool Schema

Each registered tool accepts a single parameter:

| Parameter | Type | Description |
|-----------|------|-------------|
| `prompt` | `string` | The prompt to send to the agent. |

The tool description is taken from `metadata.description` in the role YAML.

## Client Configuration

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "initrunner": {
      "command": "initrunner",
      "args": ["mcp", "serve", "/path/to/roles/agent.yaml"]
    }
  }
}
```

For multiple agents:

```json
{
  "mcpServers": {
    "initrunner": {
      "command": "initrunner",
      "args": [
        "mcp", "serve",
        "/path/to/roles/researcher.yaml",
        "/path/to/roles/writer.yaml"
      ]
    }
  }
}
```

### Claude Code

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "initrunner": {
      "command": "initrunner",
      "args": ["mcp", "serve", "roles/agent.yaml"]
    }
  }
}
```

### Cursor / Windsurf

Add to your Cursor or Windsurf MCP settings:

```json
{
  "mcpServers": {
    "initrunner": {
      "command": "initrunner",
      "args": ["mcp", "serve", "roles/agent.yaml"]
    }
  }
}
```

### Gemini CLI

Add to your `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "initrunner": {
      "command": "initrunner",
      "args": ["mcp", "serve", "roles/agent.yaml"]
    }
  }
}
```

### Codex CLI

Add to your `~/.codex/config.json`:

```json
{
  "mcpServers": {
    "initrunner": {
      "command": "initrunner",
      "args": ["mcp", "serve", "roles/agent.yaml"]
    }
  }
}
```

### Network Clients (SSE / Streamable HTTP)

Start the server:

```bash
initrunner mcp serve roles/agent.yaml --transport sse --host 0.0.0.0 --port 8080
```

Then configure your MCP client to connect to `http://<host>:8080`.

## Pass-Through Mode

With `--pass-through`, the gateway also exposes MCP tools that the agents themselves consume. This is useful when you want a single MCP server to expose both the agents and their underlying tools.

```bash
initrunner mcp serve roles/agent.yaml --pass-through
```

### How It Works

- Only `type: mcp` tools from the role are passed through. Other tool types (shell, filesystem, etc.) are skipped because they require PydanticAI `RunContext`, which doesn't exist outside an agent run.
- If no roles have MCP tools configured, `--pass-through` is a no-op.
- Pass-through tools are prefixed with `{agent_name}_` to avoid collisions across agents. If the MCP tool config also has a `tool_prefix`, both prefixes are combined.
- The role's `tool_filter`, `tool_exclude`, and `tool_prefix` settings are honored.

### Security

Pass-through mode applies the same sandbox checks as agent execution:

- MCP commands are validated against `security.tools.mcp_command_allowlist`.
- Environment variables are scrubbed using `sensitive_env_prefixes`, `sensitive_env_suffixes`, and `env_allowlist` from the role's security policy.
- Working directories are resolved relative to the role file's directory.

## Multiple Agents Example

Create a multi-tool MCP server from several specialized agents:

```bash
# roles/researcher.yaml  — searches the web and summarizes findings
# roles/writer.yaml      — writes polished prose from notes
# roles/reviewer.yaml    — reviews text for clarity and correctness

initrunner mcp serve roles/researcher.yaml roles/writer.yaml roles/reviewer.yaml
```

An MCP client (e.g., Claude Desktop) can then orchestrate all three agents as tools within a single conversation.

## Error Handling

- **Startup errors**: If any role file fails to load, the gateway exits immediately with a clear error message identifying the problematic file.
- **Runtime errors**: Agent execution failures are returned as error strings (`"Error: ..."`) to the MCP client. Unexpected exceptions are caught and returned as `"Internal error: ..."`. The MCP server never crashes due to an agent error.
- **Invalid transport**: Rejected at startup with a descriptive error listing the valid options.

## Audit Logging

Agent runs through the gateway are audit-logged the same way as any other execution mode. Use `--audit-db` to set a custom database path, or `--no-audit` to disable logging.

```bash
# Query audit logs for gateway runs
initrunner audit query --agent-name researcher
```

## Programmatic API

The gateway can also be used programmatically:

```python
from pathlib import Path
from initrunner.mcp.gateway import build_mcp_gateway, run_mcp_gateway

mcp = build_mcp_gateway(
    [Path("roles/agent.yaml")],
    server_name="my-server",
)
run_mcp_gateway(mcp, transport="stdio")
```

Or via the services layer:

```python
from pathlib import Path
from initrunner.services.operations import build_mcp_gateway_sync

mcp = build_mcp_gateway_sync([Path("roles/agent.yaml")])
```

## Dashboard Integration -- MCP Hub

The dashboard includes an MCP Hub page (`/mcp`) for visual management of MCP servers configured as agent tools. See [Dashboard -- MCP Hub](dashboard.md#mcp-hub-mcp) for full details.

Key features:

- **Servers tab**: aggregated view of all MCP servers across all agents, deduplicated by connection identity. Expand any server to introspect its tools. Health check dots show server status.
- **Discover tab**: curated registry of popular MCP servers with one-click YAML snippet copying.
- **Playground tab**: execute any MCP tool in isolation (no LLM needed). Auto-generated forms from tool input schemas. History sidebar for quick replay.
- **Canvas tab**: @xyflow/svelte topology visualization showing which agents consume which MCP servers.
- **Health monitoring**: 30-second TTL cache for health checks. Sidebar badge shows a red dot when any server is unhealthy. Launchpad widget summarizes overall MCP health.

The MCP Hub uses the same `build_transport()` and sandbox enforcement as agent execution -- command allowlists, env scrubbing, and SSRF protection all apply when the playground executes tool calls.
