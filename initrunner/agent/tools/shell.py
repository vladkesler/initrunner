"""Shell tool: runs commands in a subprocess with isolation (no shell)."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._subprocess import (
    SubprocessTimeout,
    format_subprocess_output,
)
from initrunner.agent.schema.tools import ShellToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

_FORK_BOMB_PATTERN = re.compile(r":\(\)\s*\{")

_SHELL_OPERATORS: frozenset[str] = frozenset(
    {"|", "||", "&&", ";", ";;", ">", ">>", "<", "<<", "<<<", "(", ")", "{", "}", "&"}
)


def _parse_command(command: str) -> list[str] | str:
    """Tokenize *command* with :func:`shlex.split`.

    Returns the token list on success or an error string on failure
    (e.g. unclosed quotes).
    """
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return f"Error: invalid command syntax: {exc}"
    if not tokens:
        return "Error: empty command"
    return tokens


def _check_for_shell_operators(tokens: list[str]) -> str | None:
    """Return an error string if any token is a shell operator, else ``None``."""
    for tok in tokens:
        if tok in _SHELL_OPERATORS:
            return f"Error: shell operator '{tok}' is not allowed — use dedicated tools instead"
    return None


def validate_command(
    command: str,
    *,
    allowed: list[str],
    blocked: list[str],
) -> str | None:
    """Return an error string if the command is disallowed, else ``None``."""
    # Defense-in-depth: catch fork bombs even though they need a shell to work
    if _FORK_BOMB_PATTERN.search(command):
        return "Error: fork bomb pattern detected"

    result = _parse_command(command)
    if isinstance(result, str):
        return result
    tokens = result

    if err := _check_for_shell_operators(tokens):
        return err

    base = Path(tokens[0]).name

    if allowed and base not in allowed:
        return f"Error: command '{base}' is not in the allowed list: {allowed}"

    if base in blocked:
        return f"Error: command '{base}' is blocked"

    return None


@register_tool("shell", ShellToolConfig)
def build_shell_toolset(config: ShellToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for executing commands (no shell)."""
    backend = ctx.sandbox_backend

    if config.working_dir:
        work_dir = Path(config.working_dir).resolve()
    elif ctx.role_dir is not None:
        work_dir = ctx.role_dir.resolve()
    else:
        work_dir = Path.cwd()

    toolset = FunctionToolset()

    @toolset.tool_plain
    def run_shell(command: str) -> str:
        """Execute a command and return the output."""
        if err := validate_command(
            command, allowed=config.allowed_commands, blocked=config.blocked_commands
        ):
            return err

        result = _parse_command(command)
        if isinstance(result, str):
            return result
        tokens = result

        try:
            sr = backend.run(
                tokens,
                env={},
                cwd=work_dir,
                timeout=config.timeout_seconds,
            )
        except SubprocessTimeout as exc:
            return str(exc)
        except FileNotFoundError:
            return f"Error: command '{tokens[0]}' not found"

        return format_subprocess_output(
            sr.stdout, sr.stderr, returncode=sr.returncode, max_bytes=config.max_output_bytes
        )

    return toolset
