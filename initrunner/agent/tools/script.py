"""Script tool: define inline shell scripts in YAML as named tools."""

from __future__ import annotations

import inspect
import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._subprocess import (
    SubprocessTimeout,
    format_subprocess_output,
    scrub_env,
)
from initrunner.agent.schema.tools import ScriptDefinition, ScriptToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

if TYPE_CHECKING:
    from initrunner.agent.schema.security import DockerSandboxConfig

# Reuse the shell operator set from shell_tools for consistency.
_SHELL_OPERATORS: frozenset[str] = frozenset(
    {"|", "||", "&&", ";", ";;", ">", ">>", "<", "<<", "<<<", "(", ")", "{", "}", "&"}
)


def _validate_script_body(body: str, allowed_commands: list[str]) -> str | None:
    """Validate that every command line in *body* uses an allowed command.

    Returns an error string on violation, or ``None`` if the body is valid.
    When *allowed_commands* is empty, validation is skipped entirely.
    """
    if not allowed_commands:
        return None

    for lineno, raw_line in enumerate(body.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # Reject lines containing shell operators
        try:
            tokens = shlex.split(line)
        except ValueError:
            # Malformed line — let the interpreter deal with it
            continue

        for tok in tokens:
            if tok in _SHELL_OPERATORS:
                return (
                    f"Error: shell operator '{tok}' on line {lineno} "
                    f"is not allowed with allowed_commands"
                )

        # Check first token against allowed list
        base = Path(tokens[0]).name
        if base not in allowed_commands:
            return (
                f"Error: command '{base}' on line {lineno} "
                f"is not in the allowed list: {allowed_commands}"
            )

    return None


def _make_script_fn(
    script: ScriptDefinition,
    config: ScriptToolConfig,
    work_dir: str | None,
    docker_config: DockerSandboxConfig | None = None,
    role_dir: Path | None = None,
) -> Any:
    """Build a callable with proper ``inspect.Signature`` for PydanticAI."""
    params: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}

    for p in script.parameters:
        annotations[p.name] = str
        default = inspect.Parameter.empty if p.required else (p.default or "")
        params.append(
            inspect.Parameter(
                p.name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=str,
            )
        )
    annotations["return"] = str

    sig = inspect.Signature(params, return_annotation=str)

    # Resolve per-script overrides
    interpreter = script.interpreter or config.interpreter
    timeout = script.timeout_seconds or config.timeout_seconds
    max_output = config.max_output_bytes
    allowed_cmds = script.allowed_commands

    # Build defaults map for env injection
    _defaults: dict[str, str] = {
        p.name: p.default for p in script.parameters if not p.required and p.default
    }

    # Capture in closure
    _body = script.body
    _interpreter = interpreter
    _timeout = timeout
    _max_output = max_output
    _allowed_cmds = allowed_cmds
    _work_dir = work_dir
    _docker_config = docker_config
    _role_dir = role_dir

    def script_fn(**kwargs: Any) -> str:
        # Validate against allowed_commands if set
        if _allowed_cmds:
            err = _validate_script_body(_body, _allowed_cmds)
            if err:
                return err

        # Build environment: scrubbed base + defaults + explicit params
        env = scrub_env()
        for key, value in _defaults.items():
            env[key.upper()] = value
        for key, value in kwargs.items():
            env[key.upper()] = str(value)

        if _docker_config is not None and _docker_config.enabled:
            from initrunner.agent.docker_sandbox import docker_run_script

            try:
                stdout, stderr, returncode = docker_run_script(
                    _body,
                    _interpreter,
                    _docker_config,
                    timeout=_timeout,
                    work_dir=_work_dir,
                    env=env,
                    role_dir=_role_dir,
                )
            except SubprocessTimeout:
                raise
            except FileNotFoundError:
                return f"Error: interpreter '{_interpreter}' not found"

            return format_subprocess_output(
                stdout, stderr, returncode=returncode, max_bytes=_max_output
            )

        cmd = [_interpreter]

        try:
            result = subprocess.run(
                cmd,
                input=_body.encode("utf-8"),
                capture_output=True,
                timeout=_timeout,
                cwd=_work_dir,
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise SubprocessTimeout(_timeout) from None
        except FileNotFoundError:
            return f"Error: interpreter '{_interpreter}' not found"

        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")

        return format_subprocess_output(
            stdout, stderr, returncode=result.returncode, max_bytes=_max_output
        )

    script_fn.__name__ = script.name
    script_fn.__qualname__ = script.name
    script_fn.__doc__ = script.description or f"Run the '{script.name}' script"
    script_fn.__signature__ = sig  # type: ignore[attr-defined]
    script_fn.__annotations__ = annotations

    return script_fn


@register_tool("script", ScriptToolConfig)
def build_script_toolset(config: ScriptToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset from a ScriptToolConfig."""
    role_dir = ctx.role_dir
    docker_config = ctx.role.spec.security.docker

    # Resolve working directory: explicit > role_dir > cwd
    if config.working_dir:
        work_dir = str(Path(config.working_dir).resolve())
    elif role_dir is not None:
        work_dir = str(role_dir.resolve())
    else:
        work_dir = None

    toolset = FunctionToolset()
    for script in config.scripts:
        fn = _make_script_fn(
            script, config, work_dir, docker_config=docker_config, role_dir=role_dir
        )
        toolset.tool_plain(fn)

    return toolset
