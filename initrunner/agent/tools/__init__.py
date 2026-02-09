"""Built-in tools and tool registry — split into sub-modules for SRP.

Public API re-exports for backward compatibility.
"""

from initrunner.agent.tools._registry import ToolBuildContext
from initrunner.agent.tools.custom import (
    _discover_module_tools,
    _inject_config,
    _validate_source_imports,
)
from initrunner.agent.tools.custom import (
    build_custom_toolset as _build_custom_toolset,
)
from initrunner.agent.tools.custom import (
    build_delegate_toolset as _build_delegate_toolset,
)
from initrunner.agent.tools.custom import (
    build_plugin_toolset as _build_plugin_toolset,
)
from initrunner.agent.tools.datetime_tools import build_datetime_toolset
from initrunner.agent.tools.filesystem import build_filesystem_toolset
from initrunner.agent.tools.http import build_http_toolset
from initrunner.agent.tools.memory import build_memory_toolset as _build_memory_toolset
from initrunner.agent.tools.registry import (
    build_toolsets,
    install_audit_hooks,
)
from initrunner.agent.tools.retrieval import (
    _embed_single,
    _validate_store_path,
)
from initrunner.agent.tools.retrieval import (
    build_retrieval_toolset as _build_retrieval_toolset,
)
from initrunner.agent.tools.web_reader import build_web_reader_toolset
from initrunner.agent.tools.web_scraper import build_web_scraper_toolset


def _validate_custom_tool_imports(module_or_source, sandbox):
    """Backward-compatible wrapper: accepts a module or source text."""
    import inspect
    import types
    from pathlib import Path

    if isinstance(module_or_source, types.ModuleType):
        source_file = inspect.getfile(module_or_source)
        source_text = Path(source_file).read_text()
    else:
        source_text = module_or_source
    return _validate_source_imports(source_text, sandbox)


__all__ = [
    "ToolBuildContext",
    "_build_custom_toolset",
    "_build_delegate_toolset",
    "_build_memory_toolset",
    "_build_plugin_toolset",
    "_build_retrieval_toolset",
    "_discover_module_tools",
    "_embed_single",
    "_inject_config",
    "_validate_custom_tool_imports",
    "_validate_source_imports",
    "_validate_store_path",
    "build_datetime_toolset",
    "build_filesystem_toolset",
    "build_http_toolset",
    "build_toolsets",
    "build_web_reader_toolset",
    "build_web_scraper_toolset",
    "install_audit_hooks",
]
