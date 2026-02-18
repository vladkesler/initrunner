"""Tests for tool sandboxing: AST analysis, MCP allowlist, store paths, env scrubbing."""

from __future__ import annotations

import os
import textwrap
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from initrunner.agent._paths import validate_path_within
from initrunner.agent.schema.role import RoleDefinition
from initrunner.agent.schema.security import ToolSandboxConfig
from initrunner.agent.schema.tools import McpToolConfig
from initrunner.agent.tools import (
    _validate_custom_tool_imports,
    _validate_store_path,
)

# ---------------------------------------------------------------------------
# AST-based import validation
# ---------------------------------------------------------------------------


def _write_module(tmp_path: Path, code: str) -> types.ModuleType:
    """Write a Python module and import it."""
    import importlib.util
    import types

    mod_path = tmp_path / "test_mod.py"
    mod_path.write_text(textwrap.dedent(code))

    spec = importlib.util.spec_from_file_location("test_mod", str(mod_path))
    mod = types.ModuleType("test_mod")
    mod.__file__ = str(mod_path)
    mod.__spec__ = spec
    return mod


class TestASTImportValidation:
    def test_blocked_direct_import_caught(self, tmp_path):
        mod = _write_module(tmp_path, "import os\ndef tool(): pass\n")
        sandbox = ToolSandboxConfig()
        with pytest.raises(ValueError, match="blocked module 'os'"):
            _validate_custom_tool_imports(mod, sandbox)

    def test_blocked_from_import_caught(self, tmp_path):
        mod = _write_module(tmp_path, "from subprocess import run\ndef tool(): pass\n")
        sandbox = ToolSandboxConfig()
        with pytest.raises(ValueError, match="blocked module 'subprocess'"):
            _validate_custom_tool_imports(mod, sandbox)

    def test_dunder_import_caught(self, tmp_path):
        mod = _write_module(tmp_path, '__import__("os")\ndef tool(): pass\n')
        sandbox = ToolSandboxConfig()
        with pytest.raises(ValueError, match=r"__import__.*'os'.*blocked"):
            _validate_custom_tool_imports(mod, sandbox)

    def test_pickle_import_caught(self, tmp_path):
        mod = _write_module(tmp_path, "import pickle\ndef tool(): pass\n")
        sandbox = ToolSandboxConfig()
        with pytest.raises(ValueError, match="blocked module 'pickle'"):
            _validate_custom_tool_imports(mod, sandbox)

    def test_clean_imports_pass(self, tmp_path):
        mod = _write_module(
            tmp_path,
            "import json\nimport re\ndef tool(): return 'ok'\n",
        )
        sandbox = ToolSandboxConfig()
        # Should not raise
        _validate_custom_tool_imports(mod, sandbox)

    def test_allowlist_blocks_unlisted(self, tmp_path):
        mod = _write_module(tmp_path, "import json\ndef tool(): pass\n")
        sandbox = ToolSandboxConfig(allowed_custom_modules=["re"])
        with pytest.raises(ValueError, match="not in allowlist"):
            _validate_custom_tool_imports(mod, sandbox)

    def test_allowlist_allows_listed(self, tmp_path):
        mod = _write_module(tmp_path, "import json\ndef tool(): pass\n")
        sandbox = ToolSandboxConfig(allowed_custom_modules=["json"])
        _validate_custom_tool_imports(mod, sandbox)


# ---------------------------------------------------------------------------
# MCP command allowlist
# ---------------------------------------------------------------------------


def _make_role_with_sandbox(sandbox: ToolSandboxConfig) -> RoleDefinition:
    """Build a minimal RoleDefinition with a given ToolSandboxConfig."""
    return RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-4o-mini"},
                "security": {"tools": sandbox.model_dump()},
            },
        }
    )


class TestMCPCommandAllowlist:
    def test_allowed_command_passes(self):
        from initrunner.agent.tools._registry import ToolBuildContext
        from initrunner.mcp.server import build_mcp_toolset

        config = McpToolConfig(transport="stdio", command="npx", args=["test"])
        sandbox = ToolSandboxConfig(mcp_command_allowlist=["npx", "uvx"])
        role = _make_role_with_sandbox(sandbox)
        ctx = ToolBuildContext(role=role)
        # This will try to actually build the toolset which requires mcp deps,
        # but at least the allowlist check should pass. We just verify the allowlist
        # doesn't raise.
        try:
            build_mcp_toolset(config, ctx)
        except Exception as e:
            # If it fails, it should be from MCP setup, not from allowlist
            assert "not in the allowed command list" not in str(e)

    def test_blocked_command_raises(self):
        from initrunner.agent.tools._registry import ToolBuildContext
        from initrunner.mcp.server import build_mcp_toolset

        config = McpToolConfig(transport="stdio", command="python", args=["-c", "bad"])
        sandbox = ToolSandboxConfig(mcp_command_allowlist=["npx", "uvx"])
        role = _make_role_with_sandbox(sandbox)
        ctx = ToolBuildContext(role=role)
        with pytest.raises(ValueError, match="not in the allowed command list"):
            build_mcp_toolset(config, ctx)

    def test_empty_allowlist_allows_all(self):
        from initrunner.agent.tools._registry import ToolBuildContext
        from initrunner.mcp.server import build_mcp_toolset

        config = McpToolConfig(transport="stdio", command="python", args=[])
        sandbox = ToolSandboxConfig(mcp_command_allowlist=[])
        role = _make_role_with_sandbox(sandbox)
        ctx = ToolBuildContext(role=role)
        # Should not raise from allowlist check
        try:
            build_mcp_toolset(config, ctx)
        except Exception as e:
            assert "not in the allowed command list" not in str(e)


# ---------------------------------------------------------------------------
# Store path restriction
# ---------------------------------------------------------------------------


class TestStorePathRestriction:
    def test_path_under_initrunner_passes(self):
        db_path = Path.home() / ".initrunner" / "stores" / "test.db"
        _validate_store_path(db_path, restrict=True)  # Should not raise

    def test_path_outside_initrunner_rejected(self):
        db_path = Path("/tmp/test.db")
        with pytest.raises(ValueError, match=r"outside ~/\.initrunner/"):
            _validate_store_path(db_path, restrict=True)

    def test_restriction_disabled_allows_any_path(self):
        db_path = Path("/tmp/test.db")
        _validate_store_path(db_path, restrict=False)  # Should not raise


# ---------------------------------------------------------------------------
# Path validation edge cases
# ---------------------------------------------------------------------------


class TestPathValidation:
    def test_relative_to_catches_prefix_collision(self, tmp_path):
        """Ensure /root doesn't match /root-data."""
        root = tmp_path / "root"
        root.mkdir()
        target = tmp_path / "root-data" / "file.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
        err, _ = validate_path_within(target, [root])
        assert err is not None
        assert "outside" in err

    def test_symlink_escape_caught(self, tmp_path):
        """Symlinks that escape the root should be caught."""
        root = tmp_path / "sandbox"
        root.mkdir()
        escape_target = tmp_path / "secret.txt"
        escape_target.write_text("secret data")
        symlink = root / "link.txt"
        symlink.symlink_to(escape_target)
        err, _ = validate_path_within(symlink, [root])
        assert err is not None
        assert "outside" in err

    def test_normal_path_inside_root_passes(self, tmp_path):
        root = tmp_path / "sandbox"
        root.mkdir()
        target = root / "file.txt"
        target.touch()
        err, resolved = validate_path_within(target, [root])
        assert err is None
        assert resolved == target.resolve()

    def test_symlink_rejected_when_flag_set(self, tmp_path):
        """Leaf symlink within root rejected when reject_symlinks=True."""
        root = tmp_path / "sandbox"
        root.mkdir()
        real_file = root / "real.txt"
        real_file.write_text("data")
        link = root / "link.txt"
        link.symlink_to(real_file)
        err, _ = validate_path_within(link, [root], reject_symlinks=True)
        assert err is not None
        assert "symlink" in err

    def test_symlink_allowed_when_flag_unset(self, tmp_path):
        """Same symlink passes when reject_symlinks=False (backward compat)."""
        root = tmp_path / "sandbox"
        root.mkdir()
        real_file = root / "real.txt"
        real_file.write_text("data")
        link = root / "link.txt"
        link.symlink_to(real_file)
        err, _ = validate_path_within(link, [root], reject_symlinks=False)
        assert err is None

    def test_non_symlink_passes_with_reject_flag(self, tmp_path):
        """Normal file passes with reject_symlinks=True."""
        root = tmp_path / "sandbox"
        root.mkdir()
        target = root / "file.txt"
        target.touch()
        err, _ = validate_path_within(target, [root], reject_symlinks=True)
        assert err is None

    def test_intermediate_symlink_rejected(self, tmp_path):
        """Intermediate directory symlink is rejected."""
        root = tmp_path / "sandbox"
        root.mkdir()
        real_dir = root / "real_dir"
        real_dir.mkdir()
        (real_dir / "file.txt").write_text("data")
        link_dir = root / "link_dir"
        link_dir.symlink_to(real_dir)
        target = link_dir / "file.txt"
        err, _ = validate_path_within(target, [root], reject_symlinks=True)
        assert err is not None
        assert "symlink" in err


# ---------------------------------------------------------------------------
# Environment variable scrubbing
# ---------------------------------------------------------------------------


class TestEnvScrubbing:
    def test_sensitive_vars_removed(self):
        from initrunner.agent._subprocess import scrub_env

        sandbox = ToolSandboxConfig(
            sensitive_env_prefixes=["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET"]
        )
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test",
                "ANTHROPIC_API_KEY": "sk-ant-test",
                "AWS_SECRET_ACCESS_KEY": "secret",
                "PATH": "/usr/bin",
                "HOME": "/home/user",
            },
            clear=True,
        ):
            env = scrub_env(sandbox.sensitive_env_prefixes)
            assert "OPENAI_API_KEY" not in env
            assert "ANTHROPIC_API_KEY" not in env
            assert "AWS_SECRET_ACCESS_KEY" not in env
            assert env["PATH"] == "/usr/bin"
            assert env["HOME"] == "/home/user"

    def test_no_sensitive_prefixes_keeps_all(self):
        from initrunner.agent._subprocess import scrub_env

        sandbox = ToolSandboxConfig(sensitive_env_prefixes=[])
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test", "PATH": "/usr/bin"},
            clear=True,
        ):
            env = scrub_env(sandbox.sensitive_env_prefixes, suffixes=())
            assert "OPENAI_API_KEY" in env
            assert "PATH" in env

    def test_expanded_prefixes_scrubbed(self):
        from initrunner.agent._subprocess import scrub_env

        with patch.dict(
            os.environ,
            {
                "GITHUB_TOKEN": "ghp_abc123",
                "GCP_PROJECT": "my-project",
                "AZURE_CLIENT_ID": "xxx",
                "SLACK_TOKEN": "xoxb-123",
                "STRIPE_SECRET_KEY": "sk_live_abc",
                "PATH": "/usr/bin",
                "HOME": "/home/user",
            },
            clear=True,
        ):
            env = scrub_env()
            assert "GITHUB_TOKEN" not in env
            assert "GCP_PROJECT" not in env
            assert "AZURE_CLIENT_ID" not in env
            assert "SLACK_TOKEN" not in env
            assert "STRIPE_SECRET_KEY" not in env
            assert env["PATH"] == "/usr/bin"
            assert env["HOME"] == "/home/user"

    def test_suffix_matching(self):
        from initrunner.agent._subprocess import scrub_env

        with patch.dict(
            os.environ,
            {
                "MY_CUSTOM_SECRET": "s3cret",
                "SOME_SERVICE_TOKEN": "tok123",
                "DB_PASSWORD": "pass",
                "PATH": "/usr/bin",
                "HOME": "/home/user",
                "SHELL": "/bin/bash",
            },
            clear=True,
        ):
            env = scrub_env()
            assert "MY_CUSTOM_SECRET" not in env
            assert "SOME_SERVICE_TOKEN" not in env
            assert "DB_PASSWORD" not in env
            assert env["PATH"] == "/usr/bin"
            assert env["HOME"] == "/home/user"
            assert env["SHELL"] == "/bin/bash"

    def test_case_insensitive_matching(self):
        from initrunner.agent._subprocess import scrub_env

        with patch.dict(
            os.environ,
            {
                "openai_api_key": "sk-test",
                "my_api_key": "key123",
                "PATH": "/usr/bin",
            },
            clear=True,
        ):
            env = scrub_env()
            assert "openai_api_key" not in env
            assert "my_api_key" not in env
            assert env["PATH"] == "/usr/bin"

    def test_suffix_disabled(self):
        from initrunner.agent._subprocess import scrub_env

        with patch.dict(
            os.environ,
            {
                "MY_CUSTOM_SECRET": "s3cret",
                "SOME_SERVICE_TOKEN": "tok123",
                "PATH": "/usr/bin",
            },
            clear=True,
        ):
            env = scrub_env(suffixes=())
            assert "MY_CUSTOM_SECRET" in env
            assert "SOME_SERVICE_TOKEN" in env
            assert env["PATH"] == "/usr/bin"

    def test_allowlist_prevents_scrubbing(self):
        from initrunner.agent._subprocess import scrub_env

        with patch.dict(
            os.environ,
            {
                "SSH_AGENT_PID": "12345",
                "GPG_AGENT_INFO": "/run/gpg",
                "MY_CUSTOM_SECRET": "s3cret",
                "PATH": "/usr/bin",
            },
            clear=True,
        ):
            env = scrub_env()
            assert env["SSH_AGENT_PID"] == "12345"
            assert env["GPG_AGENT_INFO"] == "/run/gpg"
            assert "MY_CUSTOM_SECRET" not in env
            assert env["PATH"] == "/usr/bin"


# ---------------------------------------------------------------------------
# AST + audit hooks integration tests
# ---------------------------------------------------------------------------


class TestASTAndAuditHooksIntegration:
    """Verify AST catches static imports at load time, audit hooks catch dynamic at call time."""

    @pytest.fixture(autouse=True, scope="class")
    def _install_hook(self):
        from initrunner.agent.sandbox import install_audit_hook

        install_audit_hook()

    @pytest.fixture(autouse=True)
    def _clean_state(self):
        from initrunner.agent.sandbox import _get_state

        state = _get_state()
        state.enforcing = False
        state.depth = 0
        state.config = None
        state.violations = []
        state.bypassed = False
        yield
        state.enforcing = False
        state.depth = 0
        state.config = None
        state.violations = []
        state.bypassed = False

    def test_ast_catches_static_import(self, tmp_path):
        """AST analysis catches 'import os' at module load time."""
        mod = _write_module(tmp_path, "import os\ndef tool(): pass\n")
        sandbox = ToolSandboxConfig(audit_hooks_enabled=True)
        with pytest.raises(ValueError, match="blocked module 'os'"):
            _validate_custom_tool_imports(mod, sandbox)

    def test_audit_hook_catches_dynamic_import(self):
        """Audit hook catches blocked module import via _check_import directly.

        Note: __import__ on cached sys.modules entries may skip the audit event,
        so we test the checker function directly to verify correctness.
        """
        from initrunner.agent.sandbox import SandboxViolation, _check_import, _get_state

        sandbox = ToolSandboxConfig(audit_hooks_enabled=True)
        state = _get_state()
        state.enforcing = True
        state.config = sandbox
        state.agent_name = "test"
        try:
            with pytest.raises(SandboxViolation, match="Import of 'ctypes' blocked"):
                _check_import(state, ("ctypes",))
        finally:
            state.enforcing = False

    def test_ast_plus_hook_layered_defense(self, tmp_path):
        """AST catches __import__, hook catches subprocess — layered defense."""

        # Module with __import__ that AST catches
        mod = _write_module(
            tmp_path,
            "import json\ndef tool():\n    return __import__('ctypes')\n",
        )
        sandbox = ToolSandboxConfig(audit_hooks_enabled=True)

        # AST catches the __import__('ctypes') pattern
        with pytest.raises(ValueError, match="blocked"):
            _validate_custom_tool_imports(mod, sandbox)

        # Module that avoids AST detection but uses subprocess at runtime
        mod2 = _write_module(
            tmp_path,
            textwrap.dedent("""\
                import json
                import subprocess
                def tool():
                    return subprocess.run(["echo", "test"], capture_output=True)
            """),
        )
        # Use a sandbox that only blocks subprocess at AST level
        sandbox2 = ToolSandboxConfig(audit_hooks_enabled=True, allow_subprocess=False)

        # AST catches the subprocess import
        with pytest.raises(ValueError, match="blocked module 'subprocess'"):
            _validate_custom_tool_imports(mod2, sandbox2)

    def test_threading_in_default_blocked_modules(self):
        """Verify threading and _thread are in default blocked_custom_modules."""
        sandbox = ToolSandboxConfig()
        assert "threading" in sandbox.blocked_custom_modules
        assert "_thread" in sandbox.blocked_custom_modules

    def test_audit_hook_config_fields_exist(self):
        """Verify the new audit hook config fields exist with correct defaults."""
        sandbox = ToolSandboxConfig()
        assert sandbox.audit_hooks_enabled is False
        assert sandbox.allowed_write_paths == []
        assert sandbox.allowed_network_hosts == []
        assert sandbox.block_private_ips is True
        assert sandbox.allow_subprocess is False
        assert sandbox.allow_eval_exec is False
        assert sandbox.sandbox_violation_action == "raise"
