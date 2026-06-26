"""LLM scaffolding for custom-tool modules (``initrunner tool new``).

Emits a plain-Python custom-tool module plus a pytest stub from a natural-
language description, reusing the BuilderSession LLM recipe (model resolution,
``run_sync``, fenced-block extraction, one validation-driven auto-repair). The
generated module is referenced via ``type: custom`` and loaded by
``agent/tools/custom.py::build_custom_toolset``; it is AST-validated here and
re-wrapped in the policy/permission/sandbox layers when the agent is built.

Scaffolding never imports the generated module (importing runs top-level code);
it only parses and AST-validates the source.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

_logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)
_MODULE_LINE = re.compile(r"^\s*Module:\s*([A-Za-z0-9_ -]+)\s*$", re.MULTILINE)


@dataclass
class ToolScaffold:
    """Generated custom-tool sources plus derived metadata."""

    module_name: str
    module_source: str
    test_source: str
    function_names: list[str]
    yaml_snippet: str
    explanation: str
    warnings: list[str] = field(default_factory=list)


def build_custom_tool_reference() -> str:
    """Compact contract handed to the LLM, analogous to ``build_schema_reference``.

    Lists the actually-blocked custom-tool imports so the model avoids them.
    """
    from initrunner.agent.schema.security import ToolSandboxConfig

    blocked = ", ".join(ToolSandboxConfig().blocked_custom_modules)
    return f"""\
Write a single Python module defining one or more custom tools for an InitRunner agent.

Contract:
- Each PUBLIC top-level function (name not starting with `_`) becomes a tool the agent
  can call. Prefer `async def` so a developer can drop `breakpoint()` and step the call
  on the main thread.
- Give every function precise type hints and a docstring. The first docstring line is the
  tool description shown to the model; parameter types define the input schema. Use only
  JSON-serializable parameter and return types (str, int, float, bool, list, dict).
- Return a SHORT, JSON-serializable result (prefer a string). Truncate large output and
  append a `[truncated]` marker; never return unbounded data.
- For configuration or secrets, accept an optional `tool_config: dict` parameter. It is
  injected from the role YAML `config:` block and hidden from the model. Do NOT read
  environment variables directly.
- Do NOT import any of these blocked modules: {blocked}. Network access via
  `httpx` / `urllib.request` is fine. For optional third-party imports, add a trailing
  `# type: ignore[import-not-found]` comment.
- No top-level side effects: only imports and definitions at module scope.

Output format (exactly):
1. A line `Module: <snake_case_module_name>` naming the module.
2. One short paragraph explaining what the tool does.
3. The tool module in a fenced ```python block.
4. A pytest stub in a second fenced ```python block that imports the module and asserts on
   one function's behaviour (mock/monkeypatch any network call)."""


_TOOL_BUILDER_SYSTEM_PROMPT = """\
You are an expert Python developer writing a single InitRunner custom-tool module.
Follow the contract exactly. Output a `Module:` line, a one-paragraph explanation, then
exactly two fenced ```python blocks: the module first, the pytest stub second.

{reference}
"""


def _extract_python_blocks(text: str) -> tuple[str, str, str]:
    """Split an LLM response into ``(explanation, module_source, test_source)``."""
    blocks = _FENCE.findall(text)
    module_source = blocks[0].strip() if blocks else ""
    test_source = blocks[1].strip() if len(blocks) > 1 else ""
    first = _FENCE.search(text)
    explanation = text[: first.start()].strip() if first else text.strip()
    return explanation, module_source, test_source


def _validate_module_source(source: str) -> str | None:
    """Return an error string if the source is invalid Python or imports a blocked
    module, else ``None``. Never imports the module."""
    from initrunner.agent.schema.security import ToolSandboxConfig
    from initrunner.agent.tools.custom import _validate_source_imports

    try:
        ast.parse(source)
    except SyntaxError as exc:
        return f"SyntaxError: {exc}"
    try:
        _validate_source_imports(source, ToolSandboxConfig())
    except ValueError as exc:
        return str(exc)
    return None


def _public_function_names(source: str) -> list[str]:
    """Top-level public function names (sync or async)."""
    tree = ast.parse(source)
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and not node.name.startswith("_")
    ]


def _proposed_module_name(explanation: str) -> str | None:
    match = _MODULE_LINE.search(explanation)
    return match.group(1).strip() if match else None


def _retarget_test_imports(test_source: str, module_name: str, function_names: list[str]) -> str:
    """Point the test's import of the tool module at the final module name.

    The model names the module its own way; when ``--output``/``name_hint``
    renames it, the generated ``from <mod> import <fn>`` line would otherwise
    import a module that does not exist.
    """
    if not test_source or not function_names:
        return test_source
    fn_set = set(function_names)
    pattern = re.compile(r"^(\s*)from\s+([.\w]+)\s+import\s+(.+)$")
    out: list[str] = []
    for line in test_source.splitlines():
        match = pattern.match(line)
        if match:
            imported = {n.strip().split(" as ")[0].strip() for n in match.group(3).split(",")}
            if imported & fn_set and match.group(2) != module_name:
                line = f"{match.group(1)}from {module_name} import {match.group(3)}"
        out.append(line)
    result = "\n".join(out)
    return result + "\n" if test_source.endswith("\n") else result


def scaffold_tool(
    description: str,
    provider: str,
    model_name: str | None = None,
    *,
    name_hint: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
) -> ToolScaffold:
    """LLM-generate a validated custom-tool module + pytest stub from a description."""
    from pydantic_ai import Agent

    from initrunner.agent.loader import _build_model
    from initrunner.agent.schema.base import ModelConfig
    from initrunner.services.agent_builder import sanitize_module_stem
    from initrunner.templates import _default_model_name

    if model_name is None:
        model_name = _default_model_name(provider)

    system = _TOOL_BUILDER_SYSTEM_PROMPT.format(reference=build_custom_tool_reference())
    model = _build_model(
        ModelConfig(provider=provider, name=model_name, base_url=base_url, api_key_env=api_key_env)
    )
    agent = Agent(model, instructions=system)

    result = agent.run_sync(description)
    explanation, module_source, test_source = _extract_python_blocks(str(result.output))

    warnings: list[str] = []
    error = (
        _validate_module_source(module_source) if module_source else "No Python module block found."
    )
    if error is not None:
        # One validation-driven auto-repair, feeding the error back to the model.
        repair = (
            f"The module failed validation: {error}\n"
            "Fix it and output the corrected module and pytest stub again, honoring the "
            "contract (valid Python, no blocked imports, two fenced ```python blocks)."
        )
        result = agent.run_sync(repair, message_history=result.all_messages())
        exp2, mod2, test2 = _extract_python_blocks(str(result.output))
        if mod2:
            module_source = mod2
            test_source = test2 or test_source
            explanation = exp2 or explanation
        error = (
            _validate_module_source(module_source)
            if module_source
            else "No Python module block produced."
        )
        if error is not None:
            warnings.append(f"Generated tool failed validation after one repair: {error}")

    valid = bool(module_source) and _validate_module_source(module_source) is None
    function_names = _public_function_names(module_source) if valid else []

    raw_name = (
        name_hint
        or _proposed_module_name(explanation)
        or (function_names[0] if function_names else description)
    )
    module_name = sanitize_module_stem(raw_name, fallback="custom_tool")
    test_source = _retarget_test_imports(test_source, module_name, function_names)
    yaml_snippet = f"tools:\n  - type: custom\n    module: {module_name}"

    return ToolScaffold(
        module_name=module_name,
        module_source=module_source,
        test_source=test_source,
        function_names=function_names,
        yaml_snippet=yaml_snippet,
        explanation=explanation,
        warnings=warnings,
    )


def write_scaffold(scaffold: ToolScaffold, out_dir: Path, *, force: bool = False) -> list[Path]:
    """Write ``<name>.py`` and ``test_<name>.py`` to *out_dir*; return written paths."""
    module_path = out_dir / f"{scaffold.module_name}.py"
    test_path = out_dir / f"test_{scaffold.module_name}.py"
    for path in (module_path, test_path):
        if path.exists() and not force:
            raise FileExistsError(f"{path} already exists (use --force to overwrite).")
    module_path.write_text(scaffold.module_source)
    written = [module_path]
    if scaffold.test_source:
        test_path.write_text(scaffold.test_source)
        written.append(test_path)
    return written
