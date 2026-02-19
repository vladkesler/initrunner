# Tool Examples — Practical Cookbook

This guide shows how to configure each built-in tool type using real examples from [`examples/roles/`](../examples/roles/). For the full configuration reference (all fields, defaults, types), see [tools.md](tools.md). For writing custom tools and plugins, see [tool_creation.md](tool_creation.md).

Each section shows the relevant YAML snippet, explains key configuration choices, and links to the complete example file.

---

## HTTP Tool — Uptime Monitoring

Make GET requests to a base URL and check endpoint health.

```yaml
tools:
  - type: http
    base_url: https://api.example.com
    allowed_methods:
      - GET
    headers:
      Accept: application/json
```

> `allowed_methods: [GET]` restricts the agent to read-only requests — it cannot POST, PUT, or DELETE. The `base_url` is prepended to every path the agent passes to `http_request()`.

- Full example: [`examples/roles/uptime-monitor.yaml`](../examples/roles/uptime-monitor.yaml)
- Reference: [tools.md — HTTP Tool](tools.md#http-tool)

---

## Slack Tool — Alert Notifications

Post messages to Slack channels via an incoming webhook.

```yaml
tools:
  - type: slack
    webhook_url: "${SLACK_WEBHOOK_URL}"
    default_channel: "#ops-alerts"
    username: Uptime Monitor
    icon_emoji: ":satellite:"
```

> `webhook_url` uses `${VAR}` syntax — the env var is resolved at runtime. This keeps secrets out of version control. `default_channel`, `username`, and `icon_emoji` set the appearance of posted messages.

- Full example: [`examples/roles/uptime-monitor.yaml`](../examples/roles/uptime-monitor.yaml)

---

## SQL Tool — Database Queries

Query a SQLite database with engine-level write protection.

```yaml
tools:
  - type: sql
    database: ./sample.db
    read_only: true
    max_rows: 100
```

> `read_only: true` enables `PRAGMA query_only=ON` at the SQLite engine level — no regex filtering, the engine itself rejects writes. `max_rows` caps result sets to prevent large outputs from consuming context window.

**Setup:** create the database before running:

```bash
sqlite3 sample.db < setup.sql
```

- Full example: [`examples/roles/data-analyst/`](../examples/roles/data-analyst/)
- Reference: [tools.md — Tool Types](tools.md#tool-types)

---

## Python Tool — Code Execution

Execute Python code in an isolated subprocess.

```yaml
tools:
  - type: python
    working_dir: .
    require_confirmation: true
    timeout_seconds: 30
```

> `require_confirmation: true` (the default) prompts the user before each execution — a human-in-the-loop safeguard. Sensitive env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AWS_SECRET`, `DATABASE_URL`) are scrubbed from the subprocess environment. Output is truncated at 100 KB.

- Full example: [`examples/roles/data-analyst/`](../examples/roles/data-analyst/)
- Reference: [tools.md — Tool Types](tools.md#tool-types)

---

## Shell Tool — System Commands

Run shell commands restricted to an explicit allowlist.

```yaml
tools:
  - type: shell
    allowed_commands:
      - kubectl
      - docker
      - curl
      - date
    require_confirmation: false
    timeout_seconds: 30
    working_dir: .
```

> `allowed_commands` is an allowlist — only these binaries can be invoked. `require_confirmation: false` is safe here because the commands are read-only status checks. For write operations, keep the default `true`. The shell tool also has a built-in blocklist (fork bombs, `rm -rf /`, etc.) and scrubs sensitive env vars.

- Full example: [`examples/roles/deploy-notifier.yaml`](../examples/roles/deploy-notifier.yaml)

---

## API Tool — Declarative REST Endpoints

Define REST API endpoints as agent tools using pure YAML. Each endpoint becomes a separate tool with typed parameters.

```yaml
tools:
  - type: api
    name: github
    description: GitHub REST API v3
    base_url: https://api.github.com
    headers:
      Accept: application/vnd.github.v3+json
      User-Agent: initrunner-github-tracker
    auth:
      Authorization: "Bearer ${GITHUB_TOKEN}"
    endpoints:
      - name: list_issues
        method: GET
        path: "/repos/{owner}/{repo}/issues"
        description: List issues in a repository
        parameters:
          - name: owner
            type: string
            required: true
            description: Repository owner (user or org)
          - name: repo
            type: string
            required: true
            description: Repository name
          - name: state
            type: string
            required: false
            default: open
            description: "Filter by state: open, closed, or all"
          - name: labels
            type: string
            required: false
            description: Comma-separated list of label names
        query_params:
          state: "{state}"
          labels: "{labels}"
          per_page: "10"
        response_extract: "$[*].{number,title,state,labels[*].name}"
        timeout: 15
```

> Key features at work: `auth` with `${GITHUB_TOKEN}` env var resolution, `{owner}` and `{repo}` path templating, `query_params` for optional filters, and `response_extract` to return only the fields the agent needs. The full example defines 5 endpoints (list_issues, get_issue, create_issue, add_comment, list_repos).

- Full example: [`examples/roles/github-tracker.yaml`](../examples/roles/github-tracker.yaml)
- Reference: [tools.md — API Tool](tools.md#api-tool)

---

## Custom Tool — Python Module Functions

Load Python functions from a module and register them as agent tools. Type annotations become the parameter schema; docstrings become tool descriptions.

**Role YAML:**

```yaml
tools:
  - type: custom
    module: my_tools
    config:
      prefix: "DEMO"
      source: "custom-tools-demo"
```

**Python module (`my_tools.py`):**

```python
def hash_text(text: str, algorithm: str = "sha256") -> str:
    """Hash text using the specified algorithm (md5, sha1, sha256, sha512)."""
    algo = algorithm.lower()
    if algo not in ("md5", "sha1", "sha256", "sha512"):
        return f"Unsupported algorithm: {algorithm}. Use md5, sha1, sha256, or sha512."
    h = hashlib.new(algo)
    h.update(text.encode())
    return f"{algo}:{h.hexdigest()}"


def lookup_with_config(query: str, tool_config: dict) -> str:
    """Look up a query using the configured prefix and source.

    The tool_config parameter is injected by InitRunner from the role YAML
    and is hidden from the LLM.
    """
    prefix = tool_config.get("prefix", "DEFAULT")
    source = tool_config.get("source", "unknown")
    return f"[{prefix}] Result for '{query}' from source '{source}'"
```

> Two patterns shown: `hash_text` is a plain function — all parameters are exposed to the LLM. `lookup_with_config` accepts `tool_config` — InitRunner injects the `config` dict from the YAML and hides the parameter from the LLM, so it sees only `lookup_with_config(query: str)`. Omitting `function` enables auto-discovery of all public functions in the module.

- Full example: [`examples/roles/custom-tools-demo/`](../examples/roles/custom-tools-demo/)
- Reference: [tools.md — Custom Tool](tools.md#custom-tool), [tool_creation.md — Custom Tools](tool_creation.md#custom-tools)

---

## MCP Tool — Model Context Protocol

Connect to an MCP server and expose its tools to the agent. Three transport types are supported: `stdio` (local process), `sse` (remote SSE), and `streamable-http`.

```yaml
# Uncomment to use GitHub's official MCP server instead of declarative API endpoints:
#
# tools:
#   - type: mcp
#     transport: stdio
#     command: npx
#     args:
#       - -y
#       - "@modelcontextprotocol/server-github"
#     tool_filter:
#       - list_issues
#       - get_issue
#       - create_issue
#       - add_issue_comment
#       - search_repositories
```

> `tool_filter` restricts which tools from the MCP server are exposed to the agent. Without it, all tools are available. This example shows MCP as a drop-in alternative to the declarative API tool for the same GitHub use case.

- Full example (commented section): [`examples/roles/github-tracker.yaml`](../examples/roles/github-tracker.yaml)
- Reference: [tools.md — MCP Tool](tools.md#mcp-tool)

---

## Git Tool — Repository Operations

Subprocess-based git operations with read-only default. Two modes:

**Read-only (code review):**

```yaml
tools:
  - type: git
    repo_path: .
    read_only: true
  - type: filesystem
    root_path: .
    read_only: true
```

> `read_only: true` (the default) registers only read tools: `git_status`, `git_log`, `git_diff`, `git_show`, `git_blame`, `git_changed_files`, `git_list_files`. Paired with a read-only filesystem tool, this is a safe setup for code review.

- Full example: [`examples/roles/code-reviewer.yaml`](../examples/roles/code-reviewer.yaml)

**Write mode (changelog generation):**

```yaml
tools:
  - type: git
    repo_path: .
    read_only: true
  - type: filesystem
    root_path: .
    read_only: false
    allowed_extensions:
      - .md
  - type: datetime
```

> This changelog generator reads git history but writes output via the filesystem tool (restricted to `.md` files). If your agent needs to create commits or tags, set `read_only: false` on the git tool — this unlocks `git_checkout`, `git_commit`, and `git_tag`. Note: `git push` is excluded by design.

- Full examples: [`examples/roles/changelog-generator.yaml`](../examples/roles/changelog-generator.yaml), [`examples/roles/code-reviewer.yaml`](../examples/roles/code-reviewer.yaml)
- Reference: [tools.md — Git Tool](tools.md#git-tool)

---

## Web Scraper Tool — Scrape and Store Web Pages

Fetch web pages, extract content as markdown, and store it in the document store for search.

```yaml
tools:
  - type: web_scraper
    allowed_domains:
      - docs.example.com
  - type: datetime
ingest:
  sources: []  # web_scraper tool populates the store at runtime
triggers:
  - type: cron
    schedule: "0 */6 * * *"
    prompt: |
      Scrape these pages and report any changes:
      - https://docs.example.com/changelog
      - https://docs.example.com/api/reference
```

> `allowed_domains` restricts scraping to the listed hosts — the agent cannot fetch pages from other domains. Content stored by `scrape_page()` lands in the same document store that `search_documents` queries, so you can combine `web_scraper` with an `ingest` section for hybrid local+web RAG. The `datetime` tool lets the agent timestamp its change reports.

- Full example: [`examples/roles/web-monitor.yaml`](../examples/roles/web-monitor.yaml)
- Reference: [tools.md — Web Scraper Tool](tools.md#web-scraper-tool)

---

## Search Tool — Web Research

Search the web and news from inside an agent. DuckDuckGo is the default provider (free, no API key).

```yaml
tools:
  - type: search
  - type: datetime
```

> The `search` tool registers two functions: `web_search` for general queries and `news_search` for recent events. Pair it with `datetime` so the agent can reason about time when filtering news. DuckDuckGo requires the `search` extra (`pip install initrunner[search]`); paid providers (SerpAPI, Brave, Tavily) need an `api_key` but use `httpx` which is already bundled.

- Full example: [`examples/roles/web-searcher.yaml`](../examples/roles/web-searcher.yaml)
- Reference: [tools.md — Search Tool](tools.md#search-tool)

---

## Common Tool Combinations

Proven patterns from the example roles:

| Pattern | Tools | Trigger | Example |
|---------|-------|---------|---------|
| **Monitoring** | http + slack + datetime | cron | [`uptime-monitor.yaml`](../examples/roles/uptime-monitor.yaml) |
| **Data analysis** | sql + python + filesystem | — (interactive) | [`data-analyst/`](../examples/roles/data-analyst/) |
| **DevOps reporting** | shell + git + slack + datetime | cron | [`deploy-notifier.yaml`](../examples/roles/deploy-notifier.yaml) |
| **API integration** | api + datetime | — (interactive) | [`github-tracker.yaml`](../examples/roles/github-tracker.yaml) |
| **Code review** | git + filesystem (both read-only) | — (interactive) | [`code-reviewer.yaml`](../examples/roles/code-reviewer.yaml) |
| **PR review** | git + filesystem (both read-only) | — (one-shot) | [`pr-reviewer.yaml`](../examples/roles/pr-reviewer.yaml) |
| **Slack changelog** | git + shell + datetime | — (one-shot) | [`changelog-slack.yaml`](../examples/roles/changelog-slack.yaml) |
| **CI explainer** | filesystem + git (both read-only) | — (one-shot) | [`ci-explainer.yaml`](../examples/roles/ci-explainer.yaml) |
| **Webhook routing** | http + slack + datetime | webhook | [`webhook-processor.yaml`](../examples/roles/webhook-processor.yaml) |
| **Web monitoring** | web_scraper + datetime | cron | [`web-monitor.yaml`](../examples/roles/web-monitor.yaml) |
| **Changelog** | git + filesystem + datetime | — (interactive) | [`changelog-generator.yaml`](../examples/roles/changelog-generator.yaml) |
| **Web research** | search + datetime | — (interactive) | [`web-searcher.yaml`](../examples/roles/web-searcher.yaml) |
| **Custom utilities** | custom + datetime | — (interactive) | [`custom-tools-demo/`](../examples/roles/custom-tools-demo/) |

---

## Triggers

Triggers run agents automatically on a schedule, file change, or incoming HTTP request. They are configured in `spec.triggers` and used with `initrunner daemon <role.yaml>`.

See [triggers.md](../core/triggers.md) for the full reference.

### Cron

Run on a schedule using cron syntax.

```yaml
triggers:
  - type: cron
    schedule: "*/5 * * * *"
    prompt: "Run the uptime check on all endpoints and report to Slack."
    timezone: UTC
```

> Runs every 5 minutes. The `prompt` is sent to the agent as the user message on each trigger.

- Full example: [`examples/roles/uptime-monitor.yaml`](../examples/roles/uptime-monitor.yaml)

### File Watch

React to file system changes with debouncing.

```yaml
triggers:
  - type: file_watch
    paths:
      - ./knowledge-base
    extensions:
      - .html
      - .md
    prompt_template: "Knowledge base updated: {path}. Re-index."
    debounce_seconds: 1.0
```

> Watches the `./knowledge-base` directory for `.html` and `.md` changes. `prompt_template` supports `{path}` substitution with the changed file path. `debounce_seconds` prevents rapid-fire triggers during bulk edits.

- Full example: [`examples/roles/support-agent/`](../examples/roles/support-agent/)

### Webhook

Listen for incoming HTTP requests.

```yaml
triggers:
  - type: webhook
    path: /webhook
    port: 8080
    method: POST
    rate_limit_rpm: 30
```

> Starts a local HTTP server on port 8080. Incoming `POST /webhook` payloads are passed to the agent as the user message. `rate_limit_rpm` caps throughput to 30 requests per minute.

- Full example: [`examples/roles/webhook-processor.yaml`](../examples/roles/webhook-processor.yaml)

---

## Compose Orchestration

Compose connects multiple agents into a pipeline. Each service runs in its own daemon thread, and `DelegateSink` routes outputs between services via in-memory queues.

```yaml
apiVersion: initrunner/v1
kind: Compose
metadata:
  name: ci-pipeline
  description: >
    CI event processing pipeline. A webhook receiver accepts CI webhooks,
    a build analyzer diagnoses failures, and a notifier sends Slack alerts
    and updates GitHub commit status.
spec:
  services:
    webhook-receiver:
      role: roles/webhook-receiver.yaml
      sink:
        type: delegate
        target: build-analyzer

    build-analyzer:
      role: roles/build-analyzer.yaml
      depends_on:
        - webhook-receiver
      sink:
        type: delegate
        target: notifier

    notifier:
      role: roles/notifier.yaml
      depends_on:
        - build-analyzer
      restart:
        condition: on-failure
        max_retries: 3
        delay_seconds: 5
```

> Three services form a pipeline: `webhook-receiver` → `build-analyzer` → `notifier`. Each `sink` routes the agent's output to the next service's input queue. `depends_on` controls startup order. `restart` with `condition: on-failure` auto-restarts the notifier up to 3 times if it crashes.

```bash
initrunner compose validate examples/compose/ci-pipeline/compose.yaml
initrunner compose up examples/compose/ci-pipeline/compose.yaml
```

---

## CSV Analysis Tool — Tabular Data Exploration

Inspect, summarize, and query CSV files within a sandboxed directory. Uses only Python's stdlib — no extra dependencies required.

```yaml
tools:
  - type: csv_analysis
    root_path: .
    max_rows: 1000
    max_file_size_mb: 10.0
    delimiter: ","
```

> `root_path` is the sandbox boundary — the agent cannot read CSV files outside it. `max_rows` is a hard cap applied on every call to bound memory usage. `max_file_size_mb` rejects oversized files before they are read into memory. Set `delimiter: "\t"` for TSV files.

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `root_path` | `str` | `"."` | Root directory for CSV file access. Paths cannot escape this directory. |
| `max_rows` | `int` | `1000` | Maximum rows read per tool call. |
| `max_file_size_mb` | `float` | `10.0` | Files larger than this (in MB) are rejected before reading. |
| `delimiter` | `str` | `","` | CSV field delimiter. Use `"\t"` for TSV files. |

### Registered tools

- **`inspect_csv(path)`** — Show column names, inferred types (int/float/string), row count, and first 5 rows as a markdown table.
- **`summarize_csv(path, column="")`** — For a named column: numeric stats (min, max, mean, median, stdev) or categorical stats (unique count, top-10 values with counts). Leave `column` empty for a one-liner per column.
- **`query_csv(path, filter_column="", filter_value="", columns="", limit=50)`** — Filter rows by exact match and return a markdown table. `columns` narrows output to a comma-separated subset of fields.

- Full example: [`examples/roles/csv-analyst/`](../../examples/roles/csv-analyst/)
- Reference: [tools.md — Tool Types](tools.md#tool-types)

- Full example: [`examples/compose/ci-pipeline/`](../examples/compose/ci-pipeline/)
