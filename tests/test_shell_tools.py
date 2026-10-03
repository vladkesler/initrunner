"""Tests for the shell tool: build_shell_toolset and command validation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from initrunner.agent.schema.tools import ShellToolConfig
from initrunner.agent.tools._registry import ToolBuildContext
from initrunner.agent.tools.shell import (
    _check_for_shell_operators,
    _parse_command,
    build_shell_toolset,
    validate_command,
)


def _make_ctx(role_dir=None):
    """Build a minimal ToolBuildContext for tests."""
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
    )
    return ToolBuildContext(role=role, role_dir=role_dir)


class TestCommandValidation:
    def test_simple_command_allowed(self):
        assert validate_command("echo hello", allowed=[], blocked=[]) is None

    def test_allowlist_permits(self):
        assert validate_command("echo hello", allowed=["echo"], blocked=[]) is None

    def test_allowlist_blocks_unlisted(self):
        err = validate_command("curl http://x", allowed=["echo"], blocked=[])
        assert err is not None
        assert "not in the allowed list" in err

    def test_blocklist_blocks(self):
        err = validate_command("rm -rf /", allowed=[], blocked=["rm"])
        assert err is not None
        assert "blocked" in err

    def test_blocklist_allows_unlisted(self):
        assert validate_command("echo hello", allowed=[], blocked=["rm"]) is None

    def test_pipe_rejected(self):
        err = validate_command("echo hi | rm foo", allowed=[], blocked=[])
        assert err is not None
        assert "shell operator" in err

    def test_and_chain_rejected(self):
        err = validate_command("echo hi && sudo reboot", allowed=[], blocked=[])
        assert err is not None
        assert "shell operator" in err

    def test_or_chain_rejected(self):
        err = validate_command("false || rm foo", allowed=[], blocked=[])
        assert err is not None
        assert "shell operator" in err

    def test_semicolon_chain_rejected(self):
        err = validate_command("echo hi ; rm foo", allowed=[], blocked=[])
        assert err is not None
        assert "shell operator" in err

    def test_fork_bomb_detected(self):
        err = validate_command(":() { :|:& };:", allowed=[], blocked=[])
        assert err is not None
        assert "fork bomb" in err

    def test_empty_command(self):
        err = validate_command("", allowed=[], blocked=[])
        assert err is not None
        assert "empty" in err

    def test_redirect_out_rejected(self):
        err = validate_command("echo hello > file.txt", allowed=[], blocked=[])
        assert err is not None
        assert "shell operator" in err

    def test_redirect_in_rejected(self):
        err = validate_command("cat < file.txt", allowed=[], blocked=[])
        assert err is not None
        assert "shell operator" in err

    def test_heredoc_rejected(self):
        err = validate_command("cat << EOF", allowed=[], blocked=[])
        assert err is not None
        assert "shell operator" in err

    def test_background_ampersand_rejected(self):
        err = validate_command("sleep 10 &", allowed=[], blocked=[])
        assert err is not None
        assert "shell operator" in err

    def test_command_substitution_harmless(self):
        # $(whoami) is a literal string token without a shell — passes validation
        assert validate_command("echo $(whoami)", allowed=[], blocked=[]) is None

    def test_backtick_harmless(self):
        # Backticks are literal tokens without a shell — passes validation
        assert validate_command("echo `whoami`", allowed=[], blocked=[]) is None

    def test_unclosed_quote_rejected(self):
        err = validate_command("echo 'hello", allowed=[], blocked=[])
        assert err is not None
        assert "invalid command syntax" in err

    def test_quoted_args_with_spaces(self):
        assert validate_command('grep -r "hello world" .', allowed=[], blocked=[]) is None

    def test_path_does_not_match_a_bare_allow_entry(self):
        err = validate_command("/tmp/not-git/git status", allowed=["git"], blocked=[])
        assert err is not None
        assert "must be listed as that path" in err
        assert validate_command("/usr/bin/git status", allowed=["git"], blocked=[]) is not None

    def test_path_matches_the_same_path_in_the_allow_list(self):
        assert validate_command("/usr/bin/git status", allowed=["/usr/bin/git"], blocked=[]) is None
        assert validate_command("git status", allowed=["/usr/bin/git"], blocked=[]) is not None

    def test_blocklist_matches_a_path_by_file_name(self):
        err = validate_command("/bin/rm -rf /", allowed=[], blocked=["rm"])
        assert err is not None
        assert "blocked" in err


class TestLaunchers:
    """Shells and exec wrappers can run any program, so the lists treat them specially."""

    @pytest.mark.parametrize(
        "command",
        [
            "sh -c 'rm -rf /'",
            "bash -c 'ls'",
            "env rm x",
            "busybox rm x",
            "timeout 5 ls",
            "xargs rm",
            "/bin/sh -c 'ls'",
        ],
    )
    def test_refused_with_an_empty_allow_list(self, command):
        err = validate_command(command, allowed=[], blocked=["rm"])
        assert err is not None
        assert "refused unless it is listed in allowed_commands" in err

    def test_refused_when_not_in_the_allow_list(self):
        err = validate_command("sh -c 'ls'", allowed=["ls"], blocked=[])
        assert err is not None
        assert "not in the allowed list" in err

    def test_sudo_is_a_launcher_even_with_no_block_list(self):
        err = validate_command("sudo ls", allowed=[], blocked=[])
        assert err is not None
        assert "refused unless" in err

    def test_allowed_launcher_runs(self):
        assert validate_command("sh -c 'ls -la'", allowed=["sh"], blocked=["rm"]) is None
        assert validate_command("env FOO=1 make test", allowed=["env"], blocked=["rm"]) is None

    @pytest.mark.parametrize(
        "command",
        [
            "sh -c 'rm -rf /'",
            "sh -c 'ls; rm x'",
            "sh -c 'ls;rm x'",
            "sh -c 'ls && /bin/rm x'",
            "sh -c 'echo $(rm x)'",
            "sh -c 'echo `rm x`'",
            "sh -c \"sh -c 'rm x'\"",
            "sh -c '{rm,-rf,/tmp/x}'",
            "env rm x",
            "env A=rm ls",
            "busybox rm x",
            "xargs rm",
            "timeout 5 /bin/rm x",
        ],
    )
    def test_allowed_launcher_cannot_run_a_blocked_command(self, command):
        launcher = command.split()[0]
        err = validate_command(command, allowed=[launcher], blocked=["rm"])
        assert err is not None
        assert "'rm' is blocked" in err

    def test_ordinary_command_with_a_blocked_word_as_argument(self):
        assert validate_command("git rm file.txt", allowed=[], blocked=["rm"]) is None
        assert validate_command("docker rm web", allowed=["docker"], blocked=["rm"]) is None


class TestParseCommand:
    def test_simple(self):
        assert _parse_command("echo hello") == ["echo", "hello"]

    def test_quoted(self):
        assert _parse_command('grep -r "hello world" .') == ["grep", "-r", "hello world", "."]

    def test_empty(self):
        result = _parse_command("")
        assert isinstance(result, str)
        assert "empty" in result

    def test_unclosed_quotes(self):
        result = _parse_command("echo 'hello")
        assert isinstance(result, str)
        assert "invalid command syntax" in result

    def test_operators_as_tokens(self):
        # shlex.split treats operators as normal tokens
        result = _parse_command("echo hello | grep world")
        assert isinstance(result, list)
        assert "|" in result

    def test_single_quoted_preserves_special(self):
        result = _parse_command("echo '$(whoami)'")
        assert result == ["echo", "$(whoami)"]


class TestCheckForShellOperators:
    def test_pipe(self):
        err = _check_for_shell_operators(["ls", "|", "grep", "foo"])
        assert err is not None
        assert "shell operator" in err

    def test_and(self):
        err = _check_for_shell_operators(["echo", "hi", "&&", "rm", "foo"])
        assert err is not None
        assert "shell operator" in err

    def test_or(self):
        err = _check_for_shell_operators(["false", "||", "echo", "fallback"])
        assert err is not None
        assert "shell operator" in err

    def test_semicolon(self):
        err = _check_for_shell_operators(["echo", "hi", ";", "rm", "foo"])
        assert err is not None
        assert "shell operator" in err

    def test_redirect(self):
        err = _check_for_shell_operators(["echo", "hello", ">", "file.txt"])
        assert err is not None
        assert "shell operator" in err

    def test_background(self):
        err = _check_for_shell_operators(["sleep", "10", "&"])
        assert err is not None
        assert "shell operator" in err

    def test_clean_tokens(self):
        assert _check_for_shell_operators(["echo", "hello", "world"]) is None

    def test_embedded_operator_in_token_allowed(self):
        # "&&" as part of a larger token is not an operator
        assert _check_for_shell_operators(["echo", "foo&&bar"]) is None


class TestShellToolset:
    def test_builds_toolset(self):
        config = ShellToolConfig()
        toolset = build_shell_toolset(config, _make_ctx())
        assert "run_shell" in toolset.tools

    def test_echo(self):
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        output = fn(command="echo hello world")
        assert "hello world" in output

    def test_exit_code_shown(self):
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        output = fn(command="false")
        assert "Exit code:" in output

    def test_launcher_in_the_allow_list_warns(self, monkeypatch, caplog):
        import logging

        monkeypatch.setattr(logging.getLogger("initrunner"), "propagate", True)
        config = ShellToolConfig(allowed_commands=["git", "env"])
        with caplog.at_level(logging.WARNING, logger="initrunner"):
            build_shell_toolset(config, _make_ctx())
        assert "Shell tool allows env, which can run any other program" in caplog.text

    def test_shell_refused_with_default_config(self):
        config = ShellToolConfig(require_confirmation=False)
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        output = fn(command="sh -c 'echo hello'")
        assert "refused unless it is listed in allowed_commands" in output

    def test_blocked_command_rejected(self):
        config = ShellToolConfig(blocked_commands=["rm"])
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        output = fn(command="rm -rf /")
        assert "blocked" in output

    def test_timeout(self):
        config = ShellToolConfig(
            timeout_seconds=1,
            require_confirmation=False,
            blocked_commands=[],
        )
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        output = fn(command="sleep 10")
        assert "timed out" in output

    def test_truncation(self):
        config = ShellToolConfig(
            max_output_bytes=20,
            require_confirmation=False,
            blocked_commands=[],
        )
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        # Generate long output via python one-liner (no shell needed)
        output = fn(command="python3 -c print('x'*200)")
        assert "[truncated]" in output

    def test_working_dir(self, tmp_path: Path):
        config = ShellToolConfig(
            working_dir=str(tmp_path),
            require_confirmation=False,
            blocked_commands=[],
        )
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        output = fn(command="pwd")
        assert str(tmp_path.resolve()) in output

    def test_role_dir_fallback(self, tmp_path: Path):
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["run_shell"].function
        output = fn(command="pwd")
        assert str(tmp_path.resolve()) in output

    def test_sensitive_env_scrubbed(self):
        env_key = "OPENAI_API_KEY"
        old_val = os.environ.get(env_key)
        os.environ[env_key] = "sk-test-secret-key"
        try:
            config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
            toolset = build_shell_toolset(config, _make_ctx())
            fn = toolset.tools["run_shell"].function
            output = fn(command="env")
            assert "sk-test-secret-key" not in output
        finally:
            if old_val is not None:
                os.environ[env_key] = old_val
            else:
                os.environ.pop(env_key, None)

    def test_default_config_values(self):
        config = ShellToolConfig()
        assert config.require_confirmation is True
        assert config.timeout_seconds == 30
        assert "rm" in config.blocked_commands
        assert "sudo" in config.blocked_commands

    def test_stderr_captured(self):
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        output = fn(command="ls /nonexistent_path_xyz_12345")
        assert "STDERR:" in output

    def test_injection_command_substitution_harmless(self):
        """$(rm -rf /) is passed as a literal string, not executed."""
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        output = fn(command="echo $(rm -rf /)")
        assert "$(rm -rf /)" in output

    def test_injection_backtick_harmless(self):
        """Backtick substitution is passed literally, not executed."""
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        output = fn(command="echo `whoami`")
        assert "`whoami`" in output

    def test_pipe_rejected_at_execution(self):
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        output = fn(command="ls | grep foo")
        assert "shell operator" in output

    def test_redirect_rejected_at_execution(self):
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        output = fn(command="echo hello > /tmp/pwned")
        assert "shell operator" in output

    def test_command_not_found(self):
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        output = fn(command="nonexistent_command_xyz_12345")
        assert "not found" in output

    def test_quoted_args_work(self):
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, _make_ctx())
        fn = toolset.tools["run_shell"].function
        output = fn(command='echo "hello world"')
        assert "hello world" in output


class TestShellSchema:
    def test_parses_from_dict(self):
        data = {"type": "shell", "timeout_seconds": 10, "allowed_commands": ["docker"]}
        config = ShellToolConfig.model_validate(data)
        assert config.timeout_seconds == 10
        assert config.allowed_commands == ["docker"]

    def test_summary(self):
        config = ShellToolConfig()
        assert "shell:" in config.summary()
        assert "confirm" in config.summary()

    def test_summary_no_confirm(self):
        config = ShellToolConfig(require_confirmation=False)
        assert "confirm" not in config.summary()
