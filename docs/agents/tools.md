# Tools — Configuration Reference

Tools give agents the ability to interact with the outside world — reading files, making HTTP requests, connecting to MCP servers, calling APIs, or running custom Python functions. They are configured in the `spec.tools` list of a role definition, keyed on the `type` field.

In addition to explicitly configured tools, InitRunner auto-registers tools when `ingest` or `memory` sections are present in the role definition. Any unrecognized `type` value is routed to the [plugin registry](tool_creation.md#plugin-registry).

## Tool Types

| Type | Description |
|------|-------------|
| `filesystem` | Read/write files within a sandboxed root directory |
| `http` | Make HTTP requests to a base URL |
| `mcp` | Connect to MCP servers (stdio, SSE, streamable-http) |
| `custom` | Load Python functions from a module — single function or auto-discover all |
| `delegate` | Invoke other agents as tool calls (inline or remote) |
| `api` | Declarative REST API endpoints defined entirely in YAML |
| `web_reader` | Fetch web pages and convert to markdown |
| `python` | Execute Python code in a subprocess with isolation |
| `datetime` | Get current time and parse dates |
| `sql` | Query SQLite databases with read-only pragma |
| `git` | Run git operations in a subprocess with read-only default |
| `shell` | Execute commands in a subprocess with allow/block lists |
| `slack` | Send messages to Slack via incoming webhooks |
| `web_scraper` | Fetch, chunk, embed, and store web pages in the document store |
| `search` | Search the web and news via DuckDuckGo, SerpAPI, Brave, or Tavily |
| `audio` | Fetch YouTube transcripts and transcribe local audio files |
| *(plugin)* | Any other type is resolved via the [plugin registry](tool_creation.md#plugin-registry) |

## Quick Example

```yaml
spec:
  tools:
    - type: filesystem
      root_path: ./src
      read_only: true
      allowed_extensions: [".py", ".md"]
    - type: http
      base_url: https://api.example.com
      allowed_methods: ["GET", "POST"]
      headers:
        Authorization: Bearer ${API_TOKEN}
    - type: mcp
      transport: stdio
      command: npx
      args: ["-y", "@anthropic/mcp-server-filesystem"]
    - type: custom
      module: my_tools              # auto-discover all public functions
      config:
        db_url: "postgres://..."
    - type: api
      name: weather
      base_url: https://api.weather.com
      endpoints:
        - name: get_weather
          path: "/current/{city}"
          parameters:
            - name: city
              type: string
              required: true
```

## Filesystem Tool

Provides sandboxed file operations within a root directory. Paths are resolved relative to `root_path` and cannot escape it (path traversal is blocked).

```yaml
tools:
  - type: filesystem
    root_path: ./src        # default: "."
    read_only: true         # default: true
    allowed_extensions:     # default: [] (all extensions)
      - ".py"
      - ".md"
      - ".txt"
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `root_path` | `str` | `"."` | Root directory for file operations. Paths are resolved relative to this. |
| `allowed_extensions` | `list[str]` | `[]` | File extensions to allow. Empty list means all extensions. Include the dot (e.g. `".py"`). |
| `read_only` | `bool` | `true` | When `true`, only read operations are available. Set to `false` to enable writing. |

### Registered Functions

**Always registered:**

- **`read_file(path: str) -> str`** — Read the contents of a file. Files larger than 1 MB are truncated and a `[truncated]` note is appended. Returns an error string if the path is outside the root or the extension is not allowed.
- **`list_directory(path: str = ".") -> str`** — List files and directories at the given path. Returns entries separated by newlines, or `"(empty directory)"`.

**Registered when `read_only: false`:**

- **`write_file(path: str, content: str) -> str`** — Write content to a file. Creates parent directories if needed. Returns a confirmation with byte count.

### Security

- All paths are resolved with `.resolve()` and checked against the root directory to prevent path traversal.
- Extension filtering applies to both reads and writes.
- Errors are returned as strings (not exceptions), so the agent can recover gracefully.

### Resource Limits

Built-in tools enforce output size limits to prevent large responses from consuming excessive context window or memory:

| Tool | Limit | Behavior |
|------|-------|----------|
| `read_file` | 1 MB | Reads first 1 MB of bytes, decodes with replacement characters, appends `[truncated]` |
| `http_request` | 100 KB | Slices response text at 100 KB, appends `[truncated]` |
| `git_*` | 100 KB | Truncates output with `[truncated — use the path argument to narrow results]` |

## HTTP Tool

Makes HTTP requests to a configured base URL. Methods are restricted to the allowed list.

```yaml
tools:
  - type: http
    base_url: https://api.example.com    # required
    allowed_methods: ["GET"]              # default: ["GET"]
    headers:                              # default: {}
      Authorization: Bearer ${API_TOKEN}
      Accept: application/json
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `base_url` | `str` | *(required)* | Base URL for requests. Paths from the agent are appended to this. |
| `allowed_methods` | `list[str]` | `["GET"]` | HTTP methods the agent is allowed to use. |
| `headers` | `dict[str, str]` | `{}` | Headers sent with every request. |

### Registered Functions

- **`http_request(method: str, path: str, body: str = "") -> str`** — Make an HTTP request. Returns `"HTTP {status_code}\n{response_body}"` or an error string. Response bodies larger than 100 KB are truncated with a `[truncated]` note. Uses a 30-second timeout via `httpx`.

### Example

With `base_url: https://api.example.com`, calling `http_request("GET", "/users/123")` sends a GET request to `https://api.example.com/users/123`.

## MCP Tool

Connects to an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server, making all of its tools available to the agent via PydanticAI's `FastMCPToolset`.

```yaml
tools:
  # Stdio transport (local process)
  - type: mcp
    transport: stdio
    command: npx
    args: ["-y", "@anthropic/mcp-server-filesystem"]

  # SSE transport (remote server)
  - type: mcp
    transport: sse
    url: http://localhost:3001/sse

  # Streamable HTTP transport with auth and tool filtering
  - type: mcp
    transport: streamable-http
    url: http://localhost:3001/mcp
    headers:
      Authorization: "Bearer ${MCP_API_TOKEN}"
    tool_filter:
      - search
      - get_document
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `transport` | `"stdio" \| "sse" \| "streamable-http"` | `"stdio"` | Transport protocol to use. |
| `command` | `str \| null` | `null` | Command to run for stdio transport. **Required** when `transport: stdio`. |
| `args` | `list[str]` | `[]` | Arguments for the stdio command. |
| `url` | `str \| null` | `null` | URL for SSE or streamable-http transport. **Required** when `transport: sse` or `streamable-http`. |
| `tool_filter` | `list[str]` | `[]` | Allowlist of tool names to expose. Empty list exposes all tools. Mutually exclusive with `tool_exclude`. |
| `tool_exclude` | `list[str]` | `[]` | Blocklist of tool names to hide. Mutually exclusive with `tool_filter`. |
| `headers` | `dict[str, str]` | `{}` | Headers for remote transports (SSE, streamable-http). Supports `${VAR}` env var syntax. |
| `env` | `dict[str, str]` | `{}` | Environment variables for stdio subprocess. Merged on top of scrubbed system env. Supports `${VAR}` syntax. |
| `cwd` | `str \| null` | `null` | Working directory for stdio transport. Relative paths resolve against the role file's directory. |
| `tool_prefix` | `str \| null` | `null` | Prefix added to all tool names (e.g., `"remote"` turns `read_file` into `remote_read_file`). |
| `max_retries` | `int` | `1` | Retry count on tool failures. |
| `timeout` | `int \| null` | `null` | Connection timeout in seconds. |

### Transport Types

**`stdio`** — Launches a local process and communicates via stdin/stdout. Best for local MCP servers packaged as CLI tools.

**`sse`** — Connects to a remote MCP server using Server-Sent Events. The `url` should point to the SSE endpoint.

**`streamable-http`** — Connects to a remote MCP server using the streamable HTTP transport. The `url` should point to the MCP endpoint.

### Examples

**Auth headers for remote transports:**

```yaml
tools:
  - type: mcp
    transport: sse
    url: https://mcp.example.com/sse
    headers:
      Authorization: "Bearer ${MCP_API_TOKEN}"
```

**Environment variable forwarding for stdio:**

```yaml
tools:
  - type: mcp
    transport: stdio
    command: npx
    args: ["-y", "@org/mcp-server-github"]
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

**Working directory for stdio:**

```yaml
tools:
  - type: mcp
    transport: stdio
    command: npx
    args: ["-y", "@anthropic/mcp-server-filesystem"]
    cwd: ./workspace
```

**Multi-server with `tool_prefix` to avoid collisions:**

```yaml
tools:
  - type: mcp
    transport: sse
    url: https://staging.example.com/mcp
    tool_prefix: staging
  - type: mcp
    transport: sse
    url: https://prod.example.com/mcp
    tool_prefix: prod
```

**Exclude specific tools:**

```yaml
tools:
  - type: mcp
    transport: stdio
    command: npx
    args: ["-y", "@org/mcp-server"]
    tool_exclude:
      - dangerous_tool
      - admin_reset
```

### CLI Introspection

List tools available from MCP servers configured in a role file:

```bash
# List all MCP tools across all configured servers
initrunner mcp list-tools role.yaml

# Target a specific MCP tool entry (0-based index)
initrunner mcp list-tools role.yaml --index 0
```

This command does not require valid LLM API keys — it connects to MCP servers directly.

## Custom Tool

Loads Python functions from a module and registers them as agent tools. Each function's name, docstring, and type annotations become the tool name, description, and parameter schema.

### Scaffolding

```bash
initrunner init --template tool --name my_tools
```

### Single Function

Specify `function` to load exactly one tool:

```yaml
tools:
  - type: custom
    module: my_tools
    function: search_db
```

### Auto-Discovery

Omit `function` to register all public functions in the module:

```yaml
tools:
  - type: custom
    module: my_tools
```

Auto-discovery collects every object in the module that is a function (`inspect.isfunction`), public (name does not start with `_`), and not a class, module, or builtin. If no qualifying functions are found, loading fails with a clear error.

### Config Injection

Pass configuration to tools via the `config` dict. Functions that declare a `tool_config` parameter receive it automatically — the parameter is hidden from the LLM.

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
    # ... use api_key
    return results
```

The LLM sees `search(query: str) -> str` — only `query` is exposed.

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `module` | `str` | *(required)* | Python module path (e.g. `my_tools` or `pkg.utils`). Must be importable. |
| `function` | `str \| null` | `null` | Function name to load. `null` auto-discovers all public functions. |
| `config` | `dict` | `{}` | Config dict injected into functions that accept a `tool_config` parameter. |

### Example

```python
# my_tools.py (importable on PYTHONPATH)

def search_db(query: str, limit: int = 10) -> str:
    """Search the database for records matching the query."""
    results = db.search(query, limit=limit)
    return "\n".join(str(r) for r in results)

def summarize(text: str) -> str:
    """Summarize a piece of text."""
    return text[:200] + "..."
```

```yaml
tools:
  # Registers both search_db and summarize
  - type: custom
    module: my_tools
```

The module is imported via `importlib.import_module` at agent build time. If the module cannot be imported, the error message identifies the missing dependency and suggests a `pip install` command.

See [Tool Creation Guide](tool_creation.md#custom-tools) for full details on writing tool functions, config injection internals, and security.

## API Tool

Defines REST API endpoints as agent tools using pure YAML — no Python required. Each endpoint becomes a separate tool with typed parameters.

### Scaffolding

```bash
initrunner init --template api --name weather-agent
```

### Example

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
          - name: repo
            type: string
            required: true
        response_extract: "$.full_name"

      - name: create_issue
        method: POST
        path: "/repos/{owner}/{repo}/issues"
        description: Create a new issue
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
          - name: body
            type: string
            required: false
            default: ""
        body_template:
          title: "{title}"
          body: "{body}"
        response_extract: "$.html_url"
```

This registers two tools: `get_repo(owner, repo)` and `create_issue(owner, repo, title, body)`.

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | *(required)* | Name for this API group. |
| `description` | `str` | `""` | Description of the API. |
| `base_url` | `str` | *(required)* | Base URL for all endpoints. |
| `headers` | `dict[str, str]` | `{}` | Headers sent with every request. Supports `${VAR}` env var syntax. |
| `auth` | `dict[str, str]` | `{}` | Auth headers merged into `headers`. Supports `${VAR}` env var syntax. |
| `endpoints` | `list` | *(required)* | Endpoint definitions (see below). |

### Endpoint Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | *(required)* | Tool function name. |
| `method` | `GET \| POST \| PUT \| PATCH \| DELETE` | `GET` | HTTP method. |
| `path` | `str` | *(required)* | URL path. Supports `{param}` placeholders filled from parameters. |
| `description` | `str` | `""` | Tool description shown to the LLM. Falls back to `"{method} {path}"`. |
| `parameters` | `list` | `[]` | Typed parameters (see below). |
| `headers` | `dict[str, str]` | `{}` | Endpoint-specific headers (merged with API-level headers). |
| `body_template` | `dict \| null` | `null` | JSON body template. String values support `{param}` substitution. |
| `query_params` | `dict[str, str]` | `{}` | Query parameters. String values support `{param}` substitution. |
| `response_extract` | `str \| null` | `null` | JSONPath (e.g. `$.data.id`) to extract from JSON responses. `null` returns full text. |
| `timeout` | `int` | `30` | Request timeout in seconds. |

### Parameter Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | *(required)* | Parameter name. Must be a valid Python identifier. |
| `type` | `string \| integer \| number \| boolean` | *(required)* | JSON Schema type, mapped to Python (`str`, `int`, `float`, `bool`). |
| `required` | `bool` | `false` | Whether the parameter is required. |
| `default` | `any` | `null` | Default value for optional parameters. |
| `description` | `str` | `""` | Parameter description for the LLM. |

### Environment Variables

Header values support `${VAR}` syntax. If the variable is set, it is substituted. If not, the literal `${VAR}` string is kept.

### Response Extraction

Simple JSONPath syntax extracts fields from JSON responses:

```yaml
response_extract: "$.data.results"     # nested field
response_extract: "$.items.0.name"     # array index
```

If the path is not found, the tool returns an error message. If the response is not valid JSON, the raw text is returned.

See [Tool Creation Guide](tool_creation.md#declarative-api-tools) for full details.

## Delegate Tool

Invokes other agents as tool calls. Supports inline mode (in-process, for dev) and MCP mode (HTTP, for distributed deployment). Each agent reference generates a `delegate_to_{name}` tool.

```yaml
tools:
  - type: delegate
    agents:
      - name: summarizer
        role_file: ./roles/summarizer.yaml
        description: "Summarizes long text"
      - name: researcher
        role_file: ./roles/researcher.yaml
        description: "Researches topics"
    mode: inline
    max_depth: 3
    timeout_seconds: 120
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `agents` | `list` | *(required)* | Agent references. Each needs `name` and either `role_file` (inline) or `url` (mcp). |
| `mode` | `"inline" \| "mcp"` | `"inline"` | Execution mode. |
| `max_depth` | `int` | `3` | Maximum delegation recursion depth. |
| `timeout_seconds` | `int` | `120` | Timeout per delegation call. |

### Registered Functions

For each agent in the `agents` list:

- **`delegate_to_{name}(prompt: str) -> str`** — Send a prompt to the named agent and return its output. Errors are returned as strings prefixed with `[DELEGATION ERROR]`.

See [Delegation](../orchestration/delegation.md) for the full configuration reference, MCP mode setup, depth tracking, and distributed deployment patterns.

## Git Tool

Provides subprocess-based git operations for reading repository state and optionally making changes. Follows the same isolation pattern as the Python tool — sensitive environment variables are scrubbed from the subprocess.

```yaml
tools:
  - type: git
    repo_path: .          # default: "."
    read_only: true       # default: true
    timeout_seconds: 30   # default: 30
    max_output_bytes: 102400  # default: 100 KB
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `repo_path` | `str` | `"."` | Path to the git repository (or any subdirectory inside one). Validated at build time via `git rev-parse`. |
| `read_only` | `bool` | `true` | When `true`, only read operations are available. Set to `false` to enable checkout, commit, and tag. |
| `timeout_seconds` | `int` | `30` | Timeout for each git command. |
| `max_output_bytes` | `int` | `102400` | Maximum output size. Truncated output includes a hint: `[truncated — use the path argument to narrow results]`. |

### Registered Functions

**Always registered (read tools):**

- **`git_status() -> str`** — Show working tree status in short format.
- **`git_log(max_count: int = 20, format: str = "oneline") -> str`** — Show commit log. Format must be one of `oneline`, `short`, `medium`, `full`, or `compact` (a token-efficient preset: hash + author + subject). Count is clamped to 1–100.
- **`git_diff(ref: str = "", staged: bool = False, path: str = "") -> str`** — Show changes in the working tree or between refs. Supports `--cached` via `staged`, a ref argument, and a path filter.
- **`git_show(ref: str = "HEAD") -> str`** — Show details of a commit (stat and patch).
- **`git_blame(path: str) -> str`** — Show line-by-line authorship of a file.
- **`git_changed_files(ref: str = "HEAD~1") -> str`** — List files changed compared to a ref (name and status).
- **`git_list_files(path: str = "") -> str`** — List tracked files (via `git ls-files`). Optional path to scope to a subdirectory.

**Registered when `read_only: false` (write tools):**

- **`git_checkout(branch: str, create: bool = False) -> str`** — Switch to a branch, or create a new one with `create=True`.
- **`git_commit(message: str, paths: str = ".") -> str`** — Stage files and create a commit.
- **`git_tag(name: str, message: str = "", ref: str = "HEAD") -> str`** — Create a lightweight tag, or an annotated tag if `message` is provided.

### Security

- **No `shell=True`** — all commands use list args.
- **Env scrubbing** — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AWS_SECRET`, `DATABASE_URL` prefixes are removed from the subprocess environment, preventing leaks through git hooks.
- **Format allowlist** — the `--format` argument is restricted to `{oneline, short, medium, full, compact}` to prevent format string abuse.
- **Output bounded** — responses exceeding `max_output_bytes` are truncated with an actionable recovery hint.
- **Repo validation** — `repo_path` is validated at build time via `git rev-parse --is-inside-work-tree`. Subdirectories inside a repo are accepted.
- **No `push`** — network-side-effecting operations are excluded by design.

### Resource Limits

| Tool | Limit | Behavior |
|------|-------|----------|
| All git tools | 100 KB (default) | Output truncated with `[truncated — use the path argument to narrow results]` |

### Example

```yaml
# Code review agent with read-only git access
tools:
  - type: git
    repo_path: .
    read_only: true
  - type: filesystem
    root_path: .
    read_only: true
```

## Web Reader Tool

Fetches a web page and converts the HTML to markdown for the agent to read. Useful for reading documentation, articles, or any public web page. Unlike the Web Scraper tool, the content is returned directly to the agent without being stored in the document store.

```yaml
tools:
  - type: web_reader
    allowed_domains:
      - docs.example.com
      - blog.example.com
    timeout_seconds: 15
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `allowed_domains` | `list[str]` | `[]` | Hostnames the agent may fetch. Empty list allows all (subject to blocked list). |
| `blocked_domains` | `list[str]` | `[]` | Hostnames the agent may not fetch. Ignored when `allowed_domains` is set. |
| `max_content_bytes` | `int` | `512000` | Maximum response size in bytes before truncation. |
| `timeout_seconds` | `int` | `15` | HTTP request timeout in seconds. |
| `user_agent` | `str` | `"initrunner/{version}"` | User-Agent header sent with requests. |

### Registered Functions

- **`fetch_page(url: str) -> str`** — Fetch a web page and return its content as markdown. Returns an error string if the domain is not allowed or the request fails.

### Security

- **SSRF protection** — Private/internal IP ranges are blocked via `SSRFSafeTransport`.
- **Domain allow/block lists** — `allowed_domains` restricts fetching to listed hosts; `blocked_domains` provides a blocklist alternative.

## Python Tool

Executes Python code in a subprocess with isolation. Sensitive environment variables are scrubbed from the subprocess. An optional network-disabling shim blocks outbound socket connections to non-loopback addresses.

```yaml
tools:
  - type: python
    timeout_seconds: 30
    max_output_bytes: 102400
    require_confirmation: true
    network_disabled: true
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `timeout_seconds` | `int` | `30` | Timeout for each code execution. |
| `max_output_bytes` | `int` | `102400` | Maximum output size (100 KB). Truncated output includes a `[truncated]` marker. |
| `working_dir` | `str \| null` | `null` | Working directory for execution. `null` uses a temporary directory that is cleaned up after each run. |
| `require_confirmation` | `bool` | `true` | When `true`, the agent must confirm before executing code. |
| `network_disabled` | `bool` | `true` | When `true`, a `sys.addaudithook` shim blocks outbound network connections to non-loopback addresses. |

### Registered Functions

- **`run_python(code: str) -> str`** — Execute Python code and return the combined stdout/stderr output. Code is written to a temporary file and run via the current Python interpreter in a subprocess.

### Security

- **Env scrubbing** — API keys and other sensitive environment variables are removed from the subprocess environment.
- **Network restriction** — When `network_disabled: true`, a `sys.addaudithook` shim blocks socket connections to non-loopback addresses. Proxy environment variables are also cleared.
- **No `shell=True`** — Code is executed via `subprocess.run` with list args.
- **Temp directory cleanup** — When `working_dir` is `null`, the temporary directory and all contents are removed after execution.

## DateTime Tool

Provides current time and date parsing. Useful for agents that need to reason about time, schedule tasks, or format dates.

```yaml
tools:
  - type: datetime
    default_timezone: US/Eastern
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_timezone` | `str` | `"UTC"` | Default timezone for `current_time` when no timezone is specified. Uses IANA timezone names (e.g. `US/Eastern`, `Europe/London`). |

### Registered Functions

- **`current_time(timezone: str = "") -> str`** — Get the current date and time. Leave timezone empty to use the configured default. Returns both ISO 8601 and human-readable format (e.g. `2024-01-15T10:30:00-05:00 (Monday, January 15, 2024 10:30:00 AM EST)`).
- **`parse_date(text: str, format: str = "") -> str`** — Parse a date string. Leave format empty for ISO 8601 auto-detection, or provide a `strftime` format string. Returns the parsed date in ISO 8601 format.

## SQL Tool

Queries SQLite databases with configurable read-only enforcement. Results are formatted as text tables with column alignment.

```yaml
tools:
  - type: sql
    database: ./data/app.db    # required
    read_only: true            # default: true
    max_rows: 100              # default: 100
    timeout_seconds: 10        # default: 10
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `database` | `str` | *(required)* | Path to SQLite database file. Relative paths are resolved against the role file's directory. Use `:memory:` for an in-memory database. |
| `read_only` | `bool` | `true` | When `true`, sets `PRAGMA query_only=ON` to prevent writes. |
| `max_rows` | `int` | `100` | Maximum number of rows returned per query. |
| `max_result_bytes` | `int` | `102400` | Maximum result size (100 KB). Truncated output includes a `[truncated]` marker. |
| `timeout_seconds` | `int` | `10` | SQLite connection timeout in seconds. |

### Registered Functions

- **`query_database(sql: str) -> str`** — Execute a SQL query against the configured SQLite database. SELECT queries return results as a formatted text table. Non-SELECT statements return a row count. Errors are returned as strings.

### Security

- **ATTACH DATABASE blocked** — `ATTACH DATABASE` statements are denied at both the regex and `sqlite3` authorizer levels, preventing access to other databases.
- **PRAGMA protection** — `PRAGMA query_only` modification is blocked to prevent the agent from disabling read-only mode.
- **Path validation** — Database paths are validated to be under the role directory or `~/.initrunner/` to prevent arbitrary file access.

### Example

```yaml
# Analytics agent with read-only database access
tools:
  - type: sql
    database: ./analytics.db
    read_only: true
    max_rows: 50
  - type: datetime
```

## Shell Tool

Executes commands in a subprocess with command allow/block lists. Commands are tokenized with `shlex.split` and run without a shell (`shell=False`), preventing shell injection. Shell operators (`|`, `&&`, `;`, etc.) are rejected.

```yaml
tools:
  - type: shell
    allowed_commands: []         # default: [] (all commands, subject to blocked list)
    working_dir: ./workspace     # default: null (role directory)
    timeout_seconds: 30          # default: 30
    require_confirmation: true   # default: true
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `allowed_commands` | `list[str]` | `[]` | Commands the agent may run. Empty list allows all (subject to blocked list). |
| `blocked_commands` | `list[str]` | *(see below)* | Commands the agent may not run. |
| `working_dir` | `str \| null` | `null` | Working directory for commands. `null` uses the role file's directory. |
| `timeout_seconds` | `int` | `30` | Timeout for each command. |
| `max_output_bytes` | `int` | `102400` | Maximum output size (100 KB). Truncated output includes a `[truncated]` marker. |
| `require_confirmation` | `bool` | `true` | When `true`, the agent must confirm before executing commands. |

### Default Blocked Commands

When `blocked_commands` is not specified, the following are blocked by default: `rm`, `mkfs`, `dd`, `fdisk`, `parted`, `mount`, `umount`, `shutdown`, `reboot`, `halt`, `poweroff`, `chmod`, `chown`, `passwd`, `useradd`, `userdel`, `sudo`, `su`.

### Registered Functions

- **`run_shell(command: str) -> str`** — Execute a command and return the combined stdout/stderr output. The command is tokenized with `shlex.split` and run without a shell. Returns an error string if the command is blocked, contains shell operators, or times out.

### Security

- **No `shell=True`** — Commands are parsed with `shlex.split` and executed as a list, preventing shell injection.
- **Shell operator blocking** — Pipe (`|`), chain (`&&`, `||`, `;`), redirection (`>`, `<`), and background (`&`) operators are rejected.
- **Fork bomb detection** — The `:(){ ...` pattern is detected and blocked.
- **Command allow/block lists** — `allowed_commands` restricts execution to listed commands; `blocked_commands` provides a blocklist of dangerous commands.
- **Env scrubbing** — Sensitive environment variables are removed from the subprocess environment.

## Slack Tool

Sends messages to Slack via incoming webhooks. Supports plain text messages, channel overrides, custom usernames, and Block Kit blocks for rich formatting.

```yaml
tools:
  - type: slack
    webhook_url: ${SLACK_WEBHOOK_URL}    # required
    default_channel: "#alerts"           # optional
    username: InitRunner                 # optional
    icon_emoji: ":robot_face:"           # optional
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `webhook_url` | `str` | *(required)* | Slack incoming webhook URL. Supports `${ENV_VAR}` substitution. |
| `default_channel` | `str \| null` | `null` | Default channel to post to. Can be overridden per message. |
| `username` | `str \| null` | `null` | Username to display for the bot. |
| `icon_emoji` | `str \| null` | `null` | Emoji to use as the bot's icon (e.g. `":robot_face:"`). |
| `timeout_seconds` | `int` | `30` | HTTP request timeout in seconds. |
| `max_response_bytes` | `int` | `1024` | Maximum response body size. |

### Registered Functions

- **`send_slack_message(text: str, channel: str | None = None, blocks: list[dict] | None = None) -> str`** — Send a message to Slack via an incoming webhook. `text` is used as the message body (and fallback when blocks are provided). `channel` overrides the default channel. `blocks` accepts Slack Block Kit blocks for rich formatting.

### Security

- **SSRF protection** — Private/internal IP ranges are blocked via `SSRFSafeTransport`.
- **Env var substitution** — The `webhook_url` supports `${ENV_VAR}` syntax so secrets stay out of YAML files.

### Example

```yaml
# Deploy notifier
tools:
  - type: slack
    webhook_url: ${SLACK_WEBHOOK_URL}
    default_channel: "#deployments"
    username: DeployBot
    icon_emoji: ":rocket:"
  - type: git
    repo_path: .
    read_only: true
```

## Web Scraper Tool

Fetches a web page, converts it to markdown, chunks the content, generates embeddings, and stores the result in the document store. Content stored by the scraper is immediately searchable via `search_documents`.

```yaml
tools:
  - type: web_scraper
    allowed_domains:
      - docs.example.com
      - blog.example.com
    timeout_seconds: 15
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `allowed_domains` | `list[str]` | `[]` | Hostnames the agent may scrape. Empty list allows all (subject to blocked list). |
| `blocked_domains` | `list[str]` | `[]` | Hostnames the agent may not scrape. Ignored when `allowed_domains` is set. |
| `max_content_bytes` | `int` | `512000` | Maximum response size in bytes before truncation. |
| `timeout_seconds` | `int` | `15` | HTTP request timeout in seconds. |
| `user_agent` | `str` | `"initrunner/0.2"` | User-Agent header sent with requests. |

### Registered Functions

- **`scrape_page(url: str) -> str`** — Fetch the URL, convert HTML to markdown, chunk the text, embed each chunk, and store the results in the document store. Returns a confirmation with chunk count and content size. Stored content becomes searchable via the `search_documents` tool.

### Security

- **SSRF protection** — Private/internal IP ranges are blocked via `SSRFSafeTransport`.
- **Domain allow/block lists** — `allowed_domains` restricts scraping to listed hosts; `blocked_domains` provides a blocklist alternative.
- **HTML sanitization** — `<script>`, `<style>`, and `<noscript>` tags are stripped; base64 data URIs are removed.
- **Content size limit** — Responses exceeding `max_content_bytes` are truncated.

### Example

```yaml
# Web monitor agent — scrapes pages on a schedule
tools:
  - type: web_scraper
    allowed_domains:
      - docs.example.com
  - type: datetime
ingest:
  sources: []  # web_scraper populates the store at runtime
triggers:
  - type: cron
    schedule: "0 */6 * * *"
    prompt: "Scrape the changelog and report changes."
```

## Search Tool

Searches the web and news using one of four providers. DuckDuckGo is the default (free, no API key). Paid providers (SerpAPI, Brave, Tavily) require an API key and use `httpx` (bundled).

```yaml
tools:
  - type: search
    provider: duckduckgo     # default
    max_results: 10          # default: 10
    safe_search: true        # default: true
    timeout_seconds: 15      # default: 15
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | `"duckduckgo" \| "serpapi" \| "brave" \| "tavily"` | `"duckduckgo"` | Search provider to use. |
| `api_key` | `str` | `""` | API key for paid providers. Supports `${ENV_VAR}` syntax. Not needed for DuckDuckGo. |
| `max_results` | `int` | `10` | Maximum number of results per search. |
| `safe_search` | `bool` | `true` | Enable safe search filtering. |
| `timeout_seconds` | `int` | `15` | HTTP request timeout in seconds. |

### Registered Functions

- **`web_search(query: str, num_results: int = 5) -> str`** — Search the web for information. Returns a numbered list of results with title, URL, and snippet. `num_results` is clamped to `max_results`.
- **`news_search(query: str, num_results: int = 5, days_back: int = 7) -> str`** — Search for recent news articles. `days_back` controls the time window (mapped to provider-specific time filters).

### Providers

| Provider | Free? | API Key | Notes |
|----------|-------|---------|-------|
| `duckduckgo` | Yes | Not required | Uses `duckduckgo-search` library. Install with `pip install initrunner[search]`. |
| `serpapi` | No | Required (`SERPAPI_API_KEY`) | Google results via SerpAPI. Uses `httpx` (bundled). |
| `brave` | No | Required (`BRAVE_API_KEY`) | Brave Search API. Uses `httpx` (bundled). |
| `tavily` | No | Required (`TAVILY_API_KEY`) | Tavily search API. Uses `httpx` (bundled). |

### Install

DuckDuckGo requires the optional `search` extra:

```bash
pip install initrunner[search]
```

Paid providers use `httpx`, which is already bundled with InitRunner — no extra install needed.

### Example

```yaml
# Research assistant with web and news search
tools:
  - type: search
    provider: duckduckgo
  - type: datetime
```

```yaml
# Using a paid provider
tools:
  - type: search
    provider: brave
    api_key: ${BRAVE_API_KEY}
    max_results: 5
```

## Audio Tool

Fetches YouTube video transcripts and transcribes local audio/video files. YouTube transcripts are pulled from YouTube's caption data (no API key required). Local file transcription sends audio to a multimodal model via PydanticAI.

```yaml
tools:
  - type: audio
    youtube_languages: ["en"]        # default: ["en"]
    include_timestamps: false        # default: false
    transcription_model: null        # default: null (uses the role's model)
    max_audio_mb: 20.0               # default: 20.0
    max_transcript_chars: 50000      # default: 50000
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `youtube_languages` | `list[str]` | `["en"]` | Language codes for YouTube transcripts, in descending priority. Falls back to auto-generated captions if manual ones aren't available. |
| `include_timestamps` | `bool` | `false` | Prefix each transcript segment with its timestamp (e.g. `[5.0s] Hello`). |
| `transcription_model` | `str \| null` | `null` | Model for local audio transcription. Must support audio input (e.g. `openai:gpt-4o-audio-preview`). `null` uses the role's configured model. |
| `max_audio_mb` | `float` | `20.0` | Maximum local audio file size in MB. |
| `max_transcript_chars` | `int` | `50000` | Maximum transcript length. Longer transcripts are truncated with a `[truncated]` marker. |

### Registered Functions

- **`get_youtube_transcript(url: str, language: str = "") -> str`** — Fetch the transcript/captions for a YouTube video. Supports standard, short, and embed URL formats. Pass `language` to override the configured language list for a single call. Falls back to auto-generated captions when manual transcripts aren't available.
- **`transcribe_audio(file_path: str) -> str`** — Transcribe a local audio or video file to text using the configured model. Supported formats: `.mp3`, `.mp4`, `.m4a`, `.wav`, `.ogg`, `.webm`, `.mpeg`, `.flac`.

### Install

The YouTube transcript feature requires the optional `audio` extra:

```bash
pip install initrunner[audio]
# or with uv:
uv sync --extra audio
```

If the package is not installed, `get_youtube_transcript` returns an error message directing the user to install the extra. The `transcribe_audio` function does not require additional packages — it uses PydanticAI's built-in multimodal support.

### YouTube URL Formats

All of the following URL formats are recognized:

- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/embed/VIDEO_ID`
- `https://www.youtube.com/shorts/VIDEO_ID`

### Security

- **File validation** — Local file paths are resolved with `.expanduser().resolve()`. Only files with supported audio extensions are accepted.
- **Size limit** — Files exceeding `max_audio_mb` are rejected before being read into memory.
- **Output bounded** — Transcripts exceeding `max_transcript_chars` are truncated with a `[truncated]` marker.

### Resource Limits

| Tool | Limit | Behavior |
|------|-------|----------|
| `get_youtube_transcript` | `max_transcript_chars` (50 KB default) | Transcript truncated with `[truncated]` |
| `transcribe_audio` | `max_audio_mb` (20 MB default) | File rejected before reading |
| `transcribe_audio` | `max_transcript_chars` (50 KB default) | Output truncated with `[truncated]` |

### Examples

**YouTube transcript agent:**

```yaml
# Fetch and summarize YouTube videos
spec:
  role: You summarize YouTube videos from their transcripts.
  model:
    provider: openai
    name: gpt-4o-mini
  tools:
    - type: audio
      youtube_languages: ["en", "es"]
      include_timestamps: true
```

**Audio transcription agent:**

```yaml
# Transcribe local audio files
spec:
  role: You transcribe and summarize audio recordings.
  model:
    provider: openai
    name: gpt-4o
  tools:
    - type: audio
      transcription_model: openai:gpt-4o-audio-preview
      max_audio_mb: 50.0
```

**Combined with search and web reader:**

```yaml
# Research agent that can watch videos and read the web
spec:
  role: You are a research assistant.
  model:
    provider: openai
    name: gpt-4o
  tools:
    - type: audio
    - type: search
      provider: duckduckgo
    - type: web_reader
```

## Plugin Tools

Any `type` value that is not one of the builtins above is resolved via the plugin registry. Plugins are third-party packages that register new tool types through Python entry points.

```yaml
tools:
  - type: jira           # provided by a hypothetical initrunner-jira package
    base_url: https://mycompany.atlassian.net
    token: ${JIRA_TOKEN}
```

All keys besides `type` are passed as the plugin's config dict. List installed plugins with `initrunner plugins`.

See [Tool Creation Guide](tool_creation.md#plugin-registry) for how to use and create plugins.

## Auto-Registered Tools

### Document Search (from `ingest`)

When `spec.ingest` is configured, InitRunner automatically registers a document search tool:

- **`search_documents(query: str, top_k: int = 5, source: str | None = None) -> str`** — Search ingested documents for relevant content. Returns matching chunks with source attribution and similarity scores. Pass `source` to filter results by exact path or glob pattern (e.g. `"*.md"`).

This tool requires running `initrunner ingest` first. If no documents have been ingested, it returns a message directing the user to run ingestion.

See [Ingestion](../core/ingestion.md) for details on configuring document ingestion.

### Memory Tools (from `memory`)

When `spec.memory` is configured, up to five tools are auto-registered depending on which memory types are enabled:

- **`remember(content: str, category: str = "general") -> str`** — Store a semantic memory (fact/knowledge) with an embedding. Only registered when `semantic.enabled` is `true`.
- **`recall(query: str, top_k: int = 5, memory_types: list[str] | None = None) -> str`** — Search all memory types by semantic similarity. Pass `memory_types` to filter (e.g. `["semantic", "procedural"]`). Always registered.
- **`list_memories(category: str | None = None, limit: int = 20, memory_type: str | None = None) -> str`** — List recent memories, optionally filtered by category or type. Always registered.
- **`learn_procedure(content: str, category: str = "general") -> str`** — Store a procedural memory (policy/pattern). Auto-injected into the system prompt on future runs. Only registered when `procedural.enabled` is `true`.
- **`record_episode(content: str, category: str = "general") -> str`** — Record an episodic memory (what happened). Only registered when `episodic.enabled` is `true`.

See [Memory](../core/memory.md) for details on memory types, consolidation, and configuration.

## Tool Build Order

When an agent is constructed, tools are built in this order:

1. Explicit tools from `spec.tools` (in definition order, including delegate, api, web_scraper, and plugin tools)
2. Auto-retrieval tool (if `spec.ingest` is configured)
3. Memory tools (if `spec.memory` is configured)
