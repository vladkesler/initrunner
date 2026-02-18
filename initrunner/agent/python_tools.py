"""Python execution tool: runs code in a subprocess with isolation."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._subprocess import (
    SubprocessTimeout,
    format_subprocess_output,
    scrub_env,
)
from initrunner.agent.schema.tools import PythonToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

# Best-effort network restriction: a sys.audit hook that blocks outbound socket
# operations to non-loopback addresses.  This stops urllib, httpx, requests, etc.
# but is NOT a kernel-level sandbox — a determined user can bypass it.
_NETWORK_DISABLE_SHIM = textwrap.dedent("""\
    import sys as _sys

    def _block_network(event, args):
        if event in ("socket.connect", "socket.bind", "socket.sendto"):
            addr = args[1] if len(args) > 1 else None
            if addr is None:
                return
            host = None
            if isinstance(addr, tuple) and len(addr) >= 2:
                host = str(addr[0])
            elif isinstance(addr, str):
                host = addr
            if host is not None and host not in ("127.0.0.1", "::1", "localhost"):
                raise PermissionError(
                    f"Network access is disabled (blocked {event} to {host})"
                )

    _sys.addaudithook(_block_network)
    del _block_network, _sys
    """)

_PROXY_ENV_KEYS = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
)


@register_tool("python", PythonToolConfig)
def build_python_toolset(config: PythonToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for executing Python code in a subprocess."""
    toolset = FunctionToolset()

    @toolset.tool
    def run_python(code: str) -> str:
        """Execute Python code and return the output."""
        work_dir = config.working_dir
        use_temp = work_dir is None

        if use_temp:
            tmp_dir = tempfile.mkdtemp(prefix="initrunner_py_")
            work_dir = tmp_dir
        else:
            assert work_dir is not None
            Path(work_dir).mkdir(parents=True, exist_ok=True)

        # Prepend network-blocking shim when network_disabled is set
        if config.network_disabled:
            code = _NETWORK_DISABLE_SHIM + code

        # Write code to a temp file
        code_file = Path(work_dir) / "_run.py"
        code_file.write_text(code, encoding="utf-8")

        env = scrub_env()
        if config.network_disabled:
            for key in _PROXY_ENV_KEYS:
                env.pop(key, None)
            env["no_proxy"] = "*"
            env["NO_PROXY"] = "*"

        try:
            result = subprocess.run(
                [sys.executable, str(code_file)],
                capture_output=True,
                timeout=config.timeout_seconds,
                cwd=work_dir,
                env=env,
            )
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return str(SubprocessTimeout(config.timeout_seconds))
        finally:
            # Clean up temp directory and all contents
            if use_temp:
                shutil.rmtree(work_dir, ignore_errors=True)
            else:
                code_file.unlink(missing_ok=True)

        return format_subprocess_output(stdout, stderr, max_bytes=config.max_output_bytes)

    return toolset
