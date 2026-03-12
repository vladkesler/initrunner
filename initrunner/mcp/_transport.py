"""Unified MCP transport construction shared by server, gateway, and introspect."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from initrunner.agent._env import resolve_env_vars
from initrunner.agent._subprocess import scrub_env
from initrunner.agent.schema.tools import McpToolConfig

if TYPE_CHECKING:
    from initrunner.agent.schema.security import ToolSandboxConfig


def build_transport(
    config: McpToolConfig,
    role_dir: Path | None = None,
    *,
    sandbox: ToolSandboxConfig | None = None,
):
    """Build a bare MCP transport from config.

    Parameters:
        config: MCP tool configuration.
        role_dir: Role file directory — used to resolve relative ``cwd`` paths.
        sandbox: When provided, validates ``command`` against
            ``mcp_command_allowlist`` and scrubs env with sandbox-specific
            prefixes/suffixes/allowlist.  When ``None`` (introspection mode),
            skips command validation and uses default scrub settings.

    Returns:
        A ``StdioTransport``, ``SSETransport``, or ``StreamableHttpTransport``.
    """
    # Resolve headers once (used by SSE and streamable-http)
    resolved_headers = {k: resolve_env_vars(v) for k, v in config.headers.items()}

    if config.transport == "stdio":
        from fastmcp.client.transports import StdioTransport

        # Validate MCP command against allowlist when sandbox is present
        if sandbox and sandbox.mcp_command_allowlist and config.command:
            if config.command not in sandbox.mcp_command_allowlist:
                raise ValueError(
                    f"MCP command '{config.command}' is not in the allowed command list: "
                    f"{sandbox.mcp_command_allowlist}"
                )

        kwargs: dict = {"command": config.command, "args": config.args}

        # Build env: scrubbed system env + interpolated config env
        if sandbox:
            base_env = scrub_env(
                sandbox.sensitive_env_prefixes,
                suffixes=sandbox.sensitive_env_suffixes,
                allowlist=set(sandbox.env_allowlist),
            )
        else:
            base_env = scrub_env()
        resolved_env = {k: resolve_env_vars(v) for k, v in config.env.items()}
        kwargs["env"] = {**base_env, **resolved_env}

        # Resolve cwd relative to role_dir when both provided
        if config.cwd is not None:
            cwd_path = Path(config.cwd)
            if not cwd_path.is_absolute() and role_dir is not None:
                cwd_path = role_dir / cwd_path
            kwargs["cwd"] = str(cwd_path)

        return StdioTransport(**kwargs)

    elif config.transport == "sse":
        from fastmcp.client.transports import SSETransport

        sse_kwargs: dict = {"url": config.url}
        if resolved_headers:
            sse_kwargs["headers"] = resolved_headers
        if config.timeout_seconds is not None:
            sse_kwargs["sse_read_timeout"] = config.timeout_seconds
        return SSETransport(**sse_kwargs)

    elif config.transport == "streamable-http":
        from fastmcp.client.transports import StreamableHttpTransport

        http_kwargs: dict = {"url": config.url}
        if resolved_headers:
            http_kwargs["headers"] = resolved_headers
        if config.timeout_seconds is not None:
            http_kwargs["sse_read_timeout"] = config.timeout_seconds
        return StreamableHttpTransport(**http_kwargs)

    else:
        raise ValueError(f"Unknown MCP transport: {config.transport}")
