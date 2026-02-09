"""Tests for the git tool: build_git_toolset and all git tool functions."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from initrunner.agent.git_tools import build_git_toolset
from initrunner.agent.schema import GitToolConfig
from initrunner.agent.tools._registry import ToolBuildContext


def _make_ctx(role_dir=None):
    """Build a minimal ToolBuildContext for tests."""
    from initrunner.agent.schema import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-4o-mini"},
            },
        }
    )
    return ToolBuildContext(role=role, role_dir=role_dir)


def _create_test_repo(path: Path) -> Path:
    """Initialize a git repo with an initial commit at *path*."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test User"],
        capture_output=True,
        check=True,
    )
    # Create initial file and commit
    (path / "README.md").write_text("# Hello\n")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "initial"],
        capture_output=True,
        check=True,
    )
    return path


def _tool_names(toolset) -> set[str]:
    """Return the set of tool names in a toolset."""
    return set(toolset.tools.keys())


def _default_branch(repo: Path) -> str:
    """Return the current branch name of the repo."""
    result = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        capture_output=True,
        check=True,
    )
    return result.stdout.decode().strip()


class TestGitToolset:
    def test_builds_toolset(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        config = GitToolConfig(repo_path=str(repo))
        toolset = build_git_toolset(config, _make_ctx())
        names = _tool_names(toolset)
        assert "git_status" in names
        assert "git_log" in names
        assert "git_diff" in names
        assert "git_show" in names
        assert "git_blame" in names
        assert "git_changed_files" in names
        assert "git_list_files" in names

    def test_read_only_has_no_write_tools(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        config = GitToolConfig(repo_path=str(repo), read_only=True)
        toolset = build_git_toolset(config, _make_ctx())
        names = _tool_names(toolset)
        assert "git_commit" not in names
        assert "git_checkout" not in names
        assert "git_tag" not in names

    def test_writable_has_write_tools(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        config = GitToolConfig(repo_path=str(repo), read_only=False)
        toolset = build_git_toolset(config, _make_ctx())
        names = _tool_names(toolset)
        assert "git_commit" in names
        assert "git_checkout" in names
        assert "git_tag" in names

    def test_status(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        config = GitToolConfig(repo_path=str(repo))
        toolset = build_git_toolset(config, _make_ctx())
        # Create an untracked file
        (repo / "new.txt").write_text("new")
        fn = toolset.tools["git_status"].function
        output = fn()
        assert "new.txt" in output

    def test_log(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        from initrunner.agent.git_tools import _run_git

        output = _run_git(["log", "--max-count=20", "--format=oneline"], str(repo), 30, 102_400)
        assert "initial" in output

    def test_log_compact_format(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        from initrunner.agent.git_tools import _COMPACT_FORMAT, _run_git

        output = _run_git(
            ["log", "--max-count=20", f"--format={_COMPACT_FORMAT}"], str(repo), 30, 102_400
        )
        assert "Test User" in output
        assert "initial" in output

    def test_log_invalid_format(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        config = GitToolConfig(repo_path=str(repo))
        toolset = build_git_toolset(config, _make_ctx())
        fn = toolset.tools["git_log"].function
        output = fn(format="evil-format")
        assert "Error" in output
        assert "invalid format" in output

    def test_diff(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        (repo / "README.md").write_text("# Modified\n")
        from initrunner.agent.git_tools import _run_git

        output = _run_git(["diff"], str(repo), 30, 102_400)
        assert "Modified" in output

    def test_diff_staged(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        (repo / "README.md").write_text("# Staged\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
        from initrunner.agent.git_tools import _run_git

        output = _run_git(["diff", "--cached"], str(repo), 30, 102_400)
        assert "Staged" in output

    def test_diff_truncation_hint(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        (repo / "big.txt").write_text("x" * 200)
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "big"],
            capture_output=True,
            check=True,
        )
        from initrunner.agent.git_tools import _run_git

        output = _run_git(["diff", "HEAD~1"], str(repo), 30, 100)
        assert "[truncated" in output
        assert "path argument" in output
        assert len(output) <= 100

    def test_show(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        from initrunner.agent.git_tools import _run_git

        output = _run_git(["show", "--stat", "--patch", "HEAD"], str(repo), 30, 102_400)
        assert "initial" in output
        assert "README.md" in output

    def test_blame(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        from initrunner.agent.git_tools import _run_git

        output = _run_git(["blame", "README.md"], str(repo), 30, 102_400)
        assert "Test User" in output

    def test_changed_files(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        (repo / "new.txt").write_text("new")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "second"],
            capture_output=True,
            check=True,
        )
        from initrunner.agent.git_tools import _run_git

        output = _run_git(["diff", "--name-status", "HEAD~1"], str(repo), 30, 102_400)
        assert "new.txt" in output

    def test_list_files(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        # Create a gitignored file
        (repo / ".gitignore").write_text("ignored.txt\n")
        (repo / "ignored.txt").write_text("should not show")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "gitignore"],
            capture_output=True,
            check=True,
        )
        from initrunner.agent.git_tools import _run_git

        output = _run_git(["ls-files"], str(repo), 30, 102_400)
        assert "README.md" in output
        assert "ignored.txt" not in output

    def test_list_files_subdir(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        (repo / "sub").mkdir()
        (repo / "sub" / "a.py").write_text("a")
        (repo / "top.py").write_text("top")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "subdir"],
            capture_output=True,
            check=True,
        )
        from initrunner.agent.git_tools import _run_git

        output = _run_git(["ls-files", "sub"], str(repo), 30, 102_400)
        assert "sub/a.py" in output
        assert "top.py" not in output

    def test_checkout_create_branch(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        from initrunner.agent.git_tools import _run_git

        _run_git(["checkout", "-b", "feature"], str(repo), 30, 102_400)
        branch = _run_git(["branch", "--show-current"], str(repo), 30, 102_400)
        assert "feature" in branch

    def test_checkout_existing_branch(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        default = _default_branch(repo)
        from initrunner.agent.git_tools import _run_git

        _run_git(["checkout", "-b", "feature"], str(repo), 30, 102_400)
        _run_git(["checkout", default], str(repo), 30, 102_400)
        branch = _run_git(["branch", "--show-current"], str(repo), 30, 102_400)
        assert default in branch

    def test_commit(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        (repo / "new.txt").write_text("content")
        from initrunner.agent.git_tools import _run_git

        _run_git(["add", "new.txt"], str(repo), 30, 102_400)
        output = _run_git(["commit", "-m", "add new"], str(repo), 30, 102_400)
        assert "add new" in output

    def test_tag(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        from initrunner.agent.git_tools import _run_git

        _run_git(["tag", "v1.0", "HEAD"], str(repo), 30, 102_400)
        output = _run_git(["tag"], str(repo), 30, 102_400)
        assert "v1.0" in output

    def test_annotated_tag(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        from initrunner.agent.git_tools import _run_git

        _run_git(["tag", "-a", "v2.0", "-m", "release", "HEAD"], str(repo), 30, 102_400)
        output = _run_git(["tag", "-n"], str(repo), 30, 102_400)
        assert "v2.0" in output
        assert "release" in output

    def test_output_truncation(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        config = GitToolConfig(repo_path=str(repo), max_output_bytes=100)
        build_git_toolset(config, _make_ctx())
        from initrunner.agent.git_tools import _run_git

        output = _run_git(["log", "--format=medium"], str(repo), 30, 100)
        assert "[truncated" in output
        assert len(output) <= 100

    def test_sensitive_env_scrubbed(self, tmp_path: Path):
        env_key = "OPENAI_API_KEY"
        old_val = os.environ.get(env_key)
        os.environ[env_key] = "sk-test-secret-key"
        try:
            from initrunner.agent._subprocess import scrub_env

            env = scrub_env()
            assert env_key not in env
        finally:
            if old_val is not None:
                os.environ[env_key] = old_val
            else:
                os.environ.pop(env_key, None)

    def test_invalid_repo_path_raises(self, tmp_path: Path):
        config = GitToolConfig(repo_path=str(tmp_path / "nonexistent"))
        with pytest.raises(ValueError, match="not a directory"):
            build_git_toolset(config, _make_ctx())

    def test_non_repo_dir_raises(self, tmp_path: Path):
        config = GitToolConfig(repo_path=str(tmp_path))
        with pytest.raises(ValueError, match="not inside a git repository"):
            build_git_toolset(config, _make_ctx())

    def test_subdirectory_of_repo_valid(self, tmp_path: Path):
        repo = _create_test_repo(tmp_path)
        sub = repo / "subdir"
        sub.mkdir()
        config = GitToolConfig(repo_path=str(sub))
        toolset = build_git_toolset(config, _make_ctx())
        assert _tool_names(toolset)

    def test_read_only_default_true(self):
        config = GitToolConfig()
        assert config.read_only is True
