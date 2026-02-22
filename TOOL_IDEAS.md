# Tool Ideas

Curated list of tool ideas for contributors. Each tool is a single file in
`initrunner/agent/tools/` — see the [tool creation guide](docs/agents/tool_creation.md)
and [Your First Tool Contribution](CONTRIBUTING.md#your-first-tool-contribution)
for a step-by-step walkthrough.

## Easy

Self-contained tools with no external services. Good first issues.

| Tool | File | What it does |
|------|------|--------------|
| `redis` | `redis_tools.py` | GET / SET / DEL / EXPIRE against a Redis instance |
| `rss` | `rss.py` | Fetch and parse RSS/Atom feeds, return latest entries |
| `calendar` | `calendar_tools.py` | ICS parsing, date math, next-N-events queries |
| `clipboard` | `clipboard.py` | Cross-platform copy/paste via `pyperclip` |
| `yaml` | `yaml_tools.py` | Parse, validate, and pretty-print YAML documents |
| `json` | `json_tools.py` | Parse, query (JSONPath), diff, and format JSON |
| `qr_code` | `qr_code.py` | Generate and decode QR codes |

## Medium

Require API keys or service access. Good for contributors familiar with the tool pattern.

| Tool | File | What it does |
|------|------|--------------|
| `github` | `github.py` | List repos, issues, PRs; create issues; post comments |
| `jira` | `jira.py` | Search issues, create/update tickets, transition status |
| `notion` | `notion.py` | Query databases, create/update pages, search content |
| `s3` | `s3.py` | List buckets/objects, get/put objects, generate presigned URLs |
| `docker` | `docker_tools.py` | List containers/images, start/stop, read logs |
| `slack_bot` | `slack_bot.py` | Post messages, list channels, react — full bot (not just webhooks) |

## Hard

Larger surface area, security considerations, or complex state management.

| Tool | File | What it does |
|------|------|--------------|
| `browser` | `browser.py` | Headless browser automation (Playwright): navigate, screenshot, extract |
| `kubernetes` | `kubernetes.py` | List/describe pods, read logs, scale deployments |
| `database` | `database.py` | Connect to Postgres/MySQL/SQLite, run read-only queries, describe schema |
| `pdf` | `pdf.py` | Extract text/tables from PDFs, merge/split pages |

## How to Get Started

1. Pick an idea from the tables above.
2. Create `initrunner/agent/tools/<file>.py`.
3. Define a config class and register the builder:

```python
from __future__ import annotations

from typing import Literal

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.schema.tools import ToolConfigBase
from initrunner.agent.tools._registry import ToolBuildContext, register_tool


class MyToolConfig(ToolConfigBase):
    type: Literal["my_tool"] = "my_tool"
    # add config fields here


@register_tool("my_tool", MyToolConfig)
def build_my_toolset(config: MyToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    toolset = FunctionToolset()

    @toolset.tool
    def do_something(arg: str) -> str:
        """One-line description for the LLM."""
        return f"result: {arg}"

    return toolset
```

4. Add your config class to `initrunner/agent/schema/tools.py`.
5. Write tests in `tests/agent/tools/test_<file>.py`.
6. Run checks: `uv run pytest tests/ -v && uv run ruff check . && uv run ruff format --check .`
7. Open a PR — see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Have an idea that's not listed? Open an issue with the `tool-request` label.
