"""Tests for PydanticAI AST extraction service."""

from __future__ import annotations

import textwrap

from initrunner.services._sidecar_common import validate_sidecar_imports
from initrunner.services.pydanticai_import import (
    PydanticAIImport,
    PydanticAIToolDef,
    build_sidecar_module,
    extract_pydanticai_import,
)

# ---------------------------------------------------------------------------
# Model extraction
# ---------------------------------------------------------------------------


class TestModelExtraction:
    def test_string_identifier(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent("openai:gpt-5")
        """)
        result = extract_pydanticai_import(source)
        assert result.provider == "openai"
        assert result.model_name == "gpt-5"

    def test_string_identifier_model_kwarg(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent(model="anthropic:claude-sonnet-4-6")
        """)
        result = extract_pydanticai_import(source)
        assert result.provider == "anthropic"
        assert result.model_name == "claude-sonnet-4-6"

    def test_model_class_openai(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            from pydantic_ai.models.openai import OpenAIModel
            agent = Agent(OpenAIModel("gpt-5"))
        """)
        result = extract_pydanticai_import(source)
        assert result.provider == "openai"
        assert result.model_name == "gpt-5"

    def test_model_class_openai_responses(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            from pydantic_ai.models.openai import OpenAIResponsesModel
            agent = Agent(OpenAIResponsesModel("gpt-5"))
        """)
        result = extract_pydanticai_import(source)
        assert result.provider == "openai"
        assert result.model_name == "gpt-5"

    def test_model_class_gemini(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            from pydantic_ai.models.gemini import GeminiModel
            agent = Agent(GeminiModel("gemini-2.5-pro"))
        """)
        result = extract_pydanticai_import(source)
        assert result.provider == "google"
        assert result.model_name == "gemini-2.5-pro"

    def test_model_settings(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            from pydantic_ai.settings import ModelSettings
            agent = Agent(
                "openai:gpt-5",
                model_settings=ModelSettings(temperature=0.7, max_tokens=4096),
            )
        """)
        result = extract_pydanticai_import(source)
        assert result.provider == "openai"
        assert result.temperature == 0.7
        assert result.max_tokens == 4096

    def test_no_model(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent()
        """)
        result = extract_pydanticai_import(source)
        assert result.provider is None
        assert result.model_name is None

    def test_multiple_agents_first_wins(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            first = Agent("openai:gpt-5")
            second = Agent("anthropic:claude-sonnet-4-6")
        """)
        result = extract_pydanticai_import(source)
        assert result.provider == "openai"
        assert result.model_name == "gpt-5"
        assert result.skipped_agents == ["second"]


# ---------------------------------------------------------------------------
# Prompt extraction
# ---------------------------------------------------------------------------


class TestPromptExtraction:
    def test_system_prompt_kwarg(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent("openai:gpt-5", system_prompt="You are a helpful assistant.")
        """)
        result = extract_pydanticai_import(source)
        assert result.system_prompt == "You are a helpful assistant."

    def test_instructions_kwarg(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent("openai:gpt-5", instructions="Be concise and accurate.")
        """)
        result = extract_pydanticai_import(source)
        assert result.instructions == "Be concise and accurate."

    def test_both_system_prompt_and_instructions(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent(
                "openai:gpt-5",
                system_prompt="You are a coder.",
                instructions="Write clean Python.",
            )
        """)
        result = extract_pydanticai_import(source)
        assert result.system_prompt == "You are a coder."
        assert result.instructions == "Write clean Python."

    def test_system_prompt_decorator_static(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent("openai:gpt-5")

            @agent.system_prompt
            def get_prompt():
                return "You are a research assistant."
        """)
        result = extract_pydanticai_import(source)
        assert result.system_prompt == "You are a research assistant."

    def test_instructions_decorator_dynamic(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent, RunContext
            agent = Agent("openai:gpt-5")

            @agent.instructions
            def get_instructions(ctx: RunContext[str]):
                return f"Context: {ctx.deps}"
        """)
        result = extract_pydanticai_import(source)
        # Dynamic -- should not extract as static
        assert result.instructions is None
        assert len(result.dynamic_prompts) == 1
        assert "ctx.deps" in result.dynamic_prompts[0]

    def test_no_prompt(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent("openai:gpt-5")
        """)
        result = extract_pydanticai_import(source)
        assert result.system_prompt is None
        assert result.instructions is None
        assert result.dynamic_prompts == []


# ---------------------------------------------------------------------------
# Tool extraction
# ---------------------------------------------------------------------------


class TestToolExtraction:
    def test_agent_tool_with_run_context(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent, RunContext
            agent = Agent("openai:gpt-5")

            @agent.tool
            def search(ctx: RunContext[str], query: str) -> str:
                \"\"\"Search the web.\"\"\"
                return f"Results for {query}"
        """)
        result = extract_pydanticai_import(source)
        assert len(result.custom_tools) == 1
        tool = result.custom_tools[0]
        assert tool.name == "search"
        assert tool.description == "Search the web."
        assert "RunContext" not in tool.source
        assert "query: str" in tool.source
        assert not tool.ctx_referenced

    def test_agent_tool_plain(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent("openai:gpt-5")

            @agent.tool_plain
            def add(a: int, b: int) -> int:
                \"\"\"Add two numbers.\"\"\"
                return a + b
        """)
        result = extract_pydanticai_import(source)
        assert len(result.custom_tools) == 1
        assert result.custom_tools[0].name == "add"
        assert "a: int, b: int" in result.custom_tools[0].source

    def test_toolset_tool(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            from pydantic_ai.toolsets.function import FunctionToolset
            ts = FunctionToolset()

            @ts.tool
            def fetch(ctx, url: str) -> str:
                \"\"\"Fetch a URL.\"\"\"
                return ""

            agent = Agent("openai:gpt-5", toolsets=[ts])
        """)
        result = extract_pydanticai_import(source)
        assert len(result.custom_tools) == 1
        assert result.custom_tools[0].name == "fetch"

    def test_tools_kwarg_list(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent

            def greet(name: str) -> str:
                \"\"\"Greet someone.\"\"\"
                return f"Hello {name}"

            agent = Agent("openai:gpt-5", tools=[greet])
        """)
        result = extract_pydanticai_import(source)
        assert len(result.custom_tools) == 1
        assert result.custom_tools[0].name == "greet"
        assert result.custom_tools[0].description == "Greet someone."

    def test_run_context_body_reference(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent, RunContext
            agent = Agent("openai:gpt-5")

            @agent.tool
            def lookup(ctx: RunContext[dict], key: str) -> str:
                \"\"\"Look up a value.\"\"\"
                data = ctx.deps
                return data.get(key, "not found")
        """)
        result = extract_pydanticai_import(source)
        assert len(result.custom_tools) == 1
        tool = result.custom_tools[0]
        assert tool.ctx_referenced is True
        assert "TODO" in tool.source
        assert "ctx.deps was removed" in tool.source

    def test_async_tool(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent("openai:gpt-5")

            @agent.tool_plain
            async def fetch_data(url: str) -> str:
                \"\"\"Fetch data from URL.\"\"\"
                return ""
        """)
        result = extract_pydanticai_import(source)
        assert len(result.custom_tools) == 1
        assert "async def fetch_data" in result.custom_tools[0].source

    def test_no_tools(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent("openai:gpt-5")
        """)
        result = extract_pydanticai_import(source)
        assert result.custom_tools == []


# ---------------------------------------------------------------------------
# Output type extraction
# ---------------------------------------------------------------------------


class TestOutputType:
    def test_bare_pydantic_model(self):
        source = textwrap.dedent("""\
            from pydantic import BaseModel
            from pydantic_ai import Agent

            class WeatherInfo(BaseModel):
                city: str
                temp: float

            agent = Agent("openai:gpt-5", output_type=WeatherInfo)
        """)
        result = extract_pydanticai_import(source)
        assert result.output_type_source is not None
        assert "class WeatherInfo" in result.output_type_source
        assert "city: str" in result.output_type_source

    def test_native_output_wrapper(self):
        source = textwrap.dedent("""\
            from pydantic import BaseModel
            from pydantic_ai import Agent
            from pydantic_ai.output import NativeOutput

            class Result(BaseModel):
                answer: str

            agent = Agent("openai:gpt-5", output_type=NativeOutput(Result))
        """)
        result = extract_pydanticai_import(source)
        assert result.output_type_source is not None
        assert "class Result" in result.output_type_source

    def test_tool_output_wrapper(self):
        source = textwrap.dedent("""\
            from pydantic import BaseModel
            from pydantic_ai import Agent
            from pydantic_ai.output import ToolOutput

            class Data(BaseModel):
                value: int

            agent = Agent("openai:gpt-5", output_type=ToolOutput(Data))
        """)
        result = extract_pydanticai_import(source)
        assert result.output_type_source is not None
        assert "class Data" in result.output_type_source

    def test_text_output_warning(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            from pydantic_ai.output import TextOutput
            agent = Agent("openai:gpt-5", output_type=TextOutput)
        """)
        result = extract_pydanticai_import(source)
        assert result.output_type_source is None
        assert any("TextOutput" in w for w in result.warnings)

    def test_list_output_warning(self):
        source = textwrap.dedent("""\
            from pydantic import BaseModel
            from pydantic_ai import Agent

            class Item(BaseModel):
                name: str

            agent = Agent("openai:gpt-5", output_type=[Item])
        """)
        result = extract_pydanticai_import(source)
        assert result.output_type_source is None
        assert any("Complex output_type" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Usage limits
# ---------------------------------------------------------------------------


class TestUsageLimits:
    def test_with_limits(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent, UsageLimits
            agent = Agent("openai:gpt-5")
            limits = UsageLimits(request_limit=10, tool_calls_limit=50)
        """)
        result = extract_pydanticai_import(source)
        assert result.usage_limits == {"request_limit": 10, "tool_calls_limit": 50}

    def test_without_limits(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent("openai:gpt-5")
        """)
        result = extract_pydanticai_import(source)
        assert result.usage_limits == {}


# ---------------------------------------------------------------------------
# Unsupported features
# ---------------------------------------------------------------------------


class TestUnsupportedFeatures:
    def test_pydantic_graph(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            from pydantic_graph import Graph
            agent = Agent("openai:gpt-5")
        """)
        result = extract_pydanticai_import(source)
        assert any("pydantic-graph" in w for w in result.warnings)

    def test_logfire(self):
        source = textwrap.dedent("""\
            import logfire
            from pydantic_ai import Agent
            agent = Agent("openai:gpt-5")
        """)
        result = extract_pydanticai_import(source)
        assert any("Logfire" in w for w in result.warnings)

    def test_mcp_server(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            from pydantic_ai.mcp import MCPServerStdio
            server = MCPServerStdio("myserver")
            agent = Agent("openai:gpt-5")
        """)
        result = extract_pydanticai_import(source)
        assert any("MCP server" in w for w in result.warnings)

    def test_builtin_tools(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent("openai:gpt-5", builtin_tools=["code_execution"])
        """)
        result = extract_pydanticai_import(source)
        assert any("builtin_tools" in w for w in result.warnings)

    def test_output_validator(self):
        source = textwrap.dedent("""\
            from pydantic_ai import Agent
            agent = Agent("openai:gpt-5")

            @agent.output_validator
            def validate(output):
                return output
        """)
        result = extract_pydanticai_import(source)
        assert any("output_validator" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_file(self):
        result = extract_pydanticai_import("")
        assert result.provider is None
        assert any("No Agent()" in w for w in result.warnings)

    def test_syntax_error(self):
        result = extract_pydanticai_import("def foo(:\n")
        assert any("Could not parse" in w for w in result.warnings)

    def test_non_pydanticai_code(self):
        source = textwrap.dedent("""\
            import json

            def main():
                data = json.loads('{"key": "value"}')
                print(data)
        """)
        result = extract_pydanticai_import(source)
        assert result.provider is None
        assert any("No Agent()" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Sidecar module
# ---------------------------------------------------------------------------


class TestSidecarModule:
    def test_generates_module(self):
        pai = PydanticAIImport(
            custom_tools=[
                PydanticAIToolDef(
                    name="search",
                    description="Search web",
                    source='def search(query: str) -> str:\n    """Search web."""\n    return ""',
                ),
            ],
            raw_imports=["import httpx", "from pydantic_ai import Agent"],
        )
        module = build_sidecar_module(pai)
        assert module is not None
        assert "import httpx" in module
        assert "pydantic_ai" not in module
        assert "def search" in module

    def test_no_tools_returns_none(self):
        pai = PydanticAIImport()
        assert build_sidecar_module(pai) is None

    def test_strips_pydantic_ai_imports(self):
        pai = PydanticAIImport(
            custom_tools=[
                PydanticAIToolDef(name="t", description="", source="def t(): pass"),
            ],
            raw_imports=[
                "from pydantic_ai import Agent",
                "from pydantic_ai.tools import RunContext",
                "import logfire",
                "import requests",
            ],
        )
        module = build_sidecar_module(pai)
        assert module is not None
        assert "pydantic_ai" not in module
        assert "logfire" not in module
        assert "import requests" in module

    def test_ctx_reference_todo(self):
        pai = PydanticAIImport(
            custom_tools=[
                PydanticAIToolDef(
                    name="lookup",
                    description="Look up value",
                    source=(
                        "def lookup(key: str) -> str:\n"
                        "    # TODO: ctx.deps was removed during import -- rewrite this logic\n"
                        '    """Look up value."""\n'
                        "    data = ctx.deps\n"
                        '    return data.get(key, "not found")\n'
                    ),
                    ctx_referenced=True,
                ),
            ],
        )
        module = build_sidecar_module(pai)
        assert module is not None
        assert "TODO: ctx.deps was removed" in module


# ---------------------------------------------------------------------------
# Sidecar validation
# ---------------------------------------------------------------------------


class TestSidecarValidation:
    def test_clean_module(self):
        source = "import json\n\ndef tool():\n    return json.dumps({})\n"
        warnings = validate_sidecar_imports(source)
        assert warnings == []

    def test_blocked_import(self):
        source = "import os\n\ndef tool():\n    return os.getcwd()\n"
        warnings = validate_sidecar_imports(source)
        assert len(warnings) == 1
        assert "os" in warnings[0]

    def test_syntax_error(self):
        warnings = validate_sidecar_imports("def foo(:\n")
        assert len(warnings) == 1
        assert "syntax errors" in warnings[0]


# ---------------------------------------------------------------------------
# Prompt text serialization
# ---------------------------------------------------------------------------


class TestToPromptText:
    def test_basic_output(self):
        pai = PydanticAIImport(
            provider="openai",
            model_name="gpt-5",
            system_prompt="You are a helper.",
            custom_tools=[
                PydanticAIToolDef(name="search", description="Search", source=""),
            ],
        )
        text = pai.to_prompt_text()
        assert "Provider: openai" in text
        assert "Model: gpt-5" in text
        assert "You are a helper." in text
        assert "search: Search" in text

    def test_empty_import(self):
        pai = PydanticAIImport()
        text = pai.to_prompt_text()
        assert "## Extracted PydanticAI Agent" in text
        # Should be minimal
        assert "Provider:" not in text
