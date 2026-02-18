"""Tests for the Python execution tool."""

from __future__ import annotations

import os

from initrunner.agent.python_tools import build_python_toolset
from initrunner.agent.schema.tools import PythonToolConfig
from initrunner.agent.tools._registry import ToolBuildContext


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


class TestPythonToolset:
    def test_builds_toolset(self):
        config = PythonToolConfig()
        toolset = build_python_toolset(config, _make_ctx())
        assert "run_python" in toolset.tools

    def test_simple_print(self):
        config = PythonToolConfig(require_confirmation=False)
        toolset = build_python_toolset(config, _make_ctx())
        fn = toolset.tools["run_python"].function
        result = fn(code='print("hello world")')
        assert "hello world" in result

    def test_captures_stderr(self):
        config = PythonToolConfig(require_confirmation=False)
        toolset = build_python_toolset(config, _make_ctx())
        fn = toolset.tools["run_python"].function
        result = fn(code='import sys; sys.stderr.write("warning\\n")')
        assert "STDERR:" in result
        assert "warning" in result

    def test_timeout(self):
        config = PythonToolConfig(timeout_seconds=1, require_confirmation=False)
        toolset = build_python_toolset(config, _make_ctx())
        fn = toolset.tools["run_python"].function
        result = fn(code="import time; time.sleep(10)")
        assert "timed out" in result

    def test_output_truncation(self):
        config = PythonToolConfig(max_output_bytes=50, require_confirmation=False)
        toolset = build_python_toolset(config, _make_ctx())
        fn = toolset.tools["run_python"].function
        result = fn(code='print("x" * 1000)')
        assert "[truncated]" in result

    def test_syntax_error(self):
        config = PythonToolConfig(require_confirmation=False)
        toolset = build_python_toolset(config, _make_ctx())
        fn = toolset.tools["run_python"].function
        result = fn(code="def f(\n")
        assert "STDERR:" in result
        assert "SyntaxError" in result

    def test_working_dir(self, tmp_path):
        config = PythonToolConfig(working_dir=str(tmp_path), require_confirmation=False)
        toolset = build_python_toolset(config, _make_ctx())
        fn = toolset.tools["run_python"].function
        result = fn(code="import os; print(os.getcwd())")
        assert str(tmp_path) in result

    def test_sensitive_env_scrubbed(self):
        config = PythonToolConfig(require_confirmation=False)
        toolset = build_python_toolset(config, _make_ctx())
        fn = toolset.tools["run_python"].function
        # Set a sensitive env var temporarily
        os.environ["OPENAI_API_KEY"] = "sk-test-secret"
        try:
            result = fn(code='import os; print(os.environ.get("OPENAI_API_KEY", "MISSING"))')
            assert "MISSING" in result
            assert "sk-test-secret" not in result
        finally:
            del os.environ["OPENAI_API_KEY"]

    def test_confirmation_default_true(self):
        config = PythonToolConfig()
        assert config.require_confirmation is True
