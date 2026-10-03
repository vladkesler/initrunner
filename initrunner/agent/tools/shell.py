"""Shell tool: runs commands in a subprocess with isolation (no shell)."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

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


# Programs whose job is to run another program. The lists are checked against
# the command's first token, which says nothing about what these go on to run.
_LAUNCHERS: frozenset[str] = frozenset(
    {
        # shells
        "sh", "bash", "dash", "zsh", "ksh", "fish", "ash", "csh", "tcsh",
        # exec wrappers
        "env", "xargs", "nohup", "nice", "ionice", "timeout", "stdbuf", "setsid",
        "chrt", "taskset", "time", "watch", "flock", "chroot", "unshare", "nsenter",
        "busybox", "toybox", "sudo", "su", "doas", "pkexec", "strace", "ltrace",
    }
)  # fmt: skip

# Characters a shell treats as joining or wrapping words: `rm x`, {rm,x}, A=rm, $(rm x).
_WORD_BREAKS = re.compile(r"[`{},=$]")


def _words(text: str) -> list[str]:
    """Split *text* the way a shell would, down to single words.

    A launcher's argument can itself be a command line (``sh -c 'ls; rm x'``),
    so a word that still holds several is split again.
    """
    lexer = shlex.shlex(_WORD_BREAKS.sub(" ", text), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        tokens = text.split()
    words: list[str] = []
    for token in tokens:
        words.extend(_words(token) if token != text and len(token.split()) > 1 else [token])
    return words


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

    # The allow list matches the first token exactly: `git` is the bare command
    # the PATH resolves, and a command written as a path must be listed as that
    # path, so /tmp/x/git cannot pass as git. The block list goes by file name,
    # so /bin/rm is still rm.
    program = tokens[0]
    name = Path(program).name

    if allowed and program not in allowed:
        hint = (
            " (a command written as a path must be listed as that path)" if "/" in program else ""
        )
        return f"Error: command '{program}' is not in the allowed list: {allowed}{hint}"

    if name in blocked:
        return f"Error: command '{name}' is blocked"

    if name in _LAUNCHERS:
        if program not in allowed:
            return (
                f"Error: '{name}' runs other programs, so it is refused unless "
                "it is listed in allowed_commands"
            )
        for arg in tokens[1:]:
            for word in _words(arg):
                if Path(word).name in blocked:
                    return f"Error: command '{Path(word).name}' is blocked (passed to '{name}')"

    return None


@register_tool("shell", ShellToolConfig)
def build_shell_toolset(config: ShellToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for executing commands (no shell)."""
    from initrunner.agent.runtime_sandbox import warn_if_unsandboxed

    backend = ctx.sandbox_backend
    warn_if_unsandboxed(backend, "shell")
    if not config.allowed_commands:
        logger.warning(
            "Shell tool has an empty allowed_commands list: every binary except shells "
            "and other launchers is permitted (an interpreter like 'python -c ...' can "
            "still run anything). Set allowed_commands to the specific binaries the "
            "agent needs."
        )
    elif launchers := sorted(c for c in config.allowed_commands if Path(c).name in _LAUNCHERS):
        logger.warning(
            "Shell tool allows %s, which can run any other program. allowed_commands "
            "does not apply to what they run; only blocked_commands does.",
            ", ".join(launchers),
        )

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
