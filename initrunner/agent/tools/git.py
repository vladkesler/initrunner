"""Git tool: runs git commands in a subprocess with isolation."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._subprocess import SubprocessTimeout, run_subprocess_text
from initrunner.agent._truncate import truncate_output
from initrunner.agent.schema.tools import GitToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

_ALLOWED_LOG_FORMATS = {"oneline", "short", "medium", "full", "compact"}

_SAFE_REF_RE = re.compile(r"^[a-zA-Z0-9_./:~^{}\-@]+$")


def _sanitize_ref(ref: str) -> str | None:
    """Return error string if ref looks like a flag or contains unsafe chars."""
    if ref.startswith("-"):
        return f"Error: invalid ref '{ref}' (must not start with '-')"
    if not _SAFE_REF_RE.match(ref):
        return f"Error: invalid ref '{ref}' (contains unsafe characters)"
    return None


def _sanitize_path(path: str) -> str | None:
    """Return error string if path looks like a flag."""
    if path.startswith("-"):
        return f"Error: invalid path '{path}' (must not start with '-')"
    return None


_COMPACT_FORMAT = "%h %an %s"


def _run_git(
    args: list[str],
    repo_path: str,
    timeout: int,
    max_output: int,
) -> str:
    """Run a git command and return its output."""
    cmd = ["git", "-C", repo_path, *args]
    try:
        stdout, stderr, returncode = run_subprocess_text(cmd, timeout=timeout)
    except SubprocessTimeout as exc:
        return str(exc)

    if returncode != 0 and stderr:
        return f"Error: {stderr.strip()}"

    output = stdout
    if stderr and returncode == 0:
        output = f"{stdout}\n{stderr}" if stdout else stderr

    output = truncate_output(
        output, max_output, "\n[truncated — use the path argument to narrow results]"
    )

    return output if output else "(no output)"


def _validate_repo_path(repo_path: str) -> str | None:
    """Validate that repo_path is inside a git work tree. Returns error string or None."""
    path = Path(repo_path).resolve()
    if not path.is_dir():
        return f"Error: '{repo_path}' is not a directory"
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return f"Error: '{repo_path}' is not inside a git repository"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return f"Error: could not validate git repository at '{repo_path}'"
    return None


@register_tool("git", GitToolConfig)
def build_git_toolset(config: GitToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for git operations."""
    repo_path = str(Path(config.repo_path).resolve())

    if err := _validate_repo_path(repo_path):
        raise ValueError(err)

    timeout = config.timeout_seconds
    max_output = config.max_output_bytes

    toolset = FunctionToolset()

    # --- Read tools (always registered) ---

    @toolset.tool
    def git_status() -> str:
        """Show the working tree status (short format)."""
        return _run_git(["status", "--short"], repo_path, timeout, max_output)

    @toolset.tool
    def git_log(max_count: int = 20, format: str = "oneline") -> str:
        """Show commit log.

        Format: oneline, short, medium, full, or compact (hash author subject).
        """
        if format not in _ALLOWED_LOG_FORMATS:
            allowed = ", ".join(sorted(_ALLOWED_LOG_FORMATS))
            return f"Error: invalid format '{format}'. Allowed: {allowed}"
        max_count = max(1, min(max_count, 100))
        if format == "compact":
            return _run_git(
                ["log", f"--max-count={max_count}", f"--format={_COMPACT_FORMAT}"],
                repo_path,
                timeout,
                max_output,
            )
        return _run_git(
            ["log", f"--max-count={max_count}", f"--format={format}"],
            repo_path,
            timeout,
            max_output,
        )

    @toolset.tool
    def git_diff(ref: str = "", staged: bool = False, path: str = "") -> str:
        """Show changes in the working tree or between refs.

        Use the path argument to narrow diffs if output is truncated.
        """
        if ref:
            if err := _sanitize_ref(ref):
                return err
        if path:
            if err := _sanitize_path(path):
                return err
        args = ["diff"]
        if staged:
            args.append("--cached")
        if ref:
            args.append(ref)
        if path:
            args.extend(["--", path])
        return _run_git(args, repo_path, timeout, max_output)

    @toolset.tool
    def git_show(ref: str = "HEAD") -> str:
        """Show details of a commit (stat and patch)."""
        if err := _sanitize_ref(ref):
            return err
        return _run_git(["show", "--stat", "--patch", ref], repo_path, timeout, max_output)

    @toolset.tool
    def git_blame(path: str) -> str:
        """Show line-by-line authorship of a file."""
        if err := _sanitize_path(path):
            return err
        return _run_git(["blame", "--", path], repo_path, timeout, max_output)

    @toolset.tool
    def git_changed_files(ref: str = "HEAD~1") -> str:
        """List files changed compared to a ref (name and status)."""
        if err := _sanitize_ref(ref):
            return err
        return _run_git(["diff", "--name-status", ref], repo_path, timeout, max_output)

    @toolset.tool
    def git_list_files(path: str = "") -> str:
        """List tracked files in the repository. Optional path to scope to a subdirectory."""
        if path:
            if err := _sanitize_path(path):
                return err
        args = ["ls-files"]
        if path:
            args.extend(["--", path])
        return _run_git(args, repo_path, timeout, max_output)

    # --- Write tools (only when read_only=False) ---

    if not config.read_only:

        @toolset.tool
        def git_checkout(branch: str, create: bool = False) -> str:
            """Switch to a branch, or create a new one with create=True."""
            if err := _sanitize_ref(branch):
                return err
            args = ["checkout"]
            if create:
                args.append("-b")
            args.append(branch)
            return _run_git(args, repo_path, timeout, max_output)

        @toolset.tool
        def git_commit(message: str, paths: str = ".") -> str:
            """Stage files and create a commit."""
            if err := _sanitize_path(paths):
                return err
            add_result = _run_git(["add", "--", paths], repo_path, timeout, max_output)
            if add_result.startswith("Error:"):
                return add_result
            return _run_git(["commit", "-m", message], repo_path, timeout, max_output)

        @toolset.tool
        def git_tag(name: str, message: str = "", ref: str = "HEAD") -> str:
            """Create a tag. If message is provided, creates an annotated tag."""
            if err := _sanitize_ref(name):
                return err
            if err := _sanitize_ref(ref):
                return err
            if message:
                return _run_git(
                    ["tag", "-a", name, "-m", message, ref], repo_path, timeout, max_output
                )
            return _run_git(["tag", name, ref], repo_path, timeout, max_output)

    return toolset
