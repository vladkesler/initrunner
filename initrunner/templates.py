"""Role YAML template generators."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _default_model_name(provider: str) -> str:
    if provider == "openai":
        return "gpt-4o-mini"
    if provider == "ollama":
        return "llama3.2"
    return "claude-sonnet-4-5-20250929"


def template_basic(name: str, provider: str) -> str:
    model_name = _default_model_name(provider)
    return f"""\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: {name}
  description: A new InitRunner agent
  tags:
    - general
spec:
  role: |
    You are a helpful assistant.
  model:
    provider: {provider}
    name: {model_name}
    temperature: 0.1
    max_tokens: 4096
  guardrails:
    max_tokens_per_run: 50000
    max_tool_calls: 20
    timeout_seconds: 300
    max_request_limit: 50
    # input_tokens_limit: 100000     # per-run input token cap
    # total_tokens_limit: 200000     # per-run total token cap
    # session_token_budget: 500000   # cumulative REPL session limit
"""


def template_rag(name: str, provider: str) -> str:
    model_name = _default_model_name(provider)
    return f"""\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: {name}
  description: RAG agent with document ingestion
  tags:
    - rag
spec:
  role: |
    You are a knowledge assistant. Use search_documents to find relevant
    content before answering. Always cite your sources.
  model:
    provider: {provider}
    name: {model_name}
    temperature: 0.1
    max_tokens: 4096
  ingest:
    sources:
      - "./docs/**/*.md"
      - "./docs/**/*.txt"
    chunking:
      strategy: fixed
      chunk_size: 512
      chunk_overlap: 50
  guardrails:
    max_tokens_per_run: 50000
    max_tool_calls: 20
    timeout_seconds: 300
    max_request_limit: 50
    # input_tokens_limit: 100000     # per-run input token cap
    # total_tokens_limit: 200000     # per-run total token cap
    # session_token_budget: 500000   # cumulative REPL session limit
"""


def template_daemon(name: str, provider: str) -> str:
    model_name = _default_model_name(provider)
    return f"""\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: {name}
  description: Daemon agent with triggers
  tags:
    - daemon
spec:
  role: |
    You are a monitoring assistant that responds to events.
  model:
    provider: {provider}
    name: {model_name}
    temperature: 0.1
    max_tokens: 4096
  triggers:
    - type: file_watch
      paths: ["./watched"]
      extensions: [".md", ".txt"]
      prompt_template: "File changed: {{path}}. Summarize the changes."
    - type: cron
      schedule: "0 9 * * 1"
      prompt: "Generate weekly status report."
  # sinks:
  #   - type: webhook
  #     url: ${{SLACK_WEBHOOK_URL}}
  #     retry_count: 2
  #   - type: file
  #     path: ./agent-results.jsonl
  #     format: json
  guardrails:
    max_tokens_per_run: 50000
    max_tool_calls: 20
    timeout_seconds: 300
    max_request_limit: 50
    # input_tokens_limit: 100000     # per-run input token cap
    # total_tokens_limit: 200000     # per-run total token cap
    # daemon_token_budget: 2000000        # lifetime limit (resets on restart)
    # daemon_daily_token_budget: 200000   # resets daily (UTC midnight)
"""


def template_memory(name: str, provider: str) -> str:
    model_name = _default_model_name(provider)
    return f"""\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: {name}
  description: Agent with long-term memory
  tags:
    - memory
spec:
  role: |
    You are a helpful assistant with long-term memory.
    Use the remember() tool to save important information.
    Use the recall() tool to search your memories before answering.
    Use the list_memories() tool to browse recent memories.
  model:
    provider: {provider}
    name: {model_name}
    temperature: 0.1
    max_tokens: 4096
  memory:
    max_sessions: 10
    max_memories: 1000
    max_resume_messages: 20
  guardrails:
    max_tokens_per_run: 50000
    max_tool_calls: 20
    timeout_seconds: 300
    max_request_limit: 50
    # input_tokens_limit: 100000     # per-run input token cap
    # total_tokens_limit: 200000     # per-run total token cap
    # session_token_budget: 500000   # cumulative REPL session limit
"""


def template_ollama(name: str, provider: str) -> str:
    # Always use ollama provider for this template, regardless of --provider flag
    model_name = _default_model_name("ollama")
    return f"""\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: {name}
  description: Agent using local Ollama model
  tags:
    - ollama
    - local
spec:
  role: |
    You are a helpful assistant running on a local Ollama model.
  model:
    provider: ollama
    name: {model_name}  # Run: ollama pull {model_name}
    # base_url: http://localhost:11434/v1  # default; override for remote Ollama
    temperature: 0.1
    max_tokens: 4096
  guardrails:
    max_tokens_per_run: 50000
    max_tool_calls: 20
    timeout_seconds: 300
    max_request_limit: 50
    # input_tokens_limit: 100000     # per-run input token cap
    # total_tokens_limit: 200000     # per-run total token cap
    # session_token_budget: 500000   # cumulative REPL session limit
"""


def template_tool(name: str, provider: str) -> str:
    # Returns a Python file, not YAML
    return f'''\
"""Custom tools for InitRunner.

Reference this module in your role.yaml:

  tools:
    - type: custom
      module: {name}
      # function: greet  # omit to auto-discover all public functions
      config:
        greeting: "Hello"

Functions that accept a `tool_config` parameter will receive
the `config` dict from the YAML definition.
"""


def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {{name}}!"


def greet_with_config(name: str, tool_config: dict) -> str:
    """Greet someone using a configurable greeting.

    The tool_config parameter is automatically injected from
    the `config` section of your role YAML — the LLM never sees it.
    """
    greeting = tool_config.get("greeting", "Hello")
    return f"{{greeting}}, {{name}}!"


def add_numbers(a: int, b: int) -> str:
    """Add two numbers together."""
    return str(a + b)
'''


def template_api(name: str, provider: str) -> str:
    model_name = _default_model_name(provider)
    return f"""\
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: {name}
  description: Agent with declarative API tools
  tags:
    - api
spec:
  role: |
    You are a helpful assistant with API access.
    Use the available tools to fetch data from external APIs.
  model:
    provider: {provider}
    name: {model_name}
    temperature: 0.1
    max_tokens: 4096
  tools:
    - type: api
      name: weather
      description: Weather API
      base_url: https://api.example.com
      headers:
        Authorization: "Bearer ${{API_KEY}}"
      endpoints:
        - name: get_weather
          method: GET
          path: "/weather/{{city}}"
          description: Get current weather for a city
          parameters:
            - name: city
              type: string
              required: true
              description: City name
          response_extract: "$.current"
        - name: get_forecast
          method: GET
          path: "/forecast/{{city}}"
          description: Get weather forecast
          parameters:
            - name: city
              type: string
              required: true
              description: City name
            - name: days
              type: integer
              required: false
              default: 3
              description: Number of forecast days
          query_params:
            days: "{{days}}"
  guardrails:
    max_tokens_per_run: 50000
    max_tool_calls: 20
    timeout_seconds: 300
    max_request_limit: 50
    # input_tokens_limit: 100000     # per-run input token cap
    # total_tokens_limit: 200000     # per-run total token cap
    # session_token_budget: 500000   # cumulative REPL session limit
"""


def template_skill(name: str, provider: str) -> str:
    return f"""\
---
name: {name}
description: A reusable skill bundle. Use when the agent needs these capabilities.
compatibility: Requires initrunner
metadata:
  author: ""
  version: "1.0"
# InitRunner extensions — tool configs and requirements
tools:
  - type: filesystem
    root_path: "."
    read_only: true
requires:
  env: []
  bins: []
  # env:
  #   - MY_API_KEY
  # bins:
  #   - jq
---

You have access to the {name} skill capabilities.

## Instructions

- Describe step-by-step how the agent should use these tools
- Include examples of expected inputs and outputs
"""


TEMPLATES: dict[str, Callable[..., str]] = {
    "basic": template_basic,
    "rag": template_rag,
    "daemon": template_daemon,
    "memory": template_memory,
    "ollama": template_ollama,
    "tool": template_tool,
    "api": template_api,
    "skill": template_skill,
}

# --- Tool prompt configs for wizard ---

# Each entry: (field_name, prompt_text, default_value)
TOOL_PROMPT_FIELDS: dict[str, list[tuple[str, str, str]]] = {
    "filesystem": [
        ("root_path", "Root path", "."),
        ("read_only", "Read-only?", "true"),
    ],
    "git": [
        ("repo_path", "Repository path", "."),
        ("read_only", "Read-only?", "true"),
    ],
    "python": [
        ("require_confirmation", "Require confirmation?", "true"),
        ("network_disabled", "Disable network?", "true"),
    ],
    "shell": [
        ("require_confirmation", "Require confirmation?", "true"),
        ("timeout_seconds", "Timeout (seconds)", "30"),
    ],
    "http": [
        ("base_url", "Base URL", "https://api.example.com"),
    ],
    "web_reader": [],
    "sql": [
        ("database", "Database path", "./data.db"),
        ("read_only", "Read-only?", "true"),
    ],
    "datetime": [
        ("default_timezone", "Default timezone", "UTC"),
    ],
    "mcp": [
        ("command", "Server command", ""),
    ],
    "slack": [
        ("webhook_url", "Webhook URL", ""),
    ],
}

# Short descriptions for tool selection menu
TOOL_DESCRIPTIONS: dict[str, str] = {
    "filesystem": "Read/write files",
    "git": "Git operations",
    "python": "Execute Python code",
    "shell": "Run shell commands",
    "http": "HTTP requests",
    "web_reader": "Fetch web pages",
    "sql": "Query SQLite databases",
    "datetime": "Date/time utilities",
    "mcp": "MCP server integration",
    "slack": "Send Slack messages",
}

# Wizard template descriptions
WIZARD_TEMPLATES: dict[str, str] = {
    "basic": "Simple assistant",
    "rag": "Answers from your documents",
    "memory": "Remembers across sessions",
    "daemon": "Runs on schedule / watches files",
    "api": "Declarative REST API tools",
    "blank": "Just the essentials, add everything yourself",
}


def build_role_yaml(
    *,
    name: str,
    description: str = "",
    provider: str = "openai",
    model_name: str | None = None,
    system_prompt: str = "You are a helpful assistant.",
    tools: list[dict[str, Any]] | None = None,
    memory: bool = False,
    ingest: dict[str, Any] | None = None,
    triggers: list[dict[str, Any]] | None = None,
    sinks: list[dict[str, Any]] | None = None,
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> str:
    """Build role YAML programmatically from structured parameters.

    Returns a YAML string ready to write to disk.
    """
    import yaml

    if model_name is None:
        model_name = _default_model_name(provider)

    role: dict[str, Any] = {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {
            "name": name,
            "description": description,
            "tags": [],
        },
        "spec": {
            "role": system_prompt,
            "model": {
                "provider": provider,
                "name": model_name,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            "guardrails": {
                "max_tokens_per_run": 50000,
                "max_tool_calls": 20,
                "timeout_seconds": 300,
                "max_request_limit": 50,
            },
        },
    }

    if tools:
        role["spec"]["tools"] = tools

    if triggers:
        role["spec"]["triggers"] = triggers

    if sinks:
        role["spec"]["sinks"] = sinks

    if memory:
        role["spec"]["memory"] = {
            "max_sessions": 10,
            "max_memories": 1000,
            "max_resume_messages": 20,
        }

    if ingest:
        role["spec"]["ingest"] = ingest

    return yaml.dump(role, default_flow_style=False, sort_keys=False, allow_unicode=True)
