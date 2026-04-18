"""Tests for the Docker sandbox backend and its building blocks."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent._subprocess import SubprocessTimeout
from initrunner.agent.schema.security import (
    _DOCKER_BLOCKED_ARGS,
    BindMount,
    DockerBackendConfig,
    SandboxConfig,
    SecurityPolicy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(role_dir=None, backend="none", network="none"):
    """Build a minimal ToolBuildContext with configurable sandbox settings."""
    from initrunner.agent.runtime_sandbox import resolve_backend
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.agent.tools._registry import ToolBuildContext

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
                "security": {
                    "sandbox": {
                        "backend": backend,
                        "network": network,
                    }
                },
            },
        }
    )
    sandbox_backend = resolve_backend(role.spec.security.sandbox, role_dir=role_dir)
    return ToolBuildContext(role=role, role_dir=role_dir, sandbox_backend=sandbox_backend)


# ===========================================================================
# Schema tests
# ===========================================================================


class TestSandboxConfigDefaults:
    def test_defaults(self):
        config = SandboxConfig()
        assert config.backend == "none"
        assert config.network == "none"
        assert config.memory_limit == "256m"
        assert config.cpu_limit == 1.0
        assert config.read_only_rootfs is True
        assert config.bind_mounts == []
        assert config.env_passthrough == []
        assert config.allowed_read_paths == []
        assert config.allowed_write_paths == []

    def test_docker_backend_defaults(self):
        config = DockerBackendConfig()
        assert config.image == "python:3.12-slim"
        assert config.user == "auto"
        assert config.extra_args == []

    def test_security_policy_has_sandbox_field(self):
        policy = SecurityPolicy()
        assert hasattr(policy, "sandbox")
        assert isinstance(policy.sandbox, SandboxConfig)
        assert policy.sandbox.backend == "none"

    def test_legacy_docker_key_rejected(self):
        with pytest.raises(ValueError, match=r"security\.docker has been replaced"):
            SecurityPolicy.model_validate({"docker": {"enabled": True}})


class TestBindMount:
    def test_valid_mount(self):
        m = BindMount(source="./data", target="/data")
        assert m.source == "./data"
        assert m.target == "/data"
        assert m.read_only is True

    def test_target_must_be_absolute(self):
        with pytest.raises(ValueError, match="absolute"):
            BindMount(source="./data", target="data")

    def test_read_only_default_true(self):
        m = BindMount(source="./x", target="/x")
        assert m.read_only is True

    def test_read_only_false(self):
        m = BindMount(source="./x", target="/x", read_only=False)
        assert m.read_only is False


class TestSandboxConfigValidation:
    def test_invalid_memory_limit(self):
        with pytest.raises(ValueError, match="Invalid memory_limit"):
            SandboxConfig(memory_limit="abc")

    def test_valid_memory_formats(self):
        for mem in ("256m", "1g", "512M", "2G", "1024k", "100b", "256"):
            config = SandboxConfig(memory_limit=mem)
            assert config.memory_limit == mem

    def test_cpu_limit_must_be_positive(self):
        with pytest.raises(ValueError):
            SandboxConfig(cpu_limit=0)

    def test_cpu_limit_negative_rejected(self):
        with pytest.raises(ValueError):
            SandboxConfig(cpu_limit=-1.0)

    def test_dangerous_extra_args_rejected(self):
        for arg in _DOCKER_BLOCKED_ARGS:
            with pytest.raises(ValueError, match="blocked for security"):
                DockerBackendConfig(extra_args=[arg])

    def test_dangerous_extra_args_with_value_rejected(self):
        with pytest.raises(ValueError, match="blocked for security"):
            DockerBackendConfig(extra_args=["--cap-add=ALL"])

    def test_safe_extra_args_allowed(self):
        config = DockerBackendConfig(extra_args=["--pids-limit=100", "--ulimit=nofile=1024"])
        assert len(config.extra_args) == 2

    def test_empty_image_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            DockerBackendConfig(image="  ")

    def test_duplicate_bind_mount_targets_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            SandboxConfig(
                bind_mounts=[
                    BindMount(source="./a", target="/data"),
                    BindMount(source="./b", target="/data"),
                ]
            )

    def test_work_target_conflicts(self):
        with pytest.raises(ValueError, match="/work"):
            SandboxConfig(bind_mounts=[BindMount(source="./project", target="/work")])

    def test_valid_bind_mounts(self):
        config = SandboxConfig(
            bind_mounts=[
                BindMount(source="./a", target="/a"),
                BindMount(source="./b", target="/b", read_only=False),
            ]
        )
        assert len(config.bind_mounts) == 2


# ===========================================================================
# Availability tests
# ===========================================================================


class TestDockerAvailability:
    def test_available_when_docker_found_and_running(self):
        from initrunner.agent.docker_sandbox import check_docker_available

        with patch("initrunner.agent.docker_sandbox.shutil.which", return_value="/usr/bin/docker"):
            with patch("initrunner.agent.docker_sandbox.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                assert check_docker_available() is True

    def test_not_available_when_binary_missing(self):
        from initrunner.agent.docker_sandbox import check_docker_available

        with patch("initrunner.agent.docker_sandbox.shutil.which", return_value=None):
            assert check_docker_available() is False

    def test_not_available_when_daemon_not_running(self):
        from initrunner.agent.docker_sandbox import check_docker_available

        with patch("initrunner.agent.docker_sandbox.shutil.which", return_value="/usr/bin/docker"):
            with patch("initrunner.agent.docker_sandbox.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1)
                assert check_docker_available() is False

    def test_not_available_when_timeout(self):
        from initrunner.agent.docker_sandbox import check_docker_available

        with patch("initrunner.agent.docker_sandbox.shutil.which", return_value="/usr/bin/docker"):
            with patch(
                "initrunner.agent.docker_sandbox.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="docker info", timeout=5),
            ):
                assert check_docker_available() is False

    def test_require_docker_raises_when_unavailable(self):
        from initrunner.agent.docker_sandbox import (
            DockerNotAvailableError,
            require_docker,
        )

        with patch("initrunner.agent.docker_sandbox.check_docker_available", return_value=False):
            with pytest.raises(DockerNotAvailableError):
                require_docker()

    def test_require_docker_passes_when_available(self):
        from initrunner.agent.docker_sandbox import require_docker

        with patch("initrunner.agent.docker_sandbox.check_docker_available", return_value=True):
            require_docker()  # Should not raise


# ===========================================================================
# Command building tests
# ===========================================================================


class TestBuildDockerCmd:
    def test_basic_command(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker")
        cmd = _build_docker_cmd(config)
        assert cmd[:3] == ["docker", "run", "--rm"]
        assert "--network" in cmd
        assert "none" in cmd
        assert "-m" in cmd
        assert "256m" in cmd
        assert "--cpus" in cmd
        assert "python:3.12-slim" in cmd

    def test_read_only_rootfs(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker", read_only_rootfs=True)
        cmd = _build_docker_cmd(config)
        assert "--read-only" in cmd
        assert "--tmpfs" in cmd
        tmpfs_idx = cmd.index("--tmpfs")
        assert "/tmp:" in cmd[tmpfs_idx + 1]

    def test_no_read_only_rootfs(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker", read_only_rootfs=False)
        cmd = _build_docker_cmd(config)
        assert "--read-only" not in cmd

    def test_bind_mounts_resolved(self, tmp_path):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        (tmp_path / "data").mkdir()
        config = SandboxConfig(
            backend="docker",
            bind_mounts=[BindMount(source="./data", target="/data", read_only=True)],
        )
        cmd = _build_docker_cmd(config, role_dir=tmp_path)
        v_indices = [i for i, x in enumerate(cmd) if x == "-v"]
        assert len(v_indices) >= 1
        mount_arg = cmd[v_indices[0] + 1]
        assert ":/data:ro" in mount_arg
        assert str(tmp_path) in mount_arg

    def test_relative_mount_source_resolves_against_role_dir(self, tmp_path):
        from initrunner.agent.docker_sandbox import _resolve_mount_source

        resolved = _resolve_mount_source("./subdir", tmp_path)
        assert resolved == str((tmp_path / "subdir").resolve())

    def test_absolute_mount_source_unchanged(self):
        from initrunner.agent.docker_sandbox import _resolve_mount_source

        resolved = _resolve_mount_source("/absolute/path", Path("/some/role"))
        assert resolved == "/absolute/path"

    def test_working_dir_mount(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker")
        cmd = _build_docker_cmd(config, work_dir="/my/work")
        v_indices = [i for i, x in enumerate(cmd) if x == "-v"]
        work_mounts = [cmd[i + 1] for i in v_indices if "/my/work:/work" in cmd[i + 1]]
        assert len(work_mounts) == 1
        assert "-w" in cmd
        w_idx = cmd.index("-w")
        assert cmd[w_idx + 1] == "/work"

    def test_env_passthrough(self, monkeypatch):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        monkeypatch.setenv("LANG", "en_US.UTF-8")
        monkeypatch.setenv("TZ", "UTC")
        config = SandboxConfig(backend="docker", env_passthrough=["LANG", "TZ"])
        cmd = _build_docker_cmd(config)
        e_indices = [i for i, x in enumerate(cmd) if x == "-e"]
        env_args = [cmd[i + 1] for i in e_indices]
        assert "LANG=en_US.UTF-8" in env_args
        assert "TZ=UTC" in env_args

    def test_env_passthrough_skips_missing(self, monkeypatch):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        monkeypatch.delenv("NONEXISTENT_VAR_XYZ", raising=False)
        config = SandboxConfig(backend="docker", env_passthrough=["NONEXISTENT_VAR_XYZ"])
        cmd = _build_docker_cmd(config)
        e_indices = [i for i, x in enumerate(cmd) if x == "-e"]
        env_args = [cmd[i + 1] for i in e_indices]
        assert not any("NONEXISTENT_VAR_XYZ" in a for a in env_args)

    def test_extra_args_appended(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(
            backend="docker", docker=DockerBackendConfig(extra_args=["--pids-limit=100"])
        )
        cmd = _build_docker_cmd(config)
        assert "--pids-limit=100" in cmd
        img_idx = cmd.index("python:3.12-slim")
        pids_idx = cmd.index("--pids-limit=100")
        assert pids_idx < img_idx

    def test_interactive_flag(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker")
        cmd = _build_docker_cmd(config, interactive=True)
        assert "-i" in cmd

    def test_no_interactive_by_default(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker")
        cmd = _build_docker_cmd(config, interactive=False)
        assert "-i" not in cmd

    def test_pids_limit_default(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker")
        cmd = _build_docker_cmd(config)
        pids_idx = cmd.index("--pids-limit")
        assert cmd[pids_idx + 1] == "256"

    def test_env_dict_passed(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker")
        cmd = _build_docker_cmd(config, env={"MY_VAR": "hello"})
        e_indices = [i for i, x in enumerate(cmd) if x == "-e"]
        env_args = [cmd[i + 1] for i in e_indices]
        assert "MY_VAR=hello" in env_args

    def test_rw_mount(self, tmp_path):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        (tmp_path / "data").mkdir()
        config = SandboxConfig(
            backend="docker",
            bind_mounts=[BindMount(source="./data", target="/data", read_only=False)],
        )
        cmd = _build_docker_cmd(config, role_dir=tmp_path)
        v_indices = [i for i, x in enumerate(cmd) if x == "-v"]
        mount_arg = cmd[v_indices[0] + 1]
        assert ":/data" in mount_arg
        assert ":ro" not in mount_arg


# ===========================================================================
# DockerBackend tests
# ===========================================================================


class TestDockerBackend:
    def test_run_builds_and_executes(self, tmp_path):
        from initrunner.agent.runtime_sandbox.docker import DockerBackend

        config = SandboxConfig(backend="docker")
        backend = DockerBackend(config)
        mock_result = MagicMock(stdout=b"hello\n", stderr=b"", returncode=0)
        with patch(
            "initrunner.agent.runtime_sandbox.docker.subprocess.run", return_value=mock_result
        ) as mock_run:
            result = backend.run(["echo", "hello"], env={}, cwd=tmp_path, timeout=30)
            assert result.stdout == "hello\n"
            assert result.stderr == ""
            assert result.returncode == 0
            cmd = mock_run.call_args[0][0]
            assert cmd[:3] == ["docker", "run", "--rm"]
            assert cmd[-2:] == ["echo", "hello"]

    def test_run_timeout_raises_and_kills_container(self, tmp_path):
        from initrunner.agent.runtime_sandbox.docker import DockerBackend

        config = SandboxConfig(backend="docker")
        backend = DockerBackend(config)
        with patch(
            "initrunner.agent.runtime_sandbox.docker.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=5),
        ):
            with patch("initrunner.agent.runtime_sandbox.docker._kill_container") as mock_kill:
                with pytest.raises(SubprocessTimeout):
                    backend.run(["sleep", "100"], env={}, cwd=tmp_path, timeout=5)
                mock_kill.assert_called_once()
                name = mock_kill.call_args[0][0]
                assert name.startswith("initrunner-")

    def test_run_with_stdin(self, tmp_path):
        from initrunner.agent.runtime_sandbox.docker import DockerBackend

        config = SandboxConfig(backend="docker")
        backend = DockerBackend(config)
        mock_result = MagicMock(stdout=b"hi\n", stderr=b"", returncode=0)
        with patch(
            "initrunner.agent.runtime_sandbox.docker.subprocess.run", return_value=mock_result
        ) as mock_run:
            backend.run(["/bin/sh"], stdin=b"echo hi", env={}, cwd=tmp_path, timeout=30)
            cmd = mock_run.call_args[0][0]
            assert "-i" in cmd
            assert mock_run.call_args[1]["input"] == b"echo hi"

    def test_run_with_extra_mounts(self, tmp_path):
        from initrunner.agent.runtime_sandbox.docker import DockerBackend

        config = SandboxConfig(backend="docker")
        backend = DockerBackend(config)
        mock_result = MagicMock(stdout=b"ok\n", stderr=b"", returncode=0)
        code_file = tmp_path / "_run.py"
        code_file.write_text("print('ok')")
        with patch(
            "initrunner.agent.runtime_sandbox.docker.subprocess.run", return_value=mock_result
        ) as mock_run:
            backend.run(
                ["python", "/work/_run.py"],
                env={},
                cwd=tmp_path,
                timeout=30,
                extra_mounts=[
                    BindMount(source=str(code_file), target="/work/_run.py", read_only=True)
                ],
            )
            cmd = mock_run.call_args[0][0]
            v_indices = [i for i, x in enumerate(cmd) if x == "-v"]
            mount_args = [cmd[i + 1] for i in v_indices]
            assert any(f"{code_file}:/work/_run.py:ro" in m for m in mount_args)


# ===========================================================================
# Tool builder integration tests
# ===========================================================================


class TestShellToolDockerIntegration:
    def test_uses_docker_when_enabled(self):
        from initrunner.agent.schema.tools import ShellToolConfig
        from initrunner.agent.tools.shell import build_shell_toolset

        ctx = _make_ctx(backend="docker")
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, ctx)
        fn = toolset.tools["run_shell"].function

        with patch("initrunner.agent.runtime_sandbox.docker.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=b"hello\n", stderr=b"", returncode=0)
            output = fn(command="echo hello")
            assert "hello" in output
            cmd = mock_run.call_args[0][0]
            assert cmd[:3] == ["docker", "run", "--rm"]

    def test_uses_null_backend_when_disabled(self):
        from initrunner.agent.schema.tools import ShellToolConfig
        from initrunner.agent.tools.shell import build_shell_toolset

        ctx = _make_ctx(backend="none")
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, ctx)
        fn = toolset.tools["run_shell"].function

        output = fn(command="echo hello")
        assert "hello" in output


class TestPythonToolDockerIntegration:
    def test_uses_docker_when_enabled(self):
        from initrunner.agent.schema.tools import PythonToolConfig
        from initrunner.agent.tools.python_exec import build_python_toolset

        ctx = _make_ctx(backend="docker")
        config = PythonToolConfig(require_confirmation=False)
        toolset = build_python_toolset(config, ctx)
        fn = toolset.tools["run_python"].function

        with patch("initrunner.agent.runtime_sandbox.docker.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=b"42\n", stderr=b"", returncode=0)
            output = fn(code="print(42)")
            assert "42" in output
            cmd = mock_run.call_args[0][0]
            assert cmd[:3] == ["docker", "run", "--rm"]

    def test_uses_null_backend_when_disabled(self):
        from initrunner.agent.schema.tools import PythonToolConfig
        from initrunner.agent.tools.python_exec import build_python_toolset

        ctx = _make_ctx(backend="none")
        config = PythonToolConfig(require_confirmation=False)
        toolset = build_python_toolset(config, ctx)
        fn = toolset.tools["run_python"].function

        output = fn(code='print("hello")')
        assert "hello" in output


class TestScriptToolDockerIntegration:
    def test_uses_docker_when_enabled(self):
        from initrunner.agent.schema.tools import ScriptDefinition, ScriptToolConfig
        from initrunner.agent.tools.script import build_script_toolset

        ctx = _make_ctx(backend="docker")
        config = ScriptToolConfig(scripts=[ScriptDefinition(name="hello", body="echo hello")])
        toolset = build_script_toolset(config, ctx)
        fn = toolset.tools["hello"].function

        with patch("initrunner.agent.runtime_sandbox.docker.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=b"hello\n", stderr=b"", returncode=0)
            output = fn()
            assert "hello" in output
            cmd = mock_run.call_args[0][0]
            assert cmd[:3] == ["docker", "run", "--rm"]
            assert "-i" in cmd

    def test_uses_null_backend_when_disabled(self):
        from initrunner.agent.schema.tools import ScriptDefinition, ScriptToolConfig
        from initrunner.agent.tools.script import build_script_toolset

        ctx = _make_ctx(backend="none")
        config = ScriptToolConfig(scripts=[ScriptDefinition(name="hello", body="echo hello")])
        toolset = build_script_toolset(config, ctx)
        fn = toolset.tools["hello"].function

        output = fn()
        assert "hello" in output


# ===========================================================================
# Registry startup validation
# ===========================================================================


class TestRegistrySandboxPreflight:
    def test_build_toolsets_runs_preflight_for_docker_backend(self):
        from initrunner.agent.tools.registry import build_toolsets

        ctx = _make_ctx(backend="docker")
        with patch(
            "initrunner.agent.runtime_sandbox.docker.check_docker_available", return_value=True
        ):
            with patch(
                "initrunner.agent.runtime_sandbox.docker.ensure_image_available"
            ) as mock_ensure:
                build_toolsets([], ctx.role)

        mock_ensure.assert_called_once_with("python:3.12-slim")

    def test_build_toolsets_no_preflight_for_null_backend(self):
        from initrunner.agent.tools.registry import build_toolsets

        ctx = _make_ctx(backend="none")
        with patch("initrunner.agent.runtime_sandbox.docker.check_docker_available") as mock_check:
            build_toolsets([], ctx.role)

        mock_check.assert_not_called()


# ===========================================================================
# Container name, cleanup, init flag
# ===========================================================================


class TestContainerNameAndCleanup:
    def test_container_name_in_command(self, tmp_path):
        from initrunner.agent.runtime_sandbox.docker import DockerBackend

        config = SandboxConfig(backend="docker")
        backend = DockerBackend(config)
        mock_result = MagicMock(stdout=b"ok\n", stderr=b"", returncode=0)
        with patch(
            "initrunner.agent.runtime_sandbox.docker.subprocess.run", return_value=mock_result
        ) as mock_run:
            backend.run(["echo", "ok"], env={}, cwd=tmp_path, timeout=30)
            cmd = mock_run.call_args[0][0]
            assert "--name" in cmd
            name_idx = cmd.index("--name")
            assert cmd[name_idx + 1].startswith("initrunner-")

    def test_label_in_command(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker")
        cmd = _build_docker_cmd(config, container_name="test-123")
        assert "--label" in cmd
        label_idx = cmd.index("--label")
        assert cmd[label_idx + 1] == "initrunner.managed=true"


class TestInitFlag:
    def test_init_flag_present(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker")
        cmd = _build_docker_cmd(config)
        assert "--init" in cmd


# ===========================================================================
# OOM detection
# ===========================================================================


class TestOomDetection:
    def test_oom_hint_appended_on_137(self, tmp_path):
        from initrunner.agent.runtime_sandbox.docker import DockerBackend

        config = SandboxConfig(backend="docker", memory_limit="256m")
        backend = DockerBackend(config)
        mock_result = MagicMock(stdout=b"", stderr=b"Killed", returncode=137)
        with patch(
            "initrunner.agent.runtime_sandbox.docker.subprocess.run", return_value=mock_result
        ):
            result = backend.run(["python", "-c", "x=[]"], env={}, cwd=tmp_path, timeout=30)
            assert result.returncode == 137
            assert "OOM" in result.stderr
            assert "256m" in result.stderr

    def test_no_oom_hint_on_normal_exit(self, tmp_path):
        from initrunner.agent.runtime_sandbox.docker import DockerBackend

        config = SandboxConfig(backend="docker")
        backend = DockerBackend(config)
        mock_result = MagicMock(stdout=b"ok", stderr=b"", returncode=0)
        with patch(
            "initrunner.agent.runtime_sandbox.docker.subprocess.run", return_value=mock_result
        ):
            result = backend.run(["echo", "ok"], env={}, cwd=tmp_path, timeout=30)
            assert result.returncode == 0
            assert "OOM" not in result.stderr


# ===========================================================================
# Bind mount validation
# ===========================================================================


class TestBindMountValidation:
    def test_missing_source_raises(self, tmp_path):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(
            backend="docker",
            bind_mounts=[BindMount(source="./nonexistent", target="/data")],
        )
        with pytest.raises(ValueError, match="does not exist"):
            _build_docker_cmd(config, role_dir=tmp_path)

    def test_missing_rw_source_raises(self, tmp_path):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(
            backend="docker",
            bind_mounts=[BindMount(source="./nonexistent", target="/out", read_only=False)],
        )
        with pytest.raises(ValueError, match="does not exist"):
            _build_docker_cmd(config, role_dir=tmp_path)

    def test_existing_source_passes(self, tmp_path):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        (tmp_path / "mydata").mkdir()
        config = SandboxConfig(
            backend="docker",
            bind_mounts=[BindMount(source="./mydata", target="/mydata")],
        )
        cmd = _build_docker_cmd(config, role_dir=tmp_path)
        assert any(":/mydata:ro" in arg for arg in cmd)


# ===========================================================================
# Image availability
# ===========================================================================


class TestEnsureImageAvailable:
    def test_image_already_local(self):
        from initrunner.agent.docker_sandbox import ensure_image_available

        mock_result = MagicMock(returncode=0)
        with patch(
            "initrunner.agent.docker_sandbox.subprocess.run", return_value=mock_result
        ) as mock_run:
            ensure_image_available("python:3.12-slim")
            assert mock_run.call_count == 1
            assert "inspect" in str(mock_run.call_args[0][0])

    def test_image_pulled_when_missing(self):
        from initrunner.agent.docker_sandbox import ensure_image_available

        inspect_fail = MagicMock(returncode=1)
        pull_ok = MagicMock(returncode=0, stderr=b"")
        with patch(
            "initrunner.agent.docker_sandbox.subprocess.run",
            side_effect=[inspect_fail, pull_ok],
        ) as mock_run:
            ensure_image_available("python:3.12-slim")
            assert mock_run.call_count == 2

    def test_pull_failure_raises(self):
        from initrunner.agent.docker_sandbox import (
            DockerNotAvailableError,
            ensure_image_available,
        )

        inspect_fail = MagicMock(returncode=1)
        pull_fail = MagicMock(returncode=1, stderr=b"not found")
        with patch(
            "initrunner.agent.docker_sandbox.subprocess.run",
            side_effect=[inspect_fail, pull_fail],
        ):
            with pytest.raises(DockerNotAvailableError, match="private image"):
                ensure_image_available("nonexistent:latest")

    def test_pull_timeout_raises(self):
        from initrunner.agent.docker_sandbox import (
            DockerNotAvailableError,
            ensure_image_available,
        )

        inspect_fail = MagicMock(returncode=1)
        with patch(
            "initrunner.agent.docker_sandbox.subprocess.run",
            side_effect=[inspect_fail, subprocess.TimeoutExpired(cmd="docker", timeout=300)],
        ):
            with pytest.raises(DockerNotAvailableError, match="Timed out"):
                ensure_image_available("huge-image:latest")


# ===========================================================================
# User flag
# ===========================================================================


class TestUserFlag:
    def test_auto_user_with_writable_work_dir(self):
        import os

        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker")
        cmd = _build_docker_cmd(config, work_dir="/my/work")
        assert "--user" in cmd
        user_idx = cmd.index("--user")
        assert cmd[user_idx + 1] == f"{os.getuid()}:{os.getgid()}"

    def test_auto_user_no_writable_mounts(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker")
        cmd = _build_docker_cmd(config)
        assert "--user" not in cmd

    def test_auto_user_with_rw_bind_mount(self, tmp_path):
        import os

        from initrunner.agent.docker_sandbox import _build_docker_cmd

        (tmp_path / "out").mkdir()
        config = SandboxConfig(
            backend="docker",
            bind_mounts=[BindMount(source="./out", target="/out", read_only=False)],
        )
        cmd = _build_docker_cmd(config, role_dir=tmp_path)
        assert "--user" in cmd
        user_idx = cmd.index("--user")
        assert cmd[user_idx + 1] == f"{os.getuid()}:{os.getgid()}"

    def test_null_user_runs_as_root(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker", docker=DockerBackendConfig(user=None))
        cmd = _build_docker_cmd(config, work_dir="/my/work")
        assert "--user" not in cmd

    def test_explicit_user(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = SandboxConfig(backend="docker", docker=DockerBackendConfig(user="1000:1000"))
        cmd = _build_docker_cmd(config)
        assert "--user" in cmd
        user_idx = cmd.index("--user")
        assert cmd[user_idx + 1] == "1000:1000"

    def test_default_user_is_auto(self):
        config = DockerBackendConfig()
        assert config.user == "auto"
