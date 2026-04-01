"""Tests for LangChain AST extraction service."""

from __future__ import annotations

import textwrap

from initrunner.services.langchain_import import (
    KNOWN_TOOL_MAP,
    LangChainImport,
    build_sidecar_module,
    extract_langchain_import,
    validate_sidecar_imports,
)

# ---------------------------------------------------------------------------
# Model extraction
# ---------------------------------------------------------------------------


class TestModelExtraction:
    def test_string_identifier(self):
        source = textwrap.dedent("""\
            from langchain.agents import create_agent
            agent = create_agent("openai:gpt-5", tools=[])
        """)
        result = extract_langchain_import(source)
        assert result.provider == "openai"
        assert result.model_name == "gpt-5"

    def test_string_identifier_model_kwarg(self):
        source = textwrap.dedent("""\
            from langchain.agents import create_agent
            agent = create_agent(model="anthropic:claude-sonnet-4-6", tools=[])
        """)
        result = extract_langchain_import(source)
        assert result.provider == "anthropic"
        assert result.model_name == "claude-sonnet-4-6"

    def test_init_chat_model(self):
        source = textwrap.dedent("""\
            from langchain.chat_models import init_chat_model
            model = init_chat_model(
                "gpt-5", model_provider="openai", temperature=0.7, max_tokens=1000
            )
            from langchain.agents import create_agent
            agent = create_agent(model, tools=[])
        """)
        result = extract_langchain_import(source)
        assert result.provider == "openai"
        assert result.model_name == "gpt-5"
        assert result.temperature == 0.7
        assert result.max_tokens == 1000

    def test_provider_specific_class(self):
        source = textwrap.dedent("""\
            from langchain_anthropic import ChatAnthropic
            model = ChatAnthropic(model="claude-sonnet-4-6", temperature=0.5)
        """)
        result = extract_langchain_import(source)
        assert result.provider == "anthropic"
        assert result.model_name == "claude-sonnet-4-6"
        assert result.temperature == 0.5

    def test_openai_class(self):
        source = textwrap.dedent("""\
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model="gpt-5", max_tokens=2000)
        """)
        result = extract_langchain_import(source)
        assert result.provider == "openai"
        assert result.model_name == "gpt-5"
        assert result.max_tokens == 2000

    def test_ollama_class(self):
        source = textwrap.dedent("""\
            from langchain_community.chat_models import ChatOllama
            model = ChatOllama(model="llama3")
        """)
        result = extract_langchain_import(source)
        assert result.provider == "ollama"
        assert result.model_name == "llama3"

    def test_no_model(self):
        source = "x = 1\n"
        result = extract_langchain_import(source)
        assert result.provider is None
        assert result.model_name is None


# ---------------------------------------------------------------------------
# System prompt extraction
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_system_prompt_kwarg(self):
        source = textwrap.dedent("""\
            from langchain.agents import create_agent
            agent = create_agent(
                model="openai:gpt-5",
                tools=[],
                system_prompt="You are a helpful weather assistant.",
            )
        """)
        result = extract_langchain_import(source)
        assert result.system_prompt == "You are a helpful weather assistant."

    def test_no_system_prompt(self):
        source = textwrap.dedent("""\
            from langchain.agents import create_agent
            agent = create_agent("openai:gpt-5", tools=[])
        """)
        result = extract_langchain_import(source)
        assert result.system_prompt is None


# ---------------------------------------------------------------------------
# Tool extraction
# ---------------------------------------------------------------------------


class TestToolExtraction:
    def test_simple_tool(self):
        source = textwrap.dedent("""\
            from langchain.tools import tool

            @tool
            def get_weather(city: str) -> str:
                \"\"\"Get current weather for a city.\"\"\"
                return f"Sunny in {city}"
        """)
        result = extract_langchain_import(source)
        assert len(result.custom_tools) == 1
        t = result.custom_tools[0]
        assert t.name == "get_weather"
        assert t.description == "Get current weather for a city."
        assert "@tool" not in t.source
        assert "def get_weather" in t.source

    def test_tool_with_custom_name(self):
        source = textwrap.dedent("""\
            from langchain.tools import tool

            @tool("web_search", description="Search the web for info.")
            def search(query: str) -> str:
                \"\"\"Search the web for information.\"\"\"
                return f"Results for: {query}"
        """)
        result = extract_langchain_import(source)
        assert len(result.custom_tools) == 1
        t = result.custom_tools[0]
        assert t.name == "web_search"
        assert t.description == "Search the web for info."

    def test_multiple_tools(self):
        source = textwrap.dedent("""\
            from langchain.tools import tool

            @tool
            def tool_a(x: int) -> int:
                \"\"\"Tool A.\"\"\"
                return x + 1

            @tool
            def tool_b(y: str) -> str:
                \"\"\"Tool B.\"\"\"
                return y.upper()
        """)
        result = extract_langchain_import(source)
        assert len(result.custom_tools) == 2
        names = {t.name for t in result.custom_tools}
        assert names == {"tool_a", "tool_b"}

    def test_known_tool_class(self):
        source = textwrap.dedent("""\
            from langchain_community.tools import DuckDuckGoSearchRun
            search = DuckDuckGoSearchRun()
        """)
        result = extract_langchain_import(source)
        assert "DuckDuckGoSearchRun" in result.known_tools
        assert len(result.custom_tools) == 0

    def test_known_tool_mapping_completeness(self):
        """Ensure all mapped tools resolve to valid InitRunner types."""
        for lc_name, ir_type in KNOWN_TOOL_MAP.items():
            assert isinstance(lc_name, str)
            assert isinstance(ir_type, str)
            assert ir_type  # non-empty

    def test_unknown_tool_class_warning(self):
        source = textwrap.dedent("""\
            from my_lib import CustomSearchTool
            tool = CustomSearchTool()
        """)
        result = extract_langchain_import(source)
        assert any("CustomSearchTool" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Agent kind detection
# ---------------------------------------------------------------------------


class TestAgentKind:
    def test_create_agent_implies_react(self):
        source = textwrap.dedent("""\
            from langchain.agents import create_agent
            agent = create_agent("openai:gpt-5", tools=[])
        """)
        result = extract_langchain_import(source)
        assert result.agent_kind == "react"

    def test_no_agent_creation(self):
        source = textwrap.dedent("""\
            from langchain_openai import ChatOpenAI
            model = ChatOpenAI(model="gpt-5")
        """)
        result = extract_langchain_import(source)
        assert result.agent_kind is None


# ---------------------------------------------------------------------------
# Max iterations
# ---------------------------------------------------------------------------


class TestMaxIterations:
    def test_call_limit_middleware(self):
        source = textwrap.dedent("""\
            from langchain.agents.middleware import CallLimitMiddleware
            middleware = CallLimitMiddleware(max_calls=15)
        """)
        result = extract_langchain_import(source)
        assert result.max_iterations == 15


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema:
    def test_response_format_class(self):
        source = textwrap.dedent("""\
            from pydantic import BaseModel, Field
            from langchain.agents import create_agent

            class ContactInfo(BaseModel):
                name: str = Field(description="Person's name")
                email: str = Field(description="Email address")

            agent = create_agent(model="openai:gpt-5", response_format=ContactInfo)
        """)
        result = extract_langchain_import(source)
        assert result.output_schema_source is not None
        assert "ContactInfo" in result.output_schema_source
        assert "name: str" in result.output_schema_source


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------


class TestStateSchema:
    def test_custom_agent_state(self):
        source = textwrap.dedent("""\
            from langchain.agents import create_agent, AgentState

            class CustomState(AgentState):
                user_id: str
                preferences: dict
        """)
        result = extract_langchain_import(source)
        assert "user_id" in result.state_fields
        assert result.state_fields["user_id"] == "str"


# ---------------------------------------------------------------------------
# Unsupported feature detection
# ---------------------------------------------------------------------------


class TestUnsupportedFeatures:
    def test_lcel_pipe(self):
        source = textwrap.dedent("""\
            from langchain.prompts import ChatPromptTemplate
            chain = prompt | model | parser
        """)
        result = extract_langchain_import(source)
        assert any("LCEL" in w for w in result.warnings)

    def test_langgraph_import(self):
        source = textwrap.dedent("""\
            from langgraph.graph import StateGraph
            graph = StateGraph()
        """)
        result = extract_langchain_import(source)
        assert any("LangGraph" in w for w in result.warnings)

    def test_memory_import(self):
        source = textwrap.dedent("""\
            from langchain.memory import ConversationBufferMemory
            memory = ConversationBufferMemory()
        """)
        result = extract_langchain_import(source)
        assert any("memory" in w.lower() for w in result.warnings)

    def test_retriever_import(self):
        source = textwrap.dedent("""\
            from langchain.vectorstores import FAISS
        """)
        result = extract_langchain_import(source)
        assert any("Retriever" in w or "VectorStore" in w for w in result.warnings)

    def test_callbacks_import(self):
        source = textwrap.dedent("""\
            from langchain.callbacks import StdOutCallbackHandler
        """)
        result = extract_langchain_import(source)
        assert any("callbacks" in w.lower() for w in result.warnings)

    def test_hitl_middleware(self):
        source = textwrap.dedent("""\
            from langchain.agents.middleware import HumanInTheLoopMiddleware
            m = HumanInTheLoopMiddleware()
        """)
        result = extract_langchain_import(source)
        assert any("Human-in-the-loop" in w for w in result.warnings)

    def test_no_warnings_for_clean_agent(self):
        source = textwrap.dedent("""\
            from langchain.agents import create_agent
            from langchain.tools import tool

            @tool
            def greet(name: str) -> str:
                \"\"\"Greet someone.\"\"\"
                return f"Hello {name}"

            agent = create_agent("openai:gpt-5", tools=[greet])
        """)
        result = extract_langchain_import(source)
        assert len(result.warnings) == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_file(self):
        result = extract_langchain_import("")
        assert result.provider is None
        assert len(result.custom_tools) == 0
        assert len(result.known_tools) == 0

    def test_syntax_error(self):
        result = extract_langchain_import("def foo(:\n")
        assert any("parse" in w.lower() for w in result.warnings)

    def test_non_langchain_code(self):
        source = textwrap.dedent("""\
            import json

            def process(data):
                return json.dumps(data)
        """)
        result = extract_langchain_import(source)
        assert result.provider is None
        assert len(result.custom_tools) == 0


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


class TestImportExtraction:
    def test_collects_imports(self):
        source = textwrap.dedent("""\
            import json
            from pathlib import Path
            from langchain.tools import tool
        """)
        result = extract_langchain_import(source)
        assert "import json" in result.raw_imports
        assert "from pathlib import Path" in result.raw_imports


# ---------------------------------------------------------------------------
# Sidecar module generation
# ---------------------------------------------------------------------------


class TestSidecarModule:
    def test_generates_module(self):
        from initrunner.services.langchain_import import LangChainToolDef

        lc = LangChainImport(
            custom_tools=[
                LangChainToolDef(
                    name="greet",
                    description="Greet someone",
                    source=(
                        "def greet(name: str) -> str:\n"
                        '    """Greet someone."""\n'
                        '    return f"Hello {name}"\n'
                    ),
                )
            ],
            raw_imports=["import json", "from langchain.tools import tool"],
        )
        sidecar = build_sidecar_module(lc)
        assert sidecar is not None
        assert "def greet" in sidecar
        assert "import json" in sidecar
        # LangChain imports should be filtered out
        assert "from langchain" not in sidecar

    def test_no_tools_returns_none(self):
        lc = LangChainImport()
        assert build_sidecar_module(lc) is None

    def test_from_full_extraction(self):
        source = textwrap.dedent("""\
            import json
            from langchain.tools import tool

            @tool
            def parse_json(data: str) -> str:
                \"\"\"Parse JSON string.\"\"\"
                return json.dumps(json.loads(data), indent=2)
        """)
        result = extract_langchain_import(source)
        sidecar = build_sidecar_module(result)
        assert sidecar is not None
        assert "import json" in sidecar
        assert "def parse_json" in sidecar
        assert "@tool" not in sidecar
        assert "from langchain" not in sidecar


# ---------------------------------------------------------------------------
# Sidecar import validation
# ---------------------------------------------------------------------------


class TestSidecarValidation:
    def test_clean_module(self):
        source = textwrap.dedent("""\
            import json

            def greet(name: str) -> str:
                return f"Hello {name}"
        """)
        warnings = validate_sidecar_imports(source)
        assert len(warnings) == 0

    def test_blocked_import(self):
        source = textwrap.dedent("""\
            import os

            def list_files(path: str) -> str:
                return str(os.listdir(path))
        """)
        warnings = validate_sidecar_imports(source)
        assert len(warnings) == 1
        assert "os" in warnings[0]

    def test_multiple_blocked(self):
        source = textwrap.dedent("""\
            import subprocess
            import shutil

            def run(cmd: str) -> str:
                return subprocess.check_output(cmd, shell=True).decode()
        """)
        warnings = validate_sidecar_imports(source)
        assert len(warnings) == 2

    def test_syntax_error(self):
        warnings = validate_sidecar_imports("def foo(:\n")
        assert len(warnings) == 1
        assert "syntax" in warnings[0].lower()


# ---------------------------------------------------------------------------
# to_prompt_text
# ---------------------------------------------------------------------------


class TestToPromptText:
    def test_basic_output(self):
        lc = LangChainImport(
            provider="openai",
            model_name="gpt-5",
            system_prompt="You are helpful.",
            agent_kind="react",
            known_tools=["DuckDuckGoSearchRun"],
        )
        text = lc.to_prompt_text()
        assert "openai" in text
        assert "gpt-5" in text
        assert "You are helpful." in text
        assert "react" in text
        assert "DuckDuckGoSearchRun" in text
        assert "search" in text  # mapped type

    def test_empty_import(self):
        lc = LangChainImport()
        text = lc.to_prompt_text()
        assert "Extracted LangChain Agent" in text
