"""AST-based PydanticAI agent extraction.

Parses a Python source file and extracts model config, system prompt,
instructions, tools, output type, usage limits, and unsupported-feature
warnings into an intermediate ``PydanticAIImport`` dataclass.  All extraction
is deterministic (no LLM calls).
"""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass, field

from initrunner.services._sidecar_common import validate_sidecar_imports as validate_sidecar_imports

# Re-export so callers can import from here
__all__ = [
    "PydanticAIImport",
    "PydanticAIToolDef",
    "build_sidecar_module",
    "extract_pydanticai_import",
    "validate_sidecar_imports",
]

# ---------------------------------------------------------------------------
# PydanticAI model class -> InitRunner provider mapping
# ---------------------------------------------------------------------------

_MODEL_CLASS_MAP: dict[str, str] = {
    "OpenAIModel": "openai",
    "OpenAIChatModel": "openai",
    "OpenAIResponsesModel": "openai",
    "AnthropicModel": "anthropic",
    "GeminiModel": "google",
    "GoogleModel": "google",
    "GroqModel": "groq",
    "MistralModel": "mistral",
    "BedrockConverseModel": "bedrock",
    "CohereModel": "cohere",
    "XAIModel": "xai",
}

# output_type wrappers that contain an inner schema reference
_OUTPUT_WRAPPERS: set[str] = {"NativeOutput", "PromptedOutput", "ToolOutput"}

# Non-portable output types
_UNSUPPORTED_OUTPUT_TYPES: set[str] = {"TextOutput", "StructuredDict"}

# Modules whose presence signals unsupported features
_UNSUPPORTED_MODULES: dict[str, str] = {
    "pydantic_graph": (
        "pydantic-graph state machine detected."
        " Use InitRunner compose.yaml for multi-step orchestration."
    ),
    "logfire": ("Logfire instrumentation detected. Use spec.observability instead."),
}

# Class names that signal unsupported features
_UNSUPPORTED_CLASSES: dict[str, str] = {
    "MCPServerStdio": "MCP server detected. Use type: mcp in tools instead.",
    "MCPServerSSE": "MCP server detected. Use type: mcp in tools instead.",
    "MCPServerHTTP": "MCP server detected. Use type: mcp in tools instead.",
    "MCPServerStreamableHTTP": "MCP server detected. Use type: mcp in tools instead.",
}

# PydanticAI import prefixes to strip from sidecar modules
_PAI_PREFIXES = ("pydantic_ai", "pydantic_graph", "logfire")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PydanticAIToolDef:
    """A single tool function extracted from source."""

    name: str
    description: str
    source: str  # function source with decorator + RunContext stripped
    ctx_referenced: bool = False  # True if stripped ctx var is still used in body


@dataclass
class PydanticAIImport:
    """Intermediate representation of a parsed PydanticAI agent."""

    provider: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None
    instructions: str | None = None
    dynamic_prompts: list[str] = field(default_factory=list)
    output_type_source: str | None = None
    usage_limits: dict[str, int] = field(default_factory=dict)
    custom_tools: list[PydanticAIToolDef] = field(default_factory=list)
    skipped_agents: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_imports: list[str] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        """Serialize to structured text for the LLM normalization prompt."""
        lines: list[str] = ["## Extracted PydanticAI Agent"]

        if self.provider or self.model_name:
            lines.append(f"Provider: {self.provider or 'unknown'}")
            lines.append(f"Model: {self.model_name or 'unknown'}")
        if self.temperature is not None:
            lines.append(f"Temperature: {self.temperature}")
        if self.max_tokens is not None:
            lines.append(f"Max tokens: {self.max_tokens}")

        if self.system_prompt:
            lines.append(f"\nSystem prompt:\n{self.system_prompt}")

        if self.instructions:
            lines.append(f"\nInstructions:\n{self.instructions}")

        if self.dynamic_prompts:
            lines.append(f"\nDynamic prompt functions ({len(self.dynamic_prompts)}):")
            for src in self.dynamic_prompts:
                lines.append(f"```\n{src}\n```")

        if self.usage_limits:
            lines.append("\nUsage limits:")
            for k, v in self.usage_limits.items():
                lines.append(f"  - {k}: {v}")

        if self.custom_tools:
            lines.append(f"\nCustom tool functions ({len(self.custom_tools)}):")
            for t in self.custom_tools:
                lines.append(f"  - {t.name}: {t.description}")

        if self.output_type_source:
            lines.append(f"\nStructured output schema:\n{self.output_type_source}")

        if self.skipped_agents:
            lines.append(f"\nSkipped agents (not imported): {', '.join(self.skipped_agents)}")

        if self.warnings:
            lines.append("\nWarnings (features not imported):")
            for w in self.warnings:
                lines.append(f"  - {w}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# AST extraction helpers
# ---------------------------------------------------------------------------


def _get_string_value(node: ast.expr) -> str | None:
    """Extract a string constant from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _get_number_value(node: ast.expr) -> float | int | None:
    """Extract a numeric constant from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    return None


def _get_keyword_value(call: ast.Call, name: str) -> ast.expr | None:
    """Find a keyword argument by name in a Call node."""
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _get_call_name(node: ast.Call) -> str | None:
    """Get the full dotted name of a Call (e.g. 'Agent', 'OpenAIModel')."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        parts: list[str] = []
        current: ast.expr = node.func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return None


# ---------------------------------------------------------------------------
# Agent discovery
# ---------------------------------------------------------------------------


def _find_agent_assignments(tree: ast.Module) -> list[tuple[str, ast.Call]]:
    """Find all ``name = Agent(...)`` assignments in source order.

    Returns (variable_name, Call_node) tuples.
    """
    agents: list[tuple[str, ast.Call]] = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        call_name = _get_call_name(node.value)
        if call_name is None:
            continue
        # Match Agent(...) or pydantic_ai.Agent(...)
        bare = call_name.rsplit(".", 1)[-1] if "." in call_name else call_name
        if bare != "Agent":
            continue
        # Get the assignment target name
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            agents.append((node.targets[0].id, node.value))
    return agents


def _find_toolset_variables(tree: ast.Module) -> set[str]:
    """Find variable names assigned to FunctionToolset() calls."""
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        call_name = _get_call_name(node.value)
        if call_name is None:
            continue
        bare = call_name.rsplit(".", 1)[-1] if "." in call_name else call_name
        if bare == "FunctionToolset":
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                names.add(node.targets[0].id)
    return names


# ---------------------------------------------------------------------------
# Model extraction
# ---------------------------------------------------------------------------


def _extract_model_config(
    agent_call: ast.Call, tree: ast.Module
) -> tuple[str | None, str | None, float | None, int | None]:
    """Extract provider, model name, temperature, and max_tokens."""
    provider: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None

    # 1. Model from Agent() -- first positional arg or model= kwarg
    model_node: ast.expr | None = None
    if agent_call.args:
        model_node = agent_call.args[0]
    if model_node is None:
        model_node = _get_keyword_value(agent_call, "model")

    if model_node is not None:
        # String literal: "openai:gpt-5"
        model_str = _get_string_value(model_node)
        if model_str:
            if ":" in model_str:
                provider, model_name = model_str.split(":", 1)
            else:
                model_name = model_str

        # Model class instantiation: OpenAIModel("gpt-5")
        elif isinstance(model_node, ast.Call):
            cls_name = _get_call_name(model_node)
            if cls_name:
                bare = cls_name.rsplit(".", 1)[-1] if "." in cls_name else cls_name
                if bare in _MODEL_CLASS_MAP:
                    provider = _MODEL_CLASS_MAP[bare]
                    if model_node.args:
                        model_name = _get_string_value(model_node.args[0])
                    if model_name is None:
                        mn = _get_keyword_value(model_node, "model_name")
                        if mn is not None:
                            model_name = _get_string_value(mn)

    # 2. ModelSettings -- from Agent kwarg or standalone
    ms_call = _find_model_settings(agent_call, tree)
    if ms_call is not None:
        temp_node = _get_keyword_value(ms_call, "temperature")
        if temp_node is not None:
            val = _get_number_value(temp_node)
            if val is not None:
                temperature = float(val)
        max_tok_node = _get_keyword_value(ms_call, "max_tokens")
        if max_tok_node is not None:
            val = _get_number_value(max_tok_node)
            if val is not None:
                max_tokens = int(val)

    return provider, model_name, temperature, max_tokens


def _find_model_settings(agent_call: ast.Call, tree: ast.Module) -> ast.Call | None:
    """Find ModelSettings() -- either as Agent kwarg or standalone in module."""
    ms_node = _get_keyword_value(agent_call, "model_settings")
    if ms_node is not None and isinstance(ms_node, ast.Call):
        name = _get_call_name(ms_node)
        if name and name.rsplit(".", 1)[-1] == "ModelSettings":
            return ms_node

    # Search for standalone ModelSettings(...) calls
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _get_call_name(node)
        if name and name.rsplit(".", 1)[-1] == "ModelSettings":
            return node

    return None


# ---------------------------------------------------------------------------
# Prompt extraction
# ---------------------------------------------------------------------------


def _extract_prompts(
    agent_call: ast.Call,
    tree: ast.Module,
    source: str,
    agent_var: str,
) -> tuple[str | None, str | None, list[str]]:
    """Extract system_prompt, instructions, and dynamic prompt function sources.

    Returns (system_prompt, instructions, dynamic_prompts).
    """
    source_lines = source.splitlines(keepends=True)
    system_prompt: str | None = None
    instructions: str | None = None
    dynamic_prompts: list[str] = []

    # 1. system_prompt= kwarg (string or list of strings)
    sp_node = _get_keyword_value(agent_call, "system_prompt")
    if sp_node is not None:
        system_prompt = _get_string_value(sp_node)

    # 2. instructions= kwarg
    inst_node = _get_keyword_value(agent_call, "instructions")
    if inst_node is not None:
        instructions = _get_string_value(inst_node)

    # 3. @agent_var.system_prompt and @agent_var.instructions decorators
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        decorator_kind = _match_prompt_decorator(node, agent_var)
        if decorator_kind is None:
            continue

        # Try to extract static return value
        static_str = _extract_static_return(node)
        if static_str is not None:
            if decorator_kind == "system_prompt" and system_prompt is None:
                system_prompt = static_str
            elif decorator_kind == "instructions" and instructions is None:
                instructions = static_str
        else:
            # Dynamic -- store function source
            start = node.lineno - 1
            end = node.end_lineno or start + 1
            func_src = textwrap.dedent("".join(source_lines[start:end]))
            dynamic_prompts.append(func_src)

    return system_prompt, instructions, dynamic_prompts


def _match_prompt_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef, agent_var: str
) -> str | None:
    """Check if function has @agent_var.system_prompt or @agent_var.instructions.

    Returns the decorator kind or None.
    """
    for dec in node.decorator_list:
        attr_name: str | None = None
        obj_name: str | None = None
        if isinstance(dec, ast.Attribute):
            attr_name = dec.attr
            if isinstance(dec.value, ast.Name):
                obj_name = dec.value.id
        elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            attr_name = dec.func.attr
            if isinstance(dec.func.value, ast.Name):
                obj_name = dec.func.value.id

        if obj_name == agent_var and attr_name in ("system_prompt", "instructions"):
            return attr_name
    return None


def _extract_static_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """If function body is a single return with a string literal, extract it."""
    body = node.body
    # Skip docstring
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    if len(body) == 1 and isinstance(body[0], ast.Return) and body[0].value is not None:
        return _get_string_value(body[0].value)
    return None


# ---------------------------------------------------------------------------
# Output type extraction
# ---------------------------------------------------------------------------


def _extract_output_type(
    agent_call: ast.Call,
    tree: ast.Module,
    source: str,
    warnings: list[str],
) -> str | None:
    """Extract output_type= and return the schema class source if found."""
    source_lines = source.splitlines(keepends=True)
    ot_node = _get_keyword_value(agent_call, "output_type")
    if ot_node is None:
        return None

    schema_name: str | None = None

    if isinstance(ot_node, ast.Name):
        name = ot_node.id
        if name in _UNSUPPORTED_OUTPUT_TYPES:
            warnings.append(f"output_type={name} is not directly portable to InitRunner.")
            return None
        schema_name = name

    elif isinstance(ot_node, ast.Call):
        call_name = _get_call_name(ot_node)
        if call_name:
            bare = call_name.rsplit(".", 1)[-1] if "." in call_name else call_name
            if bare in _OUTPUT_WRAPPERS:
                # Unwrap: NativeOutput(MySchema) -> MySchema
                if ot_node.args and isinstance(ot_node.args[0], ast.Name):
                    schema_name = ot_node.args[0].id
                else:
                    warnings.append(f"Could not unwrap output_type={bare}(...) argument.")
                    return None
            elif bare in _UNSUPPORTED_OUTPUT_TYPES:
                warnings.append(f"output_type={bare}(...) is not directly portable to InitRunner.")
                return None

    elif isinstance(ot_node, (ast.Subscript, ast.List, ast.Tuple)):
        warnings.append("Complex output_type (list/union) is not directly portable to InitRunner.")
        return None

    if schema_name is None:
        return None

    # Find the class definition in source
    for cls_node in ast.walk(tree):
        if isinstance(cls_node, ast.ClassDef) and cls_node.name == schema_name:
            start = cls_node.lineno - 1
            end = cls_node.end_lineno or start + 1
            return textwrap.dedent("".join(source_lines[start:end]))

    return None


# ---------------------------------------------------------------------------
# Tool extraction
# ---------------------------------------------------------------------------


_RUNCONTEXT_RE = re.compile(
    r"^(\s*(?:async\s+)?def\s+\w+\s*\()"  # up to opening paren (sync or async)
    r"\s*\w+\s*:\s*RunContext\[?[^\]]*\]?\s*,?\s*"  # RunContext param
    r"(.*\)\s*(?:->.*)?:\s*)$",  # rest of signature
    re.DOTALL,
)

_RUNCONTEXT_PARAM_NAME_RE = re.compile(r"^\s*(?:async\s+)?def\s+\w+\s*\(\s*(\w+)\s*:\s*RunContext")


def _extract_tools(
    tree: ast.Module,
    source: str,
    agent_var: str,
    toolset_vars: set[str],
) -> list[PydanticAIToolDef]:
    """Extract tool functions from decorators and Agent(tools=[...]) kwarg."""
    source_lines = source.splitlines(keepends=True)
    tools: list[PydanticAIToolDef] = []
    seen_names: set[str] = set()

    # 1. Find decorated tool functions
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        if not _is_tool_decorated(node, agent_var, toolset_vars):
            continue

        tool_def = _extract_single_tool(node, source_lines)
        if tool_def is not None and tool_def.name not in seen_names:
            tools.append(tool_def)
            seen_names.add(tool_def.name)

    # 2. Find functions referenced in Agent(tools=[func1, func2])
    agent_assignments = _find_agent_assignments(tree)
    if agent_assignments:
        _, agent_call = agent_assignments[0]
        tools_node = _get_keyword_value(agent_call, "tools")
        if isinstance(tools_node, (ast.List, ast.Tuple)):
            for elt in tools_node.elts:
                if isinstance(elt, ast.Name) and elt.id not in seen_names:
                    # Find function definition by name
                    func_node = _find_function_def(tree, elt.id)
                    if func_node is not None:
                        tool_def = _extract_single_tool(func_node, source_lines)
                        if tool_def is not None:
                            tools.append(tool_def)
                            seen_names.add(tool_def.name)

    return tools


def _is_tool_decorated(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    agent_var: str,
    toolset_vars: set[str],
) -> bool:
    """Check if function has @agent_var.tool, @agent_var.tool_plain,
    @toolset_var.tool, or @toolset_var.tool_plain decorator.
    """
    target_vars = {agent_var} | toolset_vars
    for dec in node.decorator_list:
        attr_name: str | None = None
        obj_name: str | None = None
        if isinstance(dec, ast.Attribute):
            attr_name = dec.attr
            if isinstance(dec.value, ast.Name):
                obj_name = dec.value.id
        elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            attr_name = dec.func.attr
            if isinstance(dec.func.value, ast.Name):
                obj_name = dec.func.value.id

        if obj_name in target_vars and attr_name in ("tool", "tool_plain"):
            return True
    return False


def _extract_single_tool(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    source_lines: list[str],
) -> PydanticAIToolDef | None:
    """Extract a single tool from a function definition."""
    name = node.name
    description = ast.get_docstring(node) or ""

    start = node.lineno - 1
    end = node.end_lineno or start + 1
    func_lines = source_lines[start:end]

    # Strip decorator lines
    cleaned_lines: list[str] = []
    in_decorator = False
    for line in func_lines:
        stripped = line.lstrip()
        if stripped.startswith("@"):
            in_decorator = True
            if stripped.rstrip().endswith(")") or "(" not in stripped:
                in_decorator = False
            continue
        elif in_decorator:
            if stripped.rstrip().endswith(")"):
                in_decorator = False
            continue
        else:
            cleaned_lines.append(line)

    func_source = textwrap.dedent("".join(cleaned_lines))

    # Strip RunContext parameter
    ctx_referenced = False
    ctx_param_name = _extract_ctx_param_name(func_source)
    if ctx_param_name is not None:
        func_source = _strip_run_context_param(func_source)
        # Check if ctx param name is still referenced in the body
        body_lines = func_source.split("\n")
        # Skip the def line to look only at the body
        body_text = "\n".join(body_lines[1:])
        if re.search(rf"\b{re.escape(ctx_param_name)}\b", body_text):
            ctx_referenced = True
            # Insert TODO comment after the def line
            indent = _detect_indent(body_lines)
            todo = (
                f"{indent}# TODO: {ctx_param_name}.deps was removed during import"
                " -- rewrite this logic\n"
            )
            body_lines.insert(1, todo)
            func_source = "\n".join(body_lines)

    return PydanticAIToolDef(
        name=name,
        description=description,
        source=func_source,
        ctx_referenced=ctx_referenced,
    )


def _extract_ctx_param_name(func_source: str) -> str | None:
    """Extract the RunContext parameter name from a function definition."""
    m = _RUNCONTEXT_PARAM_NAME_RE.search(func_source)
    return m.group(1) if m else None


def _strip_run_context_param(func_source: str) -> str:
    """Remove the RunContext[...] first parameter from the function signature."""
    lines = func_source.split("\n")
    # Try single-line signature first
    if lines:
        m = _RUNCONTEXT_RE.match(lines[0])
        if m:
            lines[0] = m.group(1) + m.group(2)
            return "\n".join(lines)

    # Multi-line signature: find and remove the RunContext line
    new_lines: list[str] = []
    removed = False
    for line in lines:
        if not removed and re.search(r"\bRunContext\b", line):
            removed = True
            # If this line also has a trailing comma before or the next param,
            # just skip it entirely
            continue
        new_lines.append(line)

    return "\n".join(new_lines)


def _detect_indent(lines: list[str]) -> str:
    """Detect indentation from function body lines."""
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            return line[: len(line) - len(stripped)]
    return "    "


def _find_function_def(
    tree: ast.Module, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find a top-level function definition by name."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


# ---------------------------------------------------------------------------
# Usage limits extraction
# ---------------------------------------------------------------------------


def _extract_usage_limits(tree: ast.Module) -> dict[str, int]:
    """Extract UsageLimits(...) kwargs."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _get_call_name(node)
        if name is None:
            continue
        bare = name.rsplit(".", 1)[-1] if "." in name else name
        if bare != "UsageLimits":
            continue

        limits: dict[str, int] = {}
        for kw in node.keywords:
            if kw.arg is None:
                continue
            val = _get_number_value(kw.value)
            if val is not None:
                limits[kw.arg] = int(val)
        return limits

    return {}


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


def _extract_imports(tree: ast.Module) -> list[str]:
    """Collect all import statements as source text."""
    imports: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    imports.append(f"import {alias.name} as {alias.asname}")
                else:
                    imports.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = ", ".join(f"{a.name} as {a.asname}" if a.asname else a.name for a in node.names)
            imports.append(f"from {module} import {names}")
    return imports


# ---------------------------------------------------------------------------
# Unsupported feature detection
# ---------------------------------------------------------------------------


def _detect_unsupported(tree: ast.Module, agent_call: ast.Call, agent_var: str) -> list[str]:
    """Detect unsupported PydanticAI features and return warning messages."""
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

    # Detect builtin_tools= kwarg
    bt_node = _get_keyword_value(agent_call, "builtin_tools")
    if bt_node is not None:
        warnings.append(
            "builtin_tools detected but not auto-mapped. Add equivalent InitRunner tools manually."
        )

    # Detect mcp_servers= kwarg (if it exists in custom code)
    # Actually check toolsets for MCP references
    ts_node = _get_keyword_value(agent_call, "toolsets")
    if ts_node is not None and isinstance(ts_node, (ast.List, ast.Tuple)):
        for elt in ts_node.elts:
            if isinstance(elt, ast.Call):
                cn = _get_call_name(elt)
                if cn and "MCP" in cn:
                    warning = "MCP server detected. Use type: mcp in tools instead."
                    if warning not in seen:
                        warnings.append(warning)
                        seen.add(warning)

    # Detect instrument= kwarg
    inst_node = _get_keyword_value(agent_call, "instrument")
    if inst_node is not None:
        warning = "instrument= detected. Use spec.observability instead."
        if warning not in seen:
            warnings.append(warning)
            seen.add(warning)

    # Detect @agent_var.output_validator
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            attr_name: str | None = None
            obj_name: str | None = None
            if isinstance(dec, ast.Attribute):
                attr_name = dec.attr
                if isinstance(dec.value, ast.Name):
                    obj_name = dec.value.id
            elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                attr_name = dec.func.attr
                if isinstance(dec.func.value, ast.Name):
                    obj_name = dec.func.value.id
            if obj_name == agent_var and attr_name == "output_validator":
                warning = "@agent.output_validator is not portable to InitRunner."
                if warning not in seen:
                    warnings.append(warning)
                    seen.add(warning)

    return warnings


# ---------------------------------------------------------------------------
# Sidecar module generation
# ---------------------------------------------------------------------------


def build_sidecar_module(pai_import: PydanticAIImport) -> str | None:
    """Assemble extracted tool functions into a standalone Python module.

    Returns the module source text, or None if no custom tools exist.
    """
    if not pai_import.custom_tools:
        return None

    parts: list[str] = [
        '"""Custom tools extracted from PydanticAI agent."""',
        "",
    ]

    # Include non-PydanticAI imports from the original source
    relevant_imports = [
        imp
        for imp in pai_import.raw_imports
        if not any(
            imp.lstrip().startswith(f"from {p}") or imp.lstrip().startswith(f"import {p}")
            for p in _PAI_PREFIXES
        )
    ]
    if relevant_imports:
        parts.extend(relevant_imports)
        parts.append("")

    # Add each tool function
    for tool_def in pai_import.custom_tools:
        parts.append("")
        parts.append(tool_def.source.rstrip())
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def extract_pydanticai_import(source: str) -> PydanticAIImport:
    """Parse Python source and extract PydanticAI agent configuration.

    All extraction is deterministic (pure AST analysis, no LLM).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return PydanticAIImport(warnings=[f"Could not parse Python source: {e}"])

    # Find agents
    agents = _find_agent_assignments(tree)
    if not agents:
        return PydanticAIImport(
            warnings=["No Agent() assignment found in source."],
            raw_imports=_extract_imports(tree),
        )

    agent_var, agent_call = agents[0]
    skipped = [name for name, _ in agents[1:]]

    # Extract all fields
    provider, model_name, temperature, max_tokens = _extract_model_config(agent_call, tree)
    system_prompt, instructions, dynamic_prompts = _extract_prompts(
        agent_call, tree, source, agent_var
    )

    warnings: list[str] = []
    output_type_source = _extract_output_type(agent_call, tree, source, warnings)

    toolset_vars = _find_toolset_variables(tree)
    custom_tools = _extract_tools(tree, source, agent_var, toolset_vars)
    usage_limits = _extract_usage_limits(tree)
    raw_imports = _extract_imports(tree)
    unsupported = _detect_unsupported(tree, agent_call, agent_var)
    warnings.extend(unsupported)

    return PydanticAIImport(
        provider=provider,
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
        instructions=instructions,
        dynamic_prompts=dynamic_prompts,
        output_type_source=output_type_source,
        usage_limits=usage_limits,
        custom_tools=custom_tools,
        skipped_agents=skipped,
        warnings=warnings,
        raw_imports=raw_imports,
    )
