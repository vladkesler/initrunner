"""Tests for the SSH sandbox backend.

SSH is remote execution, not isolation. Tests cover (1) the schema rejecting
config that wouldn't make sense over SSH, (2) the backend building correct
SSH command lines, and (3) the auth env (SSH_AUTH_SOCK) flowing through to
the local SSH process while being stripped from the remote command env.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent._subprocess import SubprocessTimeout
from initrunner.agent.runtime_sandbox.base import (
    SandboxConfigError,
    SandboxUnavailableError,
)
from initrunner.agent.runtime_sandbox.ssh import (
    SSHBackend,
    _build_remote_command,
    _scrub_caller_env,
)
from initrunner.agent.schema.security import (
    BindMount,
    SandboxConfig,
    SSHBackendConfig,
)

# ---------------------------------------------------------------------------
# Schema tests: defaults are accepted, only explicit divergence is rejected
# ---------------------------------------------------------------------------


class TestSSHSchemaAccepts:
    def test_naive_ssh_config_accepts_defaults(self):
        """A minimal `backend: ssh` config must validate.

        ``read_only_rootfs=True`` and ``network='none'`` are the SandboxConfig
        defaults; if either tripped validation, every quickstart would fail.
        """
        config = SandboxConfig(backend="ssh", ssh=SSHBackendConfig(host="my-box"))
        assert config.backend == "ssh"
        assert config.ssh is not None
        assert config.ssh.host == "my-box"
        # Defaults preserved, schema didn't reject them
        assert config.read_only_rootfs is True
        assert config.network == "none"

    def test_network_host_accepted_under_ssh(self):
        config = SandboxConfig(backend="ssh", network="host", ssh=SSHBackendConfig(host="my-box"))
        assert config.network == "host"


class TestSSHSchemaRejects:
    def test_ssh_backend_without_ssh_config_rejected(self):
        with pytest.raises(ValueError, match=r"sandbox\.ssh is unset"):
            SandboxConfig(backend="ssh")

    def test_empty_host_rejected(self):
        with pytest.raises(ValueError):
            SSHBackendConfig(host="")

    def test_bind_mounts_rejected_under_ssh(self):
        with pytest.raises(ValueError, match=r"bind_mounts is not supported"):
            SandboxConfig(
                backend="ssh",
                ssh=SSHBackendConfig(host="my-box"),
                bind_mounts=[BindMount(source="./a", target="/a")],
            )

    def test_allowed_read_paths_rejected_under_ssh(self):
        with pytest.raises(ValueError, match=r"allowed_read_paths is not supported"):
            SandboxConfig(
                backend="ssh",
                ssh=SSHBackendConfig(host="my-box"),
                allowed_read_paths=["/srv"],
            )

    def test_allowed_write_paths_rejected_under_ssh(self):
        with pytest.raises(ValueError, match=r"allowed_write_paths is not supported"):
            SandboxConfig(
                backend="ssh",
                ssh=SSHBackendConfig(host="my-box"),
                allowed_write_paths=["/srv"],
            )

    def test_network_bridge_rejected_under_ssh(self):
        with pytest.raises(ValueError, match=r"network: bridge is not meaningful"):
            SandboxConfig(backend="ssh", network="bridge", ssh=SSHBackendConfig(host="my-box"))


# ---------------------------------------------------------------------------
# Remote command construction
# ---------------------------------------------------------------------------


class TestBuildRemoteCommand:
    def test_basic_argv(self):
        cmd = _build_remote_command(argv=["ls", "-la"], env={}, remote_cwd=None)
        assert cmd == "ls -la"

    def test_argv_quoted(self):
        cmd = _build_remote_command(argv=["echo", "hello world", "$HOME"], env={}, remote_cwd=None)
        assert cmd == "echo 'hello world' '$HOME'"

    def test_remote_cwd_prefix(self):
        cmd = _build_remote_command(argv=["ls"], env={}, remote_cwd="/srv/work")
        assert cmd == "cd /srv/work && ls"

    def test_remote_cwd_with_spaces_quoted(self):
        cmd = _build_remote_command(argv=["ls"], env={}, remote_cwd="/srv/my work")
        assert cmd == "cd '/srv/my work' && ls"

    def test_no_remote_cwd_no_cd(self):
        """Without remote_cwd, the remote command must not contain `cd`.

        That keeps the SSH login directory in effect, which is what most
        users want when they haven't picked one explicitly.
        """
        cmd = _build_remote_command(argv=["pwd"], env={}, remote_cwd=None)
        assert "cd " not in cmd

    def test_env_injected(self):
        cmd = _build_remote_command(argv=["printenv", "FOO"], env={"FOO": "bar"}, remote_cwd=None)
        assert cmd == "env FOO=bar printenv FOO"

    def test_env_value_with_spaces_quoted(self):
        cmd = _build_remote_command(
            argv=["printenv", "MSG"], env={"MSG": "hello world"}, remote_cwd=None
        )
        assert cmd == "env MSG='hello world' printenv MSG"

    def test_sensitive_env_keys_scrubbed(self):
        """Caller-provided env must be scrubbed before reaching the remote shell.

        The same prefix/suffix list used by other backends applies; the local
        SSH process env is handled separately.
        """
        cmd = _build_remote_command(
            argv=["env"],
            env={
                "OPENAI_API_KEY": "sk-secret",
                "MY_TOKEN": "xyz",
                "SAFE_VAR": "ok",
            },
            remote_cwd=None,
        )
        assert "OPENAI_API_KEY" not in cmd
        assert "MY_TOKEN" not in cmd
        assert "sk-secret" not in cmd
        assert "SAFE_VAR=ok" in cmd

    def test_full_form_cwd_env_argv(self):
        cmd = _build_remote_command(
            argv=["python", "-c", "print(1)"],
            env={"PYTHONPATH": "/opt/lib"},
            remote_cwd="/srv",
        )
        assert cmd == "cd /srv && env PYTHONPATH=/opt/lib python -c 'print(1)'"


class TestScrubCallerEnv:
    def test_strips_known_prefixes(self):
        result = _scrub_caller_env({"AWS_SECRET_KEY": "x", "PATH": "/usr/bin"})
        assert "AWS_SECRET_KEY" not in result
        assert result["PATH"] == "/usr/bin"

    def test_strips_suffix_matches(self):
        result = _scrub_caller_env({"MY_TOKEN": "x", "FOO": "y"})
        assert "MY_TOKEN" not in result
        assert result["FOO"] == "y"

    def test_keeps_allowlist(self):
        # SSH_AGENT_PID is in DEFAULT_ENV_ALLOWLIST and ends in _PID (not on the
        # suffix list) so it would survive anyway, but cover the codepath.
        result = _scrub_caller_env({"SSH_AGENT_PID": "1234"})
        assert result["SSH_AGENT_PID"] == "1234"

    def test_empty_env_passthrough(self):
        assert _scrub_caller_env({}) == {}


# ---------------------------------------------------------------------------
# Backend command-line construction (mocked subprocess)
# ---------------------------------------------------------------------------


def _make_backend(**ssh_kwargs) -> SSHBackend:
    ssh_kwargs.setdefault("host", "test-host")
    config = SandboxConfig(backend="ssh", ssh=SSHBackendConfig(**ssh_kwargs))
    return SSHBackend(config)


class TestSSHCommandLine:
    def test_double_dash_precedes_host(self):
        """The `--` separator goes BEFORE the host, not after.

        `ssh host -- cmd` puts `--` in the remote command (visible as a
        spurious arg). Correct form: `ssh -- host cmd`.
        """
        backend = _make_backend(host="my-box")
        try:
            with patch("initrunner.agent.runtime_sandbox.ssh.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=b"", stderr=b"", returncode=0)
                backend.run(
                    ["echo", "hi"],
                    env={},
                    cwd=Path("/tmp"),
                    timeout=5,
                )
                argv = mock_run.call_args[0][0]
                dash_idx = argv.index("--")
                host_idx = argv.index("my-box")
                assert dash_idx < host_idx, f"`--` must precede host: {argv}"
        finally:
            backend.close()

    def test_control_master_options_present(self):
        backend = _make_backend(host="h")
        try:
            with patch("initrunner.agent.runtime_sandbox.ssh.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=b"", stderr=b"", returncode=0)
                backend.run(["true"], env={}, cwd=Path("/tmp"), timeout=5)
                argv = mock_run.call_args[0][0]
                assert "ControlMaster=auto" in argv
                assert any(a.startswith("ControlPath=") for a in argv)
                assert any(a.startswith("ControlPersist=") for a in argv)
                assert "BatchMode=yes" in argv
        finally:
            backend.close()

    def test_identity_file_threaded(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("")
        backend = _make_backend(host="h", identity_file=str(key))
        try:
            with patch("initrunner.agent.runtime_sandbox.ssh.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=b"", stderr=b"", returncode=0)
                backend.run(["true"], env={}, cwd=Path("/tmp"), timeout=5)
                argv = mock_run.call_args[0][0]
                i_idx = argv.index("-i")
                assert argv[i_idx + 1] == str(key)
        finally:
            backend.close()

    def test_config_file_threaded(self, tmp_path):
        cfg = tmp_path / "ssh_config"
        cfg.write_text("")
        backend = _make_backend(host="h", config_file=str(cfg))
        try:
            with patch("initrunner.agent.runtime_sandbox.ssh.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=b"", stderr=b"", returncode=0)
                backend.run(["true"], env={}, cwd=Path("/tmp"), timeout=5)
                argv = mock_run.call_args[0][0]
                f_idx = argv.index("-F")
                assert argv[f_idx + 1] == str(cfg)
        finally:
            backend.close()

    def test_remote_cwd_set_emits_cd_prefix(self):
        backend = _make_backend(host="h", remote_cwd="/srv/work")
        try:
            with patch("initrunner.agent.runtime_sandbox.ssh.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=b"", stderr=b"", returncode=0)
                backend.run(["ls"], env={}, cwd=Path("/tmp"), timeout=5)
                remote_cmd = mock_run.call_args[0][0][-1]
                assert remote_cmd.startswith("cd /srv/work && ")
        finally:
            backend.close()

    def test_remote_cwd_unset_no_cd(self):
        backend = _make_backend(host="h")
        try:
            with patch("initrunner.agent.runtime_sandbox.ssh.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=b"", stderr=b"", returncode=0)
                backend.run(["ls"], env={}, cwd=Path("/tmp"), timeout=5)
                remote_cmd = mock_run.call_args[0][0][-1]
                # The local cwd Path("/tmp") must NOT leak into the remote
                # command -- SSH ignores the Protocol's cwd arg.
                assert "/tmp" not in remote_cmd
                assert not remote_cmd.startswith("cd ")
        finally:
            backend.close()

    def test_local_env_preserves_ssh_auth_sock(self, monkeypatch):
        """The local SSH process env must keep SSH_AUTH_SOCK.

        scrub_env() strips it (it's in DEFAULT_SENSITIVE_ENV_PREFIXES); using
        scrub_env on the local env would silently break ssh-agent auth.
        """
        monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
        backend = _make_backend(host="h")
        try:
            with patch("initrunner.agent.runtime_sandbox.ssh.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=b"", stderr=b"", returncode=0)
                backend.run(["true"], env={}, cwd=Path("/tmp"), timeout=5)
                local_env = mock_run.call_args.kwargs["env"]
                assert local_env.get("SSH_AUTH_SOCK") == "/tmp/agent.sock"
        finally:
            backend.close()

    def test_remote_env_scrubs_secrets(self):
        backend = _make_backend(host="h")
        try:
            with patch("initrunner.agent.runtime_sandbox.ssh.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=b"", stderr=b"", returncode=0)
                backend.run(
                    ["env"],
                    env={"OPENAI_API_KEY": "sk-leak", "OK_VAR": "ok"},
                    cwd=Path("/tmp"),
                    timeout=5,
                )
                remote_cmd = mock_run.call_args[0][0][-1]
                assert "OPENAI_API_KEY" not in remote_cmd
                assert "sk-leak" not in remote_cmd
                assert "OK_VAR=ok" in remote_cmd
        finally:
            backend.close()


class TestSSHBackendBehavior:
    def test_extra_mounts_rejected(self):
        backend = _make_backend(host="h")
        try:
            with pytest.raises(SandboxConfigError, match="extra_mounts is not supported"):
                backend.run(
                    ["python", "/work/_run.py"],
                    env={},
                    cwd=Path("/tmp"),
                    timeout=5,
                    extra_mounts=[BindMount(source="/tmp/x.py", target="/work/_run.py")],
                )
        finally:
            backend.close()

    def test_timeout_raises_subprocess_timeout(self):
        backend = _make_backend(host="h")
        try:
            with patch(
                "initrunner.agent.runtime_sandbox.ssh.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=1),
            ):
                with pytest.raises(SubprocessTimeout):
                    backend.run(["sleep", "10"], env={}, cwd=Path("/tmp"), timeout=1)
        finally:
            backend.close()

    def test_returncode_and_streams_passthrough(self):
        backend = _make_backend(host="h")
        try:
            with patch("initrunner.agent.runtime_sandbox.ssh.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=b"hello\n", stderr=b"warn\n", returncode=2)
                result = backend.run(["echo", "hi"], env={}, cwd=Path("/tmp"), timeout=5)
                assert result.stdout == "hello\n"
                assert result.stderr == "warn\n"
                assert result.returncode == 2
                assert result.duration_ms >= 0
        finally:
            backend.close()


class TestSSHPreflight:
    def test_preflight_success(self):
        backend = _make_backend(host="h")
        try:
            with patch("initrunner.agent.runtime_sandbox.ssh.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=b"", stderr=b"", returncode=0)
                backend.preflight()  # should not raise
        finally:
            backend.close()

    def test_preflight_nonzero_raises_with_host_in_message(self):
        backend = _make_backend(host="missing-host")
        try:
            with patch("initrunner.agent.runtime_sandbox.ssh.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    stdout=b"", stderr=b"connection refused", returncode=255
                )
                with pytest.raises(SandboxUnavailableError) as exc_info:
                    backend.preflight()
                assert "missing-host" in str(exc_info.value)
        finally:
            backend.close()

    def test_preflight_ssh_binary_missing(self):
        backend = _make_backend(host="h")
        try:
            with patch(
                "initrunner.agent.runtime_sandbox.ssh.subprocess.run",
                side_effect=FileNotFoundError(),
            ):
                with pytest.raises(SandboxUnavailableError, match="ssh client not found"):
                    backend.preflight()
        finally:
            backend.close()


# ---------------------------------------------------------------------------
# Integration: localhost SSH (skipped unless an sshd accepts BatchMode auth)
# ---------------------------------------------------------------------------


def _localhost_ssh_works() -> bool:
    """True if `ssh -o BatchMode=yes localhost true` succeeds."""
    if shutil.which("ssh") is None:
        return False
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", "localhost", "true"],
            capture_output=True,
            timeout=10,
            env=os.environ.copy(),
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


@pytest.mark.skipif(
    not _localhost_ssh_works(),
    reason="localhost SSH not configured (need sshd + key auth)",
)
class TestSSHLocalhostIntegration:
    def test_run_echo(self):
        backend = _make_backend(host="localhost")
        try:
            backend.preflight()
            result = backend.run(["echo", "hello-from-ssh"], env={}, cwd=Path("/tmp"), timeout=15)
            assert result.returncode == 0
            assert "hello-from-ssh" in result.stdout
        finally:
            backend.close()
