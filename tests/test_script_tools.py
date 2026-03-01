"""Tests for the script tool: config validation, builder, and execution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from initrunner.agent.schema.tools import (
    ScriptDefinition,
    ScriptParameter,
    ScriptToolConfig,
)
from initrunner.agent.tools._registry import ToolBuildContext, get_tool_types
from initrunner.agent.tools.script import (
    _validate_script_body,
    build_script_toolset,
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


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestScriptConfig:
    def test_valid_config(self):
        config = ScriptToolConfig(scripts=[ScriptDefinition(name="hello", body="echo hello")])
        assert config.type == "script"
        assert len(config.scripts) == 1

    def test_invalid_identifier(self):
        with pytest.raises(ValueError, match="not a valid Python identifier"):
            ScriptDefinition(name="not-valid", body="echo hi")

    def test_empty_body_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            ScriptDefinition(name="empty", body="   ")

    def test_empty_scripts_rejected(self):
        with pytest.raises(ValueError, match="at least one script"):
            ScriptToolConfig(scripts=[])

    def test_duplicate_names_rejected(self):
        with pytest.raises(ValueError, match="unique"):
            ScriptToolConfig(
                scripts=[
                    ScriptDefinition(name="dup", body="echo 1"),
                    ScriptDefinition(name="dup", body="echo 2"),
                ]
            )

    def test_summary_single(self):
        config = ScriptToolConfig(scripts=[ScriptDefinition(name="hello", body="echo hi")])
        assert config.summary() == "script: hello"

    def test_summary_multiple(self):
        config = ScriptToolConfig(
            scripts=[
                ScriptDefinition(name="a", body="echo a"),
                ScriptDefinition(name="b", body="echo b"),
                ScriptDefinition(name="c", body="echo c"),
                ScriptDefinition(name="d", body="echo d"),
            ]
        )
        summary = config.summary()
        assert "a, b, c" in summary
        assert "+1 more" in summary

    def test_parameter_identifier_validation(self):
        with pytest.raises(ValueError, match="not a valid Python identifier"):
            ScriptParameter(name="bad-name")

    def test_per_script_overrides(self):
        script = ScriptDefinition(
            name="custom",
            body="echo hi",
            interpreter="/bin/bash",
            timeout_seconds=5,
        )
        assert script.interpreter == "/bin/bash"
        assert script.timeout_seconds == 5

    def test_from_dict(self):
        data = {
            "type": "script",
            "scripts": [{"name": "greet", "body": "echo hello"}],
        }
        config = ScriptToolConfig.model_validate(data)
        assert config.scripts[0].name == "greet"

    def test_defaults(self):
        config = ScriptToolConfig(scripts=[ScriptDefinition(name="x", body="echo x")])
        assert config.interpreter == "/bin/sh"
        assert config.timeout_seconds == 30
        assert config.max_output_bytes == 102_400
        assert config.working_dir is None


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class TestScriptBuilder:
    def test_correct_tool_count(self):
        config = ScriptToolConfig(
            scripts=[
                ScriptDefinition(name="a", body="echo a"),
                ScriptDefinition(name="b", body="echo b"),
            ]
        )
        toolset = build_script_toolset(config, _make_ctx())
        assert len(toolset.tools) == 2

    def test_tool_names_match(self):
        config = ScriptToolConfig(scripts=[ScriptDefinition(name="my_tool", body="echo hi")])
        toolset = build_script_toolset(config, _make_ctx())
        assert "my_tool" in toolset.tools

    def test_description_set(self):
        config = ScriptToolConfig(
            scripts=[ScriptDefinition(name="my_tool", body="echo hi", description="Does things")]
        )
        toolset = build_script_toolset(config, _make_ctx())
        assert toolset.tools["my_tool"].description == "Does things"

    def test_signature_has_declared_params(self):
        config = ScriptToolConfig(
            scripts=[
                ScriptDefinition(
                    name="greet",
                    body="echo $NAME",
                    parameters=[
                        ScriptParameter(name="name", required=True),
                        ScriptParameter(name="greeting", default="hello"),
                    ],
                )
            ]
        )
        toolset = build_script_toolset(config, _make_ctx())
        import inspect

        sig = inspect.signature(toolset.tools["greet"].function)
        assert "name" in sig.parameters
        assert "greeting" in sig.parameters
        # Required param has no default
        assert sig.parameters["name"].default is inspect.Parameter.empty
        # Optional param has a default
        assert sig.parameters["greeting"].default == "hello"

    def test_no_parameter_script(self):
        config = ScriptToolConfig(scripts=[ScriptDefinition(name="info", body="echo info")])
        toolset = build_script_toolset(config, _make_ctx())
        import inspect

        sig = inspect.signature(toolset.tools["info"].function)
        assert len(sig.parameters) == 0


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class TestScriptExecution:
    def test_echo_output(self):
        config = ScriptToolConfig(scripts=[ScriptDefinition(name="greet", body="echo hello world")])
        toolset = build_script_toolset(config, _make_ctx())
        fn = toolset.tools["greet"].function
        output = fn()
        assert "hello world" in output

    def test_parameter_uppercased_in_env(self):
        config = ScriptToolConfig(
            scripts=[
                ScriptDefinition(
                    name="greet",
                    body='echo "Hi $NAME"',
                    interpreter="/bin/bash",
                    parameters=[ScriptParameter(name="name", required=True)],
                )
            ]
        )
        toolset = build_script_toolset(config, _make_ctx())
        fn = toolset.tools["greet"].function
        output = fn(name="Alice")
        assert "Hi Alice" in output

    def test_nonzero_exit_code(self):
        config = ScriptToolConfig(scripts=[ScriptDefinition(name="fail", body="exit 42")])
        toolset = build_script_toolset(config, _make_ctx())
        fn = toolset.tools["fail"].function
        output = fn()
        assert "Exit code:" in output
        assert "42" in output

    def test_stderr_captured(self):
        config = ScriptToolConfig(
            scripts=[ScriptDefinition(name="warn", body="echo oops >&2", interpreter="/bin/bash")]
        )
        toolset = build_script_toolset(config, _make_ctx())
        fn = toolset.tools["warn"].function
        output = fn()
        assert "STDERR:" in output
        assert "oops" in output

    def test_timeout(self):
        config = ScriptToolConfig(
            scripts=[ScriptDefinition(name="slow", body="sleep 30", timeout_seconds=1)]
        )
        toolset = build_script_toolset(config, _make_ctx())
        fn = toolset.tools["slow"].function
        with pytest.raises(Exception, match="timed out"):
            fn()

    def test_output_truncation(self):
        config = ScriptToolConfig(
            max_output_bytes=20,
            scripts=[
                ScriptDefinition(
                    name="big",
                    body="python3 -c \"print('x' * 200)\"",
                    interpreter="/bin/bash",
                )
            ],
        )
        toolset = build_script_toolset(config, _make_ctx())
        fn = toolset.tools["big"].function
        output = fn()
        assert "[truncated]" in output

    def test_working_dir(self, tmp_path: Path):
        config = ScriptToolConfig(
            working_dir=str(tmp_path),
            scripts=[ScriptDefinition(name="where", body="pwd")],
        )
        toolset = build_script_toolset(config, _make_ctx())
        fn = toolset.tools["where"].function
        output = fn()
        assert str(tmp_path.resolve()) in output

    def test_role_dir_fallback(self, tmp_path: Path):
        config = ScriptToolConfig(scripts=[ScriptDefinition(name="where", body="pwd")])
        toolset = build_script_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["where"].function
        output = fn()
        assert str(tmp_path.resolve()) in output

    def test_sensitive_env_scrubbed(self):
        env_key = "OPENAI_API_KEY"
        old_val = os.environ.get(env_key)
        os.environ[env_key] = "sk-test-secret-key"
        try:
            config = ScriptToolConfig(
                scripts=[ScriptDefinition(name="leak", body="env", interpreter="/bin/bash")]
            )
            toolset = build_script_toolset(config, _make_ctx())
            fn = toolset.tools["leak"].function
            output = fn()
            assert "sk-test-secret-key" not in output
        finally:
            if old_val is not None:
                os.environ[env_key] = old_val
            else:
                os.environ.pop(env_key, None)

    def test_missing_interpreter(self):
        config = ScriptToolConfig(
            interpreter="/nonexistent/interpreter",
            scripts=[ScriptDefinition(name="bad", body="echo hi")],
        )
        toolset = build_script_toolset(config, _make_ctx())
        fn = toolset.tools["bad"].function
        output = fn()
        assert "not found" in output

    def test_default_parameter_value(self):
        config = ScriptToolConfig(
            scripts=[
                ScriptDefinition(
                    name="greet",
                    body='echo "Hi $NAME"',
                    interpreter="/bin/bash",
                    parameters=[
                        ScriptParameter(name="name", default="World"),
                    ],
                )
            ]
        )
        toolset = build_script_toolset(config, _make_ctx())
        fn = toolset.tools["greet"].function
        # Call without providing the parameter — should use default
        output = fn()
        assert "Hi World" in output

    def test_custom_interpreter(self):
        config = ScriptToolConfig(
            scripts=[
                ScriptDefinition(
                    name="pyecho",
                    body="print('from python')",
                    interpreter="python3",
                )
            ]
        )
        toolset = build_script_toolset(config, _make_ctx())
        fn = toolset.tools["pyecho"].function
        output = fn()
        assert "from python" in output


# ---------------------------------------------------------------------------
# Constrained execution (allowed_commands)
# ---------------------------------------------------------------------------


class TestScriptValidation:
    def test_disallowed_command_rejected(self):
        err = _validate_script_body("curl http://example.com", ["echo"])
        assert err is not None
        assert "not in the allowed list" in err

    def test_operator_rejected(self):
        err = _validate_script_body("echo hi | grep hi", ["echo", "grep"])
        assert err is not None
        assert "shell operator" in err

    def test_allowed_command_passes(self):
        err = _validate_script_body("echo hello", ["echo"])
        assert err is None

    def test_empty_allowed_skips_validation(self):
        # Empty list means no validation — let anything through
        err = _validate_script_body("curl http://evil.com", [])
        assert err is None

    def test_comments_and_blanks_skipped(self):
        body = "# comment\n\necho hello\n"
        err = _validate_script_body(body, ["echo"])
        assert err is None

    def test_full_path_command(self):
        err = _validate_script_body("/usr/bin/echo hello", ["echo"])
        assert err is None

    def test_execution_with_allowed_commands(self):
        config = ScriptToolConfig(
            scripts=[
                ScriptDefinition(
                    name="safe",
                    body="echo safe output",
                    allowed_commands=["echo"],
                )
            ]
        )
        toolset = build_script_toolset(config, _make_ctx())
        fn = toolset.tools["safe"].function
        output = fn()
        assert "safe output" in output

    def test_execution_blocked_by_allowed_commands(self):
        config = ScriptToolConfig(
            scripts=[
                ScriptDefinition(
                    name="blocked",
                    body="curl http://evil.com",
                    allowed_commands=["echo"],
                )
            ]
        )
        toolset = build_script_toolset(config, _make_ctx())
        fn = toolset.tools["blocked"].function
        output = fn()
        assert "not in the allowed list" in output


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestScriptRegistration:
    def test_registered_in_tool_types(self):
        types = get_tool_types()
        assert "script" in types
        assert types["script"] is ScriptToolConfig

    def test_parse_tool_list_recognizes_script(self):
        from initrunner.agent.schema.role import parse_tool_list

        result = parse_tool_list(
            [{"type": "script", "scripts": [{"name": "hi", "body": "echo hi"}]}]
        )
        assert len(result) == 1
        assert isinstance(result[0], ScriptToolConfig)
