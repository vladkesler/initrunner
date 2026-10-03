"""Python execution tool: runs code in a subprocess with isolation."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._subprocess import (
    SubprocessTimeout,
    format_subprocess_output,
)
from initrunner.agent.runtime_sandbox.base import SandboxConfigError
from initrunner.agent.schema.security import BindMount
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


def _host_proxy_variables() -> list[str]:
    """Names of the host variables a child would read as a proxy.

    urllib, requests and httpx treat any ``<scheme>_proxy`` variable as one, in
    either case, so the match is on the suffix rather than a fixed list.
    """
    return [name for name in os.environ if name.lower().endswith("_proxy")]


@register_tool("python", PythonToolConfig)
def build_python_toolset(config: PythonToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for executing Python code in a subprocess."""
    from initrunner.agent.runtime_sandbox import warn_if_unsandboxed

    backend = ctx.sandbox_backend
    warn_if_unsandboxed(backend, "python")

    toolset = FunctionToolset()

    @toolset.tool_plain
    def run_python(code: str) -> str:
        """Execute Python code and return the output."""
        env: dict[str, str] = {}
        unset_env: list[str] = []
        if config.network_disabled:
            code = _NETWORK_DISABLE_SHIM + code
            # The shim allows loopback, so a proxy on 127.0.0.1 named in the
            # inherited environment would be a way out. The child gets none of
            # the host's proxy variables, only NO_PROXY.
            unset_env = _host_proxy_variables()
            env = {"no_proxy": "*", "NO_PROXY": "*"}

        use_temp = config.working_dir is None
        if use_temp:
            work_dir = tempfile.mkdtemp(prefix="initrunner_py_")
        else:
            work_dir = config.working_dir
            assert work_dir is not None
            Path(work_dir).mkdir(parents=True, exist_ok=True)

        code_file = Path(work_dir) / "_run.py"
        code_file.write_text(code, encoding="utf-8")

        python_bin = sys.executable if backend.name == "none" else "python3"
        try:
            sr = backend.run(
                [python_bin, "/work/_run.py"],
                env=env,
                unset_env=unset_env,
                cwd=Path(work_dir),
                timeout=config.timeout_seconds,
                extra_mounts=[
                    BindMount(source=str(code_file), target="/work/_run.py", read_only=True),
                ],
            )
        except SubprocessTimeout as exc:
            return str(exc)
        except SandboxConfigError as exc:
            # Backend cannot stage local code (e.g. SSH has no shared filesystem).
            # Surface the message to the model instead of crashing the run so it
            # can adapt -- usually by switching to the shell tool.
            return f"Error: python tool unavailable on this sandbox backend: {exc}"
        finally:
            if use_temp:
                shutil.rmtree(work_dir, ignore_errors=True)
            else:
                code_file.unlink(missing_ok=True)

        return format_subprocess_output(
            sr.stdout, sr.stderr, returncode=sr.returncode, max_bytes=config.max_output_bytes
        )

    return toolset
