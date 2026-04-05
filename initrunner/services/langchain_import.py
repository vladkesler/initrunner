"""AST-based LangChain agent extraction.

Parses a Python source file and extracts model config, system prompt, tools,
agent kind, output schema, guardrails, and unsupported-feature warnings into
an intermediate ``LangChainImport`` dataclass.  All extraction is deterministic
(no LLM calls).
"""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass, field

from initrunner.services._sidecar_common import (
    DEFAULT_BLOCKED_MODULES,
    _assemble_sidecar_source,
    _extract_imports,
    _get_call_name,
    _get_keyword_value,
    _get_number_value,
    _get_string_value,
)
from initrunner.services._sidecar_common import (
    validate_sidecar_imports as validate_sidecar_imports,
)

# ---------------------------------------------------------------------------
# Known LangChain tool class -> InitRunner tool type mapping
# ---------------------------------------------------------------------------

KNOWN_TOOL_MAP: dict[str, str] = {
    "DuckDuckGoSearchRun": "search",
    "DuckDuckGoSearchResults": "search",
    "TavilySearchResults": "search",
    "TavilySearchAPIRetriever": "search",
    "BraveSearchResults": "search",
    "BraveSearch": "search",
    "WikipediaQueryRun": "web_reader",
    "PythonREPLTool": "python",
    "PythonAstREPLTool": "python",
    "ShellTool": "shell",
    "ReadFileTool": "filesystem",
    "WriteFileTool": "filesystem",
    "ListDirectoryTool": "filesystem",
    "CopyFileTool": "filesystem",
    "MoveFileTool": "filesystem",
    "DeleteFileTool": "filesystem",
    "FileSearchTool": "filesystem",
    "RequestsGetTool": "http",
    "RequestsPostTool": "http",
    "RequestsPatchTool": "http",
    "RequestsPutTool": "http",
    "RequestsDeleteTool": "http",
}

# LangChain provider class -> (provider, default_model) mapping
_PROVIDER_CLASS_MAP: dict[str, str] = {
    "ChatOpenAI": "openai",
    "ChatAnthropic": "anthropic",
    "ChatGoogleGenerativeAI": "google",
    "ChatVertexAI": "google",
    "ChatBedrockConverse": "bedrock",
    "ChatFireworks": "fireworks",
    "ChatGroq": "groq",
    "ChatMistralAI": "mistral",
    "ChatCohere": "cohere",
    "ChatOllama": "ollama",
}

# Modules whose presence signals unsupported features
_UNSUPPORTED_MODULES: dict[str, str] = {
    "langgraph": (
        "LangGraph state machine detected. Use InitRunner flow.yaml for multi-step orchestration."
    ),
    "langchain.memory": (
        "LangChain memory not imported. InitRunner memory is persistent and broader"
        " -- configure spec.memory manually if needed."
    ),
    "langchain_community.memory": (
        "LangChain memory not imported. InitRunner memory is persistent and broader"
        " -- configure spec.memory manually if needed."
    ),
}

# Class names that signal unsupported features
_UNSUPPORTED_CLASSES: dict[str, str] = {
    "ConversationBufferMemory": (
        "LangChain memory not imported. InitRunner memory is persistent and broader"
        " -- configure spec.memory manually if needed."
    ),
    "ConversationSummaryMemory": (
        "LangChain memory not imported. InitRunner memory is persistent and broader"
        " -- configure spec.memory manually if needed."
    ),
    "HumanInTheLoopMiddleware": (
        "Human-in-the-loop middleware not imported."
        " Use tool permissions (confirmation: true) instead."
    ),
}

# Re-export for backwards compatibility
_DEFAULT_BLOCKED_MODULES = DEFAULT_BLOCKED_MODULES


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class LangChainToolDef:
    """A single @tool-decorated function extracted from source."""

    name: str
    description: str
    source: str  # function source with @tool decorator stripped


@dataclass
class LangChainImport:
    """Intermediate representation of a parsed LangChain agent."""

    provider: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None
    agent_kind: str | None = None  # "react" if create_agent detected
    max_iterations: int | None = None
    output_schema_source: str | None = None
    custom_tools: list[LangChainToolDef] = field(default_factory=list)
    known_tools: list[str] = field(default_factory=list)
    state_fields: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    raw_imports: list[str] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        """Serialize to structured text for the LLM normalization prompt."""
        lines: list[str] = ["## Extracted LangChain Agent"]

        if self.provider or self.model_name:
            lines.append(f"Provider: {self.provider or 'unknown'}")
            lines.append(f"Model: {self.model_name or 'unknown'}")
        if self.temperature is not None:
            lines.append(f"Temperature: {self.temperature}")
        if self.max_tokens is not None:
            lines.append(f"Max tokens: {self.max_tokens}")

        if self.system_prompt:
            lines.append(f"\nSystem prompt:\n{self.system_prompt}")

        if self.agent_kind:
            lines.append(f"\nAgent kind: {self.agent_kind}")

        if self.max_iterations is not None:
            lines.append(f"Max iterations: {self.max_iterations}")

        if self.known_tools:
            mapped = []
            for t in self.known_tools:
                ir_type = KNOWN_TOOL_MAP.get(t, t)
                mapped.append(f"  - {t} -> type: {ir_type}")
            lines.append("\nKnown tools (mapped to InitRunner types):")
            lines.extend(mapped)

        if self.custom_tools:
            lines.append(f"\nCustom @tool functions ({len(self.custom_tools)}):")
            for t in self.custom_tools:
                lines.append(f"  - {t.name}: {t.description}")

        if self.output_schema_source:
            lines.append(f"\nStructured output schema:\n{self.output_schema_source}")

        if self.state_fields:
            lines.append("\nCustom state fields:")
            for name, type_str in self.state_fields.items():
                lines.append(f"  - {name}: {type_str}")

        if self.warnings:
            lines.append("\nWarnings (features not imported):")
            for w in self.warnings:
                lines.append(f"  - {w}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Model config extraction
# ---------------------------------------------------------------------------


def _extract_model_config(
    tree: ast.Module,
) -> tuple[str | None, str | None, float | None, int | None]:
    """Extract provider, model name, temperature, and max_tokens."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        name = _get_call_name(node)
        if name is None:
            continue

        # create_agent("provider:model", ...) or create_agent(model="provider:model", ...)
        if name in ("create_agent", "agents.create_agent"):
            # First positional arg or model= kwarg
            model_str = None
            if node.args:
                model_str = _get_string_value(node.args[0])
            if model_str is None:
                model_node = _get_keyword_value(node, "model")
                if model_node is not None:
                    model_str = _get_string_value(model_node)

            if model_str and ":" in model_str:
                provider, model_name = model_str.split(":", 1)
                return provider, model_name, None, None
            if model_str:
                return None, model_str, None, None

        # init_chat_model("model-name", model_provider="...", ...)
        if name in ("init_chat_model", "chat_models.init_chat_model"):
            model_name = None
            provider = None
            temp = None
            max_tok = None

            if node.args:
                model_name = _get_string_value(node.args[0])

            prov_node = _get_keyword_value(node, "model_provider")
            if prov_node is not None:
                provider = _get_string_value(prov_node)

            model_node = _get_keyword_value(node, "model")
            if model_node is not None and model_name is None:
                model_name = _get_string_value(model_node)

            temp_node = _get_keyword_value(node, "temperature")
            if temp_node is not None:
                val = _get_number_value(temp_node)
                if val is not None:
                    temp = float(val)

            max_tok_node = _get_keyword_value(node, "max_tokens")
            if max_tok_node is not None:
                val = _get_number_value(max_tok_node)
                if val is not None:
                    max_tok = int(val)

            return provider, model_name, temp, max_tok

        # Provider-specific class: ChatOpenAI(model="gpt-5", temperature=0.7)
        # name might be just "ChatOpenAI" or "langchain_openai.ChatOpenAI"
        class_name = name.rsplit(".", 1)[-1] if "." in name else name
        if class_name in _PROVIDER_CLASS_MAP:
            provider = _PROVIDER_CLASS_MAP[class_name]
            model_name = None
            temp = None
            max_tok = None

            model_node = _get_keyword_value(node, "model")
            if model_node is None:
                model_node = _get_keyword_value(node, "model_name")
            if model_node is not None:
                model_name = _get_string_value(model_node)
            elif node.args:
                model_name = _get_string_value(node.args[0])

            temp_node = _get_keyword_value(node, "temperature")
            if temp_node is not None:
                val = _get_number_value(temp_node)
                if val is not None:
                    temp = float(val)

            max_tok_node = _get_keyword_value(node, "max_tokens")
            if max_tok_node is not None:
                val = _get_number_value(max_tok_node)
                if val is not None:
                    max_tok = int(val)

            return provider, model_name, temp, max_tok

    return None, None, None, None


def _extract_system_prompt(tree: ast.Module) -> str | None:
    """Extract system_prompt= from create_agent() call."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _get_call_name(node)
        if name not in ("create_agent", "agents.create_agent"):
            continue

        prompt_node = _get_keyword_value(node, "system_prompt")
        if prompt_node is not None:
            return _get_string_value(prompt_node)

    return None


def _extract_tools(tree: ast.Module, source: str) -> tuple[list[LangChainToolDef], list[str]]:
    """Extract @tool functions and recognized tool class instantiations."""
    custom_tools: list[LangChainToolDef] = []
    known_tools: list[str] = []
    source_lines = source.splitlines(keepends=True)

    # Find @tool decorated functions
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        is_tool = False
        tool_name: str | None = None
        tool_desc: str | None = None

        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "tool":
                is_tool = True
            elif isinstance(dec, ast.Attribute) and dec.attr == "tool":
                is_tool = True
            elif isinstance(dec, ast.Call):
                dec_name = _get_call_name(dec)
                if dec_name and dec_name.endswith("tool"):
                    is_tool = True
                    # @tool("custom_name", description="...")
                    if dec.args:
                        tool_name = _get_string_value(dec.args[0])
                    desc_node = _get_keyword_value(dec, "description")
                    if desc_node is not None:
                        tool_desc = _get_string_value(desc_node)

        if not is_tool:
            continue

        name = tool_name or node.name
        # Extract docstring as description
        description = tool_desc or ast.get_docstring(node) or ""

        # Extract function source, stripping @tool decorator(s)
        func_start = node.lineno - 1  # 0-indexed
        func_end = node.end_lineno or func_start + 1
        func_lines = source_lines[func_start:func_end]

        # Strip decorator lines
        cleaned_lines: list[str] = []
        in_decorator = False
        for line in func_lines:
            stripped = line.lstrip()
            if stripped.startswith("@"):
                # Check if this is the @tool decorator
                if "tool" in stripped:
                    in_decorator = True
                    # Multi-line decorator check
                    if stripped.rstrip().endswith(")") or "(" not in stripped:
                        in_decorator = False
                    continue
                cleaned_lines.append(line)
            elif in_decorator:
                # Continuation of multi-line decorator
                if stripped.rstrip().endswith(")"):
                    in_decorator = False
                continue
            else:
                cleaned_lines.append(line)

        func_source = textwrap.dedent("".join(cleaned_lines))

        custom_tools.append(
            LangChainToolDef(name=name, description=description, source=func_source)
        )

    # Find known tool class instantiations
    seen_tools: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _get_call_name(node)
        if name is None:
            continue
        class_name = name.rsplit(".", 1)[-1] if "." in name else name
        if class_name in KNOWN_TOOL_MAP and class_name not in seen_tools:
            known_tools.append(class_name)
            seen_tools.add(class_name)

    return custom_tools, known_tools


def _extract_agent_kind(tree: ast.Module) -> str | None:
    """Detect agent construction pattern."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _get_call_name(node)
        if name in ("create_agent", "agents.create_agent"):
            return "react"
    return None


def _extract_output_schema(tree: ast.Module, source: str) -> str | None:
    """Extract response_format= schema class source."""
    source_lines = source.splitlines(keepends=True)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _get_call_name(node)
        if name not in ("create_agent", "agents.create_agent"):
            continue

        fmt_node = _get_keyword_value(node, "response_format")
        if fmt_node is None:
            continue

        # Find the referenced class name
        schema_name: str | None = None
        if isinstance(fmt_node, ast.Name):
            schema_name = fmt_node.id
        elif isinstance(fmt_node, ast.Call):
            # ToolStrategy(MySchema) or similar
            inner_name = _get_call_name(fmt_node)
            if inner_name and fmt_node.args:
                if isinstance(fmt_node.args[0], ast.Name):
                    schema_name = fmt_node.args[0].id

        if schema_name is None:
            return None

        # Find the class definition in source
        for cls_node in ast.walk(tree):
            if isinstance(cls_node, ast.ClassDef) and cls_node.name == schema_name:
                start = cls_node.lineno - 1
                end = cls_node.end_lineno or start + 1
                return textwrap.dedent("".join(source_lines[start:end]))

    return None


def _extract_max_iterations(tree: ast.Module) -> int | None:
    """Extract max_iterations from middleware or agent config."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _get_call_name(node)
        if name is None:
            continue

        # CallLimitMiddleware(max_calls=20) or similar
        class_name = name.rsplit(".", 1)[-1] if "." in name else name
        if "limit" in class_name.lower() or "iteration" in class_name.lower():
            for kw_name in ("max_calls", "max_iterations"):
                val_node = _get_keyword_value(node, kw_name)
                if val_node is not None:
                    val = _get_number_value(val_node)
                    if val is not None:
                        return int(val)

    return None


def _extract_state_schema(tree: ast.Module) -> dict[str, str]:
    """Find custom AgentState subclass fields."""
    fields: dict[str, str] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # Check if it inherits from AgentState
        for base in node.bases:
            base_name = None
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            if base_name != "AgentState":
                continue

            # Extract annotated fields
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    type_str = ast.dump(item.annotation) if item.annotation else "Any"
                    # Try to get a readable type string
                    if isinstance(item.annotation, ast.Name):
                        type_str = item.annotation.id
                    elif isinstance(item.annotation, ast.Constant):
                        type_str = str(item.annotation.value)
                    fields[item.target.id] = type_str

    return fields


def _detect_unsupported(tree: ast.Module) -> list[str]:
    """Detect unsupported LangChain features and return warning messages."""
    warnings: list[str] = []
    seen: set[str] = set()

    # Check imports for unsupported modules
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for mod_prefix, warning in _UNSUPPORTED_MODULES.items():
                if node.module.startswith(mod_prefix) and warning not in seen:
                    warnings.append(warning)
                    seen.add(warning)
        if isinstance(node, ast.Import):
            for alias in node.names:
                for mod_prefix, warning in _UNSUPPORTED_MODULES.items():
                    if alias.name.startswith(mod_prefix) and warning not in seen:
                        warnings.append(warning)
                        seen.add(warning)

    # Check for unsupported class instantiations
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _get_call_name(node)
            if name is not None:
                class_name = name.rsplit(".", 1)[-1] if "." in name else name
                if class_name in _UNSUPPORTED_CLASSES:
                    warning = _UNSUPPORTED_CLASSES[class_name]
                    if warning not in seen:
                        warnings.append(warning)
                        seen.add(warning)

    # Detect LCEL pipe operators (a | b)
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            warning = (
                "LCEL pipeline detected but not importable."
                " Describe the chain logic in spec.role instead."
            )
            if warning not in seen:
                warnings.append(warning)
                seen.add(warning)
            break

    # Detect retriever/vectorstore usage
    retriever_pattern = re.compile(r"retriever|vectorstore|vector_store", re.IGNORECASE)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if retriever_pattern.search(node.module):
                warning = (
                    "Retriever/VectorStore detected."
                    " Configure spec.ingest for InitRunner's RAG pipeline."
                )
                if warning not in seen:
                    warnings.append(warning)
                    seen.add(warning)

    # Detect callback handlers
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if "callbacks" in node.module:
                warning = "LangChain callbacks not imported. Use spec.observability for tracing."
                if warning not in seen:
                    warnings.append(warning)
                    seen.add(warning)

    return warnings


# ---------------------------------------------------------------------------
# Sidecar module generation
# ---------------------------------------------------------------------------


_LC_PREFIXES = ("langchain", "langgraph", "langsmith")


def build_sidecar_module(lc_import: LangChainImport) -> str | None:
    """Assemble extracted @tool functions into a standalone Python module.

    Returns the module source text, or None if no custom tools exist.
    """
    if not lc_import.custom_tools:
        return None

    return _assemble_sidecar_source(
        framework_label="LangChain",
        framework_prefixes=_LC_PREFIXES,
        raw_imports=lc_import.raw_imports,
        tool_sources=[t.source for t in lc_import.custom_tools],
    )


# validate_sidecar_imports is imported from _sidecar_common at the top of this module
# and re-exported for backwards compatibility.


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def extract_langchain_import(source: str) -> LangChainImport:
    """Parse Python source and extract LangChain agent configuration.

    All extraction is deterministic (pure AST analysis, no LLM).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return LangChainImport(warnings=[f"Could not parse Python source: {e}"])

    provider, model_name, temperature, max_tokens = _extract_model_config(tree)
    system_prompt = _extract_system_prompt(tree)
    custom_tools, known_tools = _extract_tools(tree, source)
    agent_kind = _extract_agent_kind(tree)
    output_schema = _extract_output_schema(tree, source)
    max_iterations = _extract_max_iterations(tree)
    state_fields = _extract_state_schema(tree)
    raw_imports = _extract_imports(tree)
    warnings = _detect_unsupported(tree)

    # Warn about unknown tool classes
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _get_call_name(node)
        if name is None:
            continue
        class_name = name.rsplit(".", 1)[-1] if "." in name else name
        # Heuristic: ends with "Tool" but not in our map
        if (
            class_name.endswith("Tool")
            and class_name not in KNOWN_TOOL_MAP
            and class_name != "tool"
        ):
            warnings.append(
                f"Unknown tool '{class_name}' skipped. Add manually or use type: custom."
            )

    return LangChainImport(
        provider=provider,
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
        agent_kind=agent_kind,
        max_iterations=max_iterations,
        output_schema_source=output_schema,
        custom_tools=custom_tools,
        known_tools=known_tools,
        state_fields=state_fields,
        warnings=warnings,
        raw_imports=raw_imports,
    )
