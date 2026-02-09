"""Tests for PEP 578 audit hook sandbox."""

from __future__ import annotations

import socket
import subprocess

import pytest

from initrunner.agent.sandbox import (
    SandboxViolation,
    _framework_bypass,
    _get_state,
    install_audit_hook,
    sandbox_scope,
    set_audit_logger,
)
from initrunner.agent.schema import ToolSandboxConfig


@pytest.fixture(autouse=True, scope="session")
def _install_hook():
    """Install the audit hook once for the entire test session."""
    install_audit_hook()


@pytest.fixture(autouse=True)
def _clean_state():
    """Ensure sandbox state is clean before and after each test."""
    state = _get_state()
    state.enforcing = False
    state.depth = 0
    state.config = None
    state.agent_name = ""
    state.violations = []
    state.bypassed = False
    yield
    state.enforcing = False
    state.depth = 0
    state.config = None
    state.agent_name = ""
    state.violations = []
    state.bypassed = False


# ---------------------------------------------------------------------------
# Sandbox scope behavior
# ---------------------------------------------------------------------------


class TestSandboxScope:
    def test_enforcement_on_inside_scope(self):
        config = ToolSandboxConfig(audit_hooks_enabled=True)
        state = _get_state()
        assert not state.enforcing
        with sandbox_scope(config=config, agent_name="test"):
            assert state.enforcing
        assert not state.enforcing

    def test_enforcement_off_outside_scope(self):
        state = _get_state()
        assert not state.enforcing

    def test_reentrant_scope(self):
        config = ToolSandboxConfig(audit_hooks_enabled=True)
        state = _get_state()
        with sandbox_scope(config=config, agent_name="outer"):
            assert state.depth == 1
            with sandbox_scope(config=config, agent_name="inner"):
                assert state.depth == 2
                assert state.enforcing
            assert state.depth == 1
            assert state.enforcing
        assert state.depth == 0
        assert not state.enforcing

    def test_framework_bypass_disables_enforcement(self):
        config = ToolSandboxConfig(audit_hooks_enabled=True)
        state = _get_state()
        with sandbox_scope(config=config, agent_name="test"):
            assert state.enforcing
            with _framework_bypass():
                assert not state.enforcing
            assert state.enforcing

    def test_violations_cleared_on_exit(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            sandbox_violation_action="log",
            allow_subprocess=False,
        )
        state = _get_state()
        with sandbox_scope(config=config, agent_name="test"):
            try:
                subprocess.Popen(["echo", "test"])
            except (SandboxViolation, OSError):
                pass
        # Violations should be cleared after scope exit
        assert state.violations == []


# ---------------------------------------------------------------------------
# Filesystem hooks
# ---------------------------------------------------------------------------


class TestFileSystemHooks:
    def test_read_always_allowed(self, tmp_path):
        config = ToolSandboxConfig(audit_hooks_enabled=True)
        test_file = tmp_path / "readable.txt"
        test_file.write_text("hello")
        with sandbox_scope(config=config, agent_name="test"):
            content = test_file.read_text()
            assert content == "hello"

    def test_write_blocked_no_allowed_paths(self, tmp_path):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            allowed_write_paths=[],
        )
        test_file = tmp_path / "blocked.txt"
        with sandbox_scope(config=config, agent_name="test"):
            with pytest.raises(SandboxViolation, match=r"Write to.*blocked"):
                test_file.write_text("should fail")

    def test_write_allowed_within_path(self, tmp_path):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            allowed_write_paths=[str(tmp_path)],
        )
        test_file = tmp_path / "allowed.txt"
        with sandbox_scope(config=config, agent_name="test"):
            test_file.write_text("should succeed")
            assert test_file.read_text() == "should succeed"

    def test_write_blocked_outside_allowed_path(self, tmp_path):
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        blocked_dir = tmp_path / "blocked"
        blocked_dir.mkdir()

        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            allowed_write_paths=[str(allowed_dir)],
        )
        test_file = blocked_dir / "nope.txt"
        with sandbox_scope(config=config, agent_name="test"):
            with pytest.raises(SandboxViolation, match="not in allowed_write_paths"):
                test_file.write_text("should fail")


# ---------------------------------------------------------------------------
# Network hooks
# ---------------------------------------------------------------------------


class TestNetworkHooks:
    def test_private_ip_blocked(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            block_private_ips=True,
        )
        with sandbox_scope(config=config, agent_name="test"):
            with pytest.raises(SandboxViolation, match=r"private IP.*127\.0\.0\.1"):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    s.connect(("127.0.0.1", 65432))
                finally:
                    s.close()

    def test_private_ip_allowed_when_disabled(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            block_private_ips=False,
        )
        with sandbox_scope(config=config, agent_name="test"):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                # Will fail to connect but shouldn't raise SandboxViolation
                s.settimeout(0.01)
                with pytest.raises(OSError):
                    s.connect(("127.0.0.1", 65432))
            finally:
                s.close()

    def test_hostname_allowlist_blocks_unlisted(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            allowed_network_hosts=["example.com"],
            allow_eval_exec=True,  # allow internal compile/exec from encoding lookups
        )
        with sandbox_scope(config=config, agent_name="test"):
            with pytest.raises(SandboxViolation, match=r"DNS resolution.*blocked"):
                socket.getaddrinfo("blocked-host.example.org", 80)

    def test_hostname_allowlist_allows_listed(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            allowed_network_hosts=["example.com"],
            allow_eval_exec=True,
        )
        with sandbox_scope(config=config, agent_name="test"):
            # Should not raise SandboxViolation (may raise socket errors though)
            try:
                socket.getaddrinfo("example.com", 80)
            except OSError:
                pass  # Network errors are fine, sandbox shouldn't block

    def test_empty_allowlist_allows_all_dns(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            allowed_network_hosts=[],
            allow_eval_exec=True,
        )
        with sandbox_scope(config=config, agent_name="test"):
            try:
                socket.getaddrinfo("any-host.example.com", 80)
            except OSError:
                pass  # Network errors fine, no sandbox violation

    def test_localhost_blocked(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            block_private_ips=True,
        )
        with sandbox_scope(config=config, agent_name="test"):
            with pytest.raises(SandboxViolation, match=r"private IP.*127\.0\.0\.1"):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    s.connect(("127.0.0.1", 65432))
                finally:
                    s.close()


# ---------------------------------------------------------------------------
# Subprocess hooks
# ---------------------------------------------------------------------------


class TestSubprocessHooks:
    def test_subprocess_blocked_by_default(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            allow_subprocess=False,
        )
        with sandbox_scope(config=config, agent_name="test"):
            with pytest.raises(SandboxViolation, match="Subprocess execution blocked"):
                subprocess.Popen(["echo", "test"])

    def test_subprocess_allowed_when_enabled(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            allow_subprocess=True,
        )
        with sandbox_scope(config=config, agent_name="test"):
            proc = subprocess.Popen(
                ["echo", "test"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _ = proc.communicate()
            assert b"test" in stdout


# ---------------------------------------------------------------------------
# Import hooks
# ---------------------------------------------------------------------------


class TestImportHooks:
    def test_check_import_blocks_threading_directly(self):
        """Unit test: _check_import correctly blocks threading module."""
        from initrunner.agent.sandbox import _check_import

        config = ToolSandboxConfig(audit_hooks_enabled=True)
        state = _get_state()
        state.enforcing = True
        state.config = config
        state.agent_name = "test"
        try:
            with pytest.raises(SandboxViolation, match=r"threading.*not allowed in sandbox"):
                _check_import(state, ("threading",))
        finally:
            state.enforcing = False

    def test_check_import_blocks_thread_module_directly(self):
        """Unit test: _check_import correctly blocks _thread module."""
        from initrunner.agent.sandbox import _check_import

        config = ToolSandboxConfig(audit_hooks_enabled=True)
        state = _get_state()
        state.enforcing = True
        state.config = config
        state.agent_name = "test"
        try:
            with pytest.raises(SandboxViolation, match=r"_thread.*not allowed in sandbox"):
                _check_import(state, ("_thread",))
        finally:
            state.enforcing = False

    def test_cached_import_does_not_fire_hook(self):
        """Demonstrates that __import__ on cached modules doesn't trigger the hook.

        This is the expected limitation: import hooks are defense-in-depth,
        operation-level hooks (open, socket, subprocess) are the primary defense.
        """
        config = ToolSandboxConfig(audit_hooks_enabled=True)
        # threading is already in sys.modules, so __import__ won't fire the hook
        with sandbox_scope(config=config, agent_name="test"):
            # Should NOT raise — module is cached
            __import__("threading")

    def test_blocked_module_caught_by_checker(self):
        """_check_import blocks modules in blocked_custom_modules."""
        from initrunner.agent.sandbox import _check_import

        config = ToolSandboxConfig(audit_hooks_enabled=True)
        state = _get_state()
        state.enforcing = True
        state.config = config
        state.agent_name = "test"
        try:
            with pytest.raises(SandboxViolation, match="Import of 'ctypes' blocked"):
                _check_import(state, ("ctypes",))
        finally:
            state.enforcing = False

    def test_allowed_module_passes(self):
        config = ToolSandboxConfig(audit_hooks_enabled=True)
        with sandbox_scope(config=config, agent_name="test"):
            # json is not in blocked list, should work
            __import__("json")


# ---------------------------------------------------------------------------
# Eval/exec hooks
# ---------------------------------------------------------------------------


class TestEvalExecHooks:
    def test_exec_blocked_by_default(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            allow_eval_exec=False,
        )
        with sandbox_scope(config=config, agent_name="test"):
            with pytest.raises(SandboxViolation, match=r"(exec|compile) blocked"):
                exec("x = 1")

    def test_compile_blocked_by_default(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            allow_eval_exec=False,
        )
        with sandbox_scope(config=config, agent_name="test"):
            with pytest.raises(SandboxViolation, match="compile blocked"):
                compile("x = 1", "<string>", "exec")

    def test_exec_allowed_when_enabled(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            allow_eval_exec=True,
        )
        with sandbox_scope(config=config, agent_name="test"):
            ns: dict = {}
            exec("x = 42", ns)
            assert ns["x"] == 42


# ---------------------------------------------------------------------------
# Violation action modes
# ---------------------------------------------------------------------------


class TestViolationAction:
    def test_raise_mode_raises(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            sandbox_violation_action="raise",
            allow_subprocess=False,
        )
        with sandbox_scope(config=config, agent_name="test"):
            with pytest.raises(SandboxViolation):
                subprocess.Popen(["echo", "test"])

    def test_log_mode_does_not_raise(self):
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            sandbox_violation_action="log",
            allow_subprocess=False,
        )
        state = _get_state()
        with sandbox_scope(config=config, agent_name="test"):
            try:
                subprocess.Popen(["echo", "test"])
            except OSError:
                pass  # Actual OS errors are fine, just no SandboxViolation
            # Violations should have been recorded
            assert len(state.violations) > 0
            assert any("Subprocess" in v["detail"] for v in state.violations)


# ---------------------------------------------------------------------------
# Threading escape prevention
# ---------------------------------------------------------------------------


class TestThreadingEscape:
    def test_threading_import_checker_blocks(self):
        """The import checker correctly blocks threading even if the audit event
        doesn't fire for cached modules. This tests the checker function directly."""
        from initrunner.agent.sandbox import _check_import

        config = ToolSandboxConfig(audit_hooks_enabled=True)
        state = _get_state()
        state.enforcing = True
        state.config = config
        state.agent_name = "test"
        try:
            with pytest.raises(SandboxViolation, match="threading"):
                _check_import(state, ("threading",))
        finally:
            state.enforcing = False

    def test_threading_in_blocked_modules_default(self):
        """Verify threading and _thread are in the default blocked modules list."""
        config = ToolSandboxConfig()
        assert "threading" in config.blocked_custom_modules
        assert "_thread" in config.blocked_custom_modules

    def test_operation_hooks_catch_thread_operations(self):
        """Even if a thread is somehow spawned, operation-level hooks (subprocess,
        network, filesystem writes) still catch violations within the sandbox scope."""
        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            allow_subprocess=False,
        )
        with sandbox_scope(config=config, agent_name="test"):
            with pytest.raises(SandboxViolation, match="Subprocess execution blocked"):
                subprocess.Popen(["echo", "test"])


# ---------------------------------------------------------------------------
# Audit trail integration
# ---------------------------------------------------------------------------


class TestAuditIntegration:
    def test_violations_logged_to_audit(self, tmp_path):
        from initrunner.audit.logger import AuditLogger

        db_path = tmp_path / "test_audit.db"
        audit_logger = AuditLogger(db_path=db_path)

        set_audit_logger(audit_logger)

        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            sandbox_violation_action="log",
            allow_subprocess=False,
        )

        try:
            with sandbox_scope(config=config, agent_name="test-agent"):
                try:
                    subprocess.Popen(["echo", "test"])
                except OSError:
                    pass

            # Violations should have been logged to the security_events table
            events = audit_logger.query_security_events(
                event_type="sandbox_violation",
                agent_name="test-agent",
            )
            assert len(events) > 0
            assert any("Subprocess" in e["details"] for e in events)
        finally:
            set_audit_logger(None)
            audit_logger.close()

    def test_violations_logged_on_raise_too(self, tmp_path):
        from initrunner.audit.logger import AuditLogger

        db_path = tmp_path / "test_audit2.db"
        audit_logger = AuditLogger(db_path=db_path)

        set_audit_logger(audit_logger)

        config = ToolSandboxConfig(
            audit_hooks_enabled=True,
            sandbox_violation_action="raise",
            allow_subprocess=False,
        )

        try:
            with pytest.raises(SandboxViolation):
                with sandbox_scope(config=config, agent_name="test-agent"):
                    subprocess.Popen(["echo", "test"])

            # Even in raise mode, violations should be logged on scope exit
            events = audit_logger.query_security_events(
                event_type="sandbox_violation",
                agent_name="test-agent",
            )
            assert len(events) > 0
        finally:
            set_audit_logger(None)
            audit_logger.close()
