"""Custom tool loading, AST validation, and delegate/plugin toolset building."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.schema import (
    CustomToolConfig,
    DelegateToolConfig,
    PluginToolConfig,
    ToolSandboxConfig,
)
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

if TYPE_CHECKING:
    from pydantic_ai.toolsets import AbstractToolset


def _validate_source_imports(source_text: str, sandbox: ToolSandboxConfig) -> None:
    """AST-based import analysis on raw source text (before importing the module)."""
    import ast

    tree = ast.parse(source_text)

    blocked = set(sandbox.blocked_custom_modules)
    allowed = set(sandbox.allowed_custom_modules)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                base = (alias.name or "").split(".")[0]
                if isinstance(node, ast.ImportFrom) and node.module:
                    base = node.module.split(".")[0]
                if allowed:
                    if base not in allowed:
                        raise ValueError(
                            f"Custom tool imports module '{base}' which is not in allowlist"
                        )
                elif base in blocked:
                    raise ValueError(f"Custom tool imports blocked module '{base}'")
        # Catch __import__("os") pattern
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
        ):
            if node.args and isinstance(node.args[0], ast.Constant):
                mod_name = str(node.args[0].value)
                if allowed:
                    if mod_name not in allowed:
                        raise ValueError(
                            f"Custom tool uses __import__('{mod_name}') which is not in allowlist"
                        )
                elif mod_name in blocked:
                    raise ValueError(f"Custom tool uses __import__('{mod_name}') which is blocked")


def _inject_config(func: Callable, config_data: dict[str, object]) -> Callable:
    """Bind tool_config to a function if it accepts that parameter."""
    import inspect
    from functools import partial

    sig = inspect.signature(func)
    if "tool_config" not in sig.parameters:
        return func

    new_func = partial(func, tool_config=config_data)
    new_func.__name__ = func.__name__  # type: ignore[attr-defined]
    new_func.__qualname__ = getattr(func, "__qualname__", func.__name__)  # type: ignore[attr-defined]
    new_func.__doc__ = func.__doc__
    new_func.__module__ = func.__module__
    # Strip tool_config from annotations so PydanticAI doesn't expose it to LLM
    new_annotations = {k: v for k, v in func.__annotations__.items() if k != "tool_config"}
    new_func.__annotations__ = new_annotations
    return new_func


def _discover_module_tools(mod: object) -> list[Callable]:
    """Discover all public callable functions in a module."""
    import inspect
    import types

    funcs: list[Callable] = []
    for name in dir(mod):
        if name.startswith("_"):
            continue
        obj = getattr(mod, name)
        if not callable(obj):
            continue
        # Skip classes, modules, and builtins
        if isinstance(obj, type | types.ModuleType | types.BuiltinFunctionType):
            continue
        if not inspect.isfunction(obj):
            continue
        funcs.append(obj)
    return funcs


@register_tool("custom", CustomToolConfig)
def build_custom_toolset(
    config: CustomToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Load custom tool function(s) from a module path."""
    import importlib
    import importlib.util
    import sys

    sandbox = ctx.role.spec.security.tools

    # Add role_dir to sys.path so local modules are importable (matches sinks/custom.py)
    role_dir_str: str | None = None
    if ctx.role_dir is not None:
        role_dir_str = str(ctx.role_dir)
        if role_dir_str not in sys.path:
            sys.path.insert(0, role_dir_str)

    # Validate source via AST BEFORE importing to prevent arbitrary code execution
    spec = importlib.util.find_spec(config.module)
    if spec is None:
        if role_dir_str is not None and role_dir_str in sys.path:
            sys.path.remove(role_dir_str)
        raise ValueError(
            f"Could not find module '{config.module}'. Install it with: pip install {config.module}"
        )

    if spec.origin and Path(spec.origin).is_file():
        source_text = Path(spec.origin).read_text()
        _validate_source_imports(source_text, sandbox)

    try:
        mod = importlib.import_module(config.module)
    except ImportError as e:
        missing = e.name or config.module
        raise ValueError(
            f"Could not load module '{config.module}': missing dependency '{missing}'. "
            f"Install it with: pip install {missing}"
        ) from e
    finally:
        # Clean up sys.path to avoid polluting it for unrelated imports
        if role_dir_str is not None and role_dir_str in sys.path:
            sys.path.remove(role_dir_str)

    # Collect functions: single function or auto-discover
    if config.function is not None:
        func = getattr(mod, config.function, None)
        if func is None:
            raise ValueError(f"Function '{config.function}' not found in module '{config.module}'")
        funcs = [func]
    else:
        funcs = _discover_module_tools(mod)
        if not funcs:
            raise ValueError(
                f"No public callable functions found in module '{config.module}'. "
                "Add public functions or specify 'function' explicitly."
            )

    toolset = FunctionToolset()
    for func in funcs:
        # Inject config if the function accepts tool_config
        func = _inject_config(func, config.config)

        # Apply sandbox if enabled
        if sandbox is not None and sandbox.audit_hooks_enabled:
            from initrunner.agent.sandbox import sandbox_scope

            original_func = func

            def sandboxed_func(*args, _orig=original_func, **kwargs):
                with sandbox_scope(config=sandbox, agent_name=config.module):
                    return _orig(*args, **kwargs)

            sandboxed_func.__name__ = original_func.__name__  # type: ignore[attr-defined]
            sandboxed_func.__qualname__ = getattr(
                original_func,
                "__qualname__",
                original_func.__name__,  # type: ignore[attr-defined]
            )
            sandboxed_func.__doc__ = original_func.__doc__
            sandboxed_func.__annotations__ = getattr(original_func, "__annotations__", {})
            func = sandboxed_func

        toolset.tool(func)
    return toolset


@register_tool("delegate", DelegateToolConfig)
def build_delegate_toolset(
    config: DelegateToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Build delegate tools: one tool per agent ref (delegate_to_{name})."""
    from initrunner.agent.delegation import InlineInvoker, McpInvoker

    role_dir = ctx.role_dir
    toolset = FunctionToolset()

    for agent_ref in config.agents:
        if config.mode == "inline":
            role_path = Path(agent_ref.role_file)  # type: ignore[arg-type]
            if not role_path.is_absolute() and role_dir is not None:
                role_path = role_dir / role_path
            sm = config.shared_memory
            # Resolve relative shared memory paths against the coordinator's role_dir
            sm_path: str | None = None
            if sm and sm.store_path:
                sp = Path(sm.store_path)
                if not sp.is_absolute() and role_dir is not None:
                    sp = (role_dir / sp).resolve()
                sm_path = str(sp)
            invoker: InlineInvoker | McpInvoker = InlineInvoker(
                role_path.resolve(),
                max_depth=config.max_depth,
                timeout=config.timeout_seconds,
                shared_memory_path=sm_path,
                shared_max_memories=sm.max_memories if sm else 1000,
            )
        else:
            invoker = McpInvoker(
                base_url=agent_ref.url,  # type: ignore[arg-type]
                agent_name=agent_ref.name,
                timeout=config.timeout_seconds,
                headers_env=agent_ref.headers_env,
            )

        # Capture invoker and description in closure
        _invoker = invoker
        _desc = agent_ref.description or f"Delegate task to the {agent_ref.name} agent"

        def _make_tool(inv: InlineInvoker | McpInvoker, desc: str, name: str) -> None:
            def delegate_fn(prompt: str) -> str:
                return inv.invoke(prompt)

            delegate_fn.__name__ = f"delegate_to_{name}"
            delegate_fn.__qualname__ = f"delegate_to_{name}"
            delegate_fn.__doc__ = desc
            toolset.tool(delegate_fn)

        _make_tool(_invoker, _desc, agent_ref.name)

    return toolset


@register_tool("plugin", PluginToolConfig)
def build_plugin_toolset(config: PluginToolConfig, ctx: ToolBuildContext) -> AbstractToolset:
    """Build a toolset from a plugin registry entry."""
    from initrunner.agent.plugins import get_registry

    registry = get_registry()
    plugin = registry.get(config.type)

    if plugin is None:
        installed = sorted(registry.list_plugins().keys())
        if installed:
            raise ValueError(
                f"Tool type '{config.type}' not found. "
                f"Installed plugins: {installed}. "
                f"Did you forget to pip install initrunner-{config.type}?"
            )
        raise ValueError(
            f"Tool type '{config.type}' not found. No plugins installed. "
            f"Install one with: pip install initrunner-{config.type}"
        )

    validated = plugin.config_class.model_validate({"type": config.type, **config.config})
    return plugin.builder(validated, role_dir=ctx.role_dir, sandbox=ctx.role.spec.security.tools)
