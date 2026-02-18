"""Filesystem tools: read_file, list_directory, write_file."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._paths import validate_path_within
from initrunner.agent._truncate import truncate_output
from initrunner.agent.schema.tools import FileSystemToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

_MAX_READ_FILE_BYTES = 1_048_576  # 1 MB


@register_tool("filesystem", FileSystemToolConfig)
def build_filesystem_toolset(
    config: FileSystemToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Build a FunctionToolset for filesystem operations."""
    root = Path(config.root_path).resolve()
    allowed_ext = set(config.allowed_extensions) if config.allowed_extensions else None

    toolset = FunctionToolset()

    @toolset.tool
    def read_file(path: str) -> str:
        """Read the contents of a file."""
        raw = root / path
        err, target = validate_path_within(
            raw, [root], allowed_ext=allowed_ext, reject_symlinks=True
        )
        if err:
            return err
        try:
            size = target.stat().st_size
            if size > _MAX_READ_FILE_BYTES:
                data = target.read_bytes()[:_MAX_READ_FILE_BYTES]
                return truncate_output(data.decode("utf-8", errors="replace"), _MAX_READ_FILE_BYTES)
            return target.read_text(encoding="utf-8")
        except OSError as e:
            return f"Error reading file: {e}"

    @toolset.tool
    def list_directory(path: str = ".") -> str:
        """List files and directories at the given path."""
        raw = root / path
        err, target = validate_path_within(raw, [root], reject_symlinks=True)
        if err:
            return err
        try:
            entries = sorted(os.listdir(target))
            return "\n".join(entries) if entries else "(empty directory)"
        except OSError as e:
            return f"Error listing directory: {e}"

    if not config.read_only:

        @toolset.tool
        def write_file(path: str, content: str) -> str:
            """Write content to a file."""
            raw = root / path
            err, target = validate_path_within(
                raw, [root], allowed_ext=allowed_ext, reject_symlinks=True
            )
            if err:
                return err
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                return f"Written {len(content)} bytes to {path}"
            except OSError as e:
                return f"Error writing file: {e}"

    return toolset
