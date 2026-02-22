# Contributing to InitRunner

Thanks for your interest in contributing! This guide covers the basics.

## Reporting Issues

Open a GitHub issue with:

- A clear title and description
- Steps to reproduce (for bugs)
- Your Python version and OS
- The relevant role YAML (if applicable)

**Security vulnerabilities:** please see [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Development Setup

```bash
# Clone and install
git clone https://github.com/vladkesler/initrunner.git
cd initrunner
uv sync

# Run tests
uv run pytest tests/ -v

# Lint and format
uv run ruff check .
uv run ruff format .

# Type check
uv run ty check initrunner/
```

## PR Guidelines

1. Fork the repo and create a feature branch from `main`.
2. Keep changes focused — one logical change per PR.
3. Add tests for new functionality.
4. Ensure all checks pass: `uv run pytest tests/ -v && uv run ruff check . && uv run ruff format --check .`
5. Write a clear PR description explaining what and why.

## Your First Tool Contribution

Tools are self-contained Python files in `initrunner/agent/tools/`. No framework
wiring needed — the registry discovers them automatically.

**Steps:**

1. Create `initrunner/agent/tools/my_tool.py`.
2. Define a config class that extends `ToolConfigBase`:

```python
from typing import Literal
from initrunner.agent.schema.tools import ToolConfigBase

class MyToolConfig(ToolConfigBase):
    type: Literal["my_tool"] = "my_tool"
    # add config fields here
```

3. Write a builder function decorated with `@register_tool` that returns a
   `FunctionToolset`:

```python
from pydantic_ai.toolsets.function import FunctionToolset
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

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
5. Write tests in `tests/agent/tools/test_my_tool.py`.
6. Run all checks: `uv run pytest tests/ -v && uv run ruff check . && uv run ruff format --check .`
7. Open a PR.

**Reference implementations:**

| File | Lines | Why it's useful |
|------|-------|-----------------|
| `datetime_tools.py` | ~43 | Simplest tool — good starting template |
| `http.py` | — | Shows SSRF protection patterns |
| `web_reader.py` | — | Shows domain allowlist configuration |

For the full guide, see [docs/agents/tool_creation.md](docs/agents/tool_creation.md).

## Your First Role YAML Contribution

No Python needed — roles are pure YAML. Start from the hello-world example:

```yaml
# examples/roles/hello-world.yaml (27 lines)
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: hello-world
  description: A friendly greeter agent
  tags: [example, greeting]
  author: InitRunner Team
  version: "1.0.0"
spec:
  role: >
    You are a friendly greeter. Keep your responses short, warm,
    and cheerful.
  model:
    provider: openai
    name: gpt-5-mini
    temperature: 0.8
    max_tokens: 1024
```

Test it locally:

```bash
initrunner run examples/roles/your-role.yaml
```

There are 25+ existing examples in `examples/roles/` for inspiration — browse
them to see tools, triggers, guardrails, and ingestion in action.

## Areas Where We Need Help

- **New tools** — see [TOOL_IDEAS.md](TOOL_IDEAS.md) for a curated list. Look for issues tagged `tool-request` and `good-first-issue`.
- **Example roles** — add new role YAMLs to `examples/roles/`. No Python required.
- **Documentation improvements** — fix typos, clarify guides, add examples to `docs/`.
- **Bug fixes** — check issues tagged `bug` and `good-first-issue`.
- **Test coverage** — we always welcome more tests. Mirror the source layout under `tests/`.

## Architecture

See [CLAUDE.md](CLAUDE.md) for project structure, architecture decisions, and key conventions.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
