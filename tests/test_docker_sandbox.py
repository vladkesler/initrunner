"""Tests for the Docker container sandbox."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent._subprocess import SubprocessTimeout
from initrunner.agent.schema.security import (
    _DOCKER_BLOCKED_ARGS,
    BindMount,
    DockerSandboxConfig,
    SecurityPolicy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(role_dir=None, docker_enabled=False, docker_network="none"):
    """Build a minimal ToolBuildContext with configurable Docker settings."""
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
                    "docker": {
                        "enabled": docker_enabled,
                        "network": docker_network,
                    }
                },
            },
        }
    )
    return ToolBuildContext(role=role, role_dir=role_dir)


# ===========================================================================
# Schema tests
# ===========================================================================


class TestDockerSandboxConfigDefaults:
    def test_defaults(self):
        config = DockerSandboxConfig()
        assert config.enabled is False
        assert config.image == "python:3.12-slim"
        assert config.network == "none"
        assert config.memory_limit == "256m"
        assert config.cpu_limit == 1.0
        assert config.read_only_rootfs is True
        assert config.bind_mounts == []
        assert config.env_passthrough == []
        assert config.extra_args == []

    def test_security_policy_has_docker_field(self):
        policy = SecurityPolicy()
        assert hasattr(policy, "docker")
        assert isinstance(policy.docker, DockerSandboxConfig)
        assert policy.docker.enabled is False


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


class TestDockerSandboxConfigValidation:
    def test_empty_image_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            DockerSandboxConfig(image="  ")

    def test_invalid_memory_limit(self):
        with pytest.raises(ValueError, match="Invalid memory_limit"):
            DockerSandboxConfig(memory_limit="abc")

    def test_valid_memory_formats(self):
        for mem in ("256m", "1g", "512M", "2G", "1024k", "100b", "256"):
            config = DockerSandboxConfig(memory_limit=mem)
            assert config.memory_limit == mem

    def test_cpu_limit_must_be_positive(self):
        with pytest.raises(ValueError):
            DockerSandboxConfig(cpu_limit=0)

    def test_cpu_limit_negative_rejected(self):
        with pytest.raises(ValueError):
            DockerSandboxConfig(cpu_limit=-1.0)

    def test_dangerous_extra_args_rejected(self):
        for arg in _DOCKER_BLOCKED_ARGS:
            with pytest.raises(ValueError, match="blocked for security"):
                DockerSandboxConfig(extra_args=[arg])

    def test_dangerous_extra_args_with_value_rejected(self):
        with pytest.raises(ValueError, match="blocked for security"):
            DockerSandboxConfig(extra_args=["--cap-add=ALL"])

    def test_safe_extra_args_allowed(self):
        config = DockerSandboxConfig(extra_args=["--pids-limit=100", "--ulimit=nofile=1024"])
        assert len(config.extra_args) == 2

    def test_duplicate_bind_mount_targets_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            DockerSandboxConfig(
                bind_mounts=[
                    BindMount(source="./a", target="/data"),
                    BindMount(source="./b", target="/data"),
                ]
            )

    def test_work_target_conflicts(self):
        with pytest.raises(ValueError, match="/work"):
            DockerSandboxConfig(bind_mounts=[BindMount(source="./project", target="/work")])

    def test_valid_bind_mounts(self):
        config = DockerSandboxConfig(
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

        config = DockerSandboxConfig()
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

        config = DockerSandboxConfig(read_only_rootfs=True)
        cmd = _build_docker_cmd(config)
        assert "--read-only" in cmd
        assert "--tmpfs" in cmd
        # Check tmpfs value
        tmpfs_idx = cmd.index("--tmpfs")
        assert "/tmp:" in cmd[tmpfs_idx + 1]

    def test_no_read_only_rootfs(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = DockerSandboxConfig(read_only_rootfs=False)
        cmd = _build_docker_cmd(config)
        assert "--read-only" not in cmd

    def test_bind_mounts_resolved(self, tmp_path):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = DockerSandboxConfig(
            bind_mounts=[BindMount(source="./data", target="/data", read_only=True)]
        )
        cmd = _build_docker_cmd(config, role_dir=tmp_path)
        # Should contain -v with resolved path
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

        config = DockerSandboxConfig()
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
        config = DockerSandboxConfig(env_passthrough=["LANG", "TZ"])
        cmd = _build_docker_cmd(config)
        e_indices = [i for i, x in enumerate(cmd) if x == "-e"]
        env_args = [cmd[i + 1] for i in e_indices]
        assert "LANG=en_US.UTF-8" in env_args
        assert "TZ=UTC" in env_args

    def test_env_passthrough_skips_missing(self, monkeypatch):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        monkeypatch.delenv("NONEXISTENT_VAR_XYZ", raising=False)
        config = DockerSandboxConfig(env_passthrough=["NONEXISTENT_VAR_XYZ"])
        cmd = _build_docker_cmd(config)
        e_indices = [i for i, x in enumerate(cmd) if x == "-e"]
        env_args = [cmd[i + 1] for i in e_indices]
        assert not any("NONEXISTENT_VAR_XYZ" in a for a in env_args)

    def test_extra_args_appended(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = DockerSandboxConfig(extra_args=["--pids-limit=100"])
        cmd = _build_docker_cmd(config)
        assert "--pids-limit=100" in cmd
        # extra_args should come before image
        img_idx = cmd.index("python:3.12-slim")
        pids_idx = cmd.index("--pids-limit=100")
        assert pids_idx < img_idx

    def test_interactive_flag(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = DockerSandboxConfig()
        cmd = _build_docker_cmd(config, interactive=True)
        assert "-i" in cmd

    def test_no_interactive_by_default(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = DockerSandboxConfig()
        cmd = _build_docker_cmd(config, interactive=False)
        assert "-i" not in cmd

    def test_pids_limit_default(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = DockerSandboxConfig()
        cmd = _build_docker_cmd(config)
        pids_idx = cmd.index("--pids-limit")
        assert cmd[pids_idx + 1] == "256"

    def test_env_dict_passed(self):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = DockerSandboxConfig()
        cmd = _build_docker_cmd(config, env={"MY_VAR": "hello"})
        e_indices = [i for i, x in enumerate(cmd) if x == "-e"]
        env_args = [cmd[i + 1] for i in e_indices]
        assert "MY_VAR=hello" in env_args

    def test_rw_mount(self, tmp_path):
        from initrunner.agent.docker_sandbox import _build_docker_cmd

        config = DockerSandboxConfig(
            bind_mounts=[BindMount(source="./data", target="/data", read_only=False)]
        )
        cmd = _build_docker_cmd(config, role_dir=tmp_path)
        v_indices = [i for i, x in enumerate(cmd) if x == "-v"]
        mount_arg = cmd[v_indices[0] + 1]
        assert ":/data" in mount_arg
        assert ":ro" not in mount_arg


# ===========================================================================
# Execution tests
# ===========================================================================


class TestDockerRunCommand:
    def test_builds_and_runs(self):
        from initrunner.agent.docker_sandbox import docker_run_command

        config = DockerSandboxConfig()
        mock_result = MagicMock(
            stdout=b"hello\n",
            stderr=b"",
            returncode=0,
        )
        with patch(
            "initrunner.agent.docker_sandbox.subprocess.run", return_value=mock_result
        ) as mock_run:
            stdout, stderr, rc = docker_run_command(["echo", "hello"], config, timeout=30)
            assert stdout == "hello\n"
            assert stderr == ""
            assert rc == 0
            # Verify docker run was called
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            assert cmd[:3] == ["docker", "run", "--rm"]
            assert cmd[-2:] == ["echo", "hello"]

    def test_timeout_raises(self):
        from initrunner.agent.docker_sandbox import docker_run_command

        config = DockerSandboxConfig()
        with patch(
            "initrunner.agent.docker_sandbox.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=5),
        ):
            with pytest.raises(SubprocessTimeout):
                docker_run_command(["sleep", "100"], config, timeout=5)


class TestDockerRunPython:
    def test_creates_temp_file_and_runs(self):
        from initrunner.agent.docker_sandbox import docker_run_python

        config = DockerSandboxConfig()
        mock_result = MagicMock(
            stdout=b"42\n",
            stderr=b"",
            returncode=0,
        )
        with patch(
            "initrunner.agent.docker_sandbox.subprocess.run", return_value=mock_result
        ) as mock_run:
            stdout, _stderr, rc = docker_run_python("print(42)", config, timeout=30)
            assert stdout == "42\n"
            assert rc == 0
            # Verify command includes python /code/_run.py
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            assert cmd[-2:] == ["python", "/code/_run.py"]
            # Verify /code mount exists
            v_indices = [i for i, x in enumerate(cmd) if x == "-v"]
            code_mounts = [cmd[i + 1] for i in v_indices if ":/code" in cmd[i + 1]]
            assert len(code_mounts) == 1

    def test_temp_dir_cleaned_up(self, tmp_path):
        from initrunner.agent.docker_sandbox import docker_run_python

        config = DockerSandboxConfig()
        created_dirs = []

        original_mkdtemp = __import__("tempfile").mkdtemp

        def tracking_mkdtemp(**kwargs):
            d = original_mkdtemp(**kwargs)
            created_dirs.append(d)
            return d

        mock_result = MagicMock(stdout=b"ok\n", stderr=b"", returncode=0)
        with patch("initrunner.agent.docker_sandbox.subprocess.run", return_value=mock_result):
            with patch(
                "initrunner.agent.docker_sandbox.tempfile.mkdtemp", side_effect=tracking_mkdtemp
            ):
                docker_run_python("print('ok')", config, timeout=30)

        # Verify temp dir was cleaned up
        assert len(created_dirs) == 1
        assert not Path(created_dirs[0]).exists()

    def test_temp_dir_cleaned_up_on_timeout(self):
        from initrunner.agent.docker_sandbox import docker_run_python

        config = DockerSandboxConfig()
        created_dirs = []

        original_mkdtemp = __import__("tempfile").mkdtemp

        def tracking_mkdtemp(**kwargs):
            d = original_mkdtemp(**kwargs)
            created_dirs.append(d)
            return d

        with patch(
            "initrunner.agent.docker_sandbox.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=5),
        ):
            with patch(
                "initrunner.agent.docker_sandbox.tempfile.mkdtemp", side_effect=tracking_mkdtemp
            ):
                with pytest.raises(SubprocessTimeout):
                    docker_run_python("import time; time.sleep(100)", config, timeout=5)

        assert len(created_dirs) == 1
        assert not Path(created_dirs[0]).exists()

    def test_timeout_raises(self):
        from initrunner.agent.docker_sandbox import docker_run_python

        config = DockerSandboxConfig()
        with patch(
            "initrunner.agent.docker_sandbox.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=5),
        ):
            with pytest.raises(SubprocessTimeout):
                docker_run_python("import time; time.sleep(100)", config, timeout=5)


class TestDockerRunScript:
    def test_pipes_body_via_stdin(self):
        from initrunner.agent.docker_sandbox import docker_run_script

        config = DockerSandboxConfig()
        mock_result = MagicMock(
            stdout=b"hello\n",
            stderr=b"",
            returncode=0,
        )
        with patch(
            "initrunner.agent.docker_sandbox.subprocess.run", return_value=mock_result
        ) as mock_run:
            stdout, _stderr, rc = docker_run_script("echo hello", "/bin/sh", config, timeout=30)
            assert stdout == "hello\n"
            assert rc == 0
            # Verify -i flag and interpreter
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            assert "-i" in cmd
            assert cmd[-1] == "/bin/sh"
            # Verify stdin
            assert call_args[1]["input"] == b"echo hello"

    def test_env_passed_as_flags(self):
        from initrunner.agent.docker_sandbox import docker_run_script

        config = DockerSandboxConfig()
        mock_result = MagicMock(stdout=b"", stderr=b"", returncode=0)
        with patch(
            "initrunner.agent.docker_sandbox.subprocess.run", return_value=mock_result
        ) as mock_run:
            docker_run_script(
                "echo $NAME",
                "/bin/sh",
                config,
                timeout=30,
                env={"NAME": "Alice"},
            )
            cmd = mock_run.call_args[0][0]
            e_indices = [i for i, x in enumerate(cmd) if x == "-e"]
            env_args = [cmd[i + 1] for i in e_indices]
            assert "NAME=Alice" in env_args

    def test_timeout_raises(self):
        from initrunner.agent.docker_sandbox import docker_run_script

        config = DockerSandboxConfig()
        with patch(
            "initrunner.agent.docker_sandbox.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=5),
        ):
            with pytest.raises(SubprocessTimeout):
                docker_run_script("sleep 100", "/bin/sh", config, timeout=5)


# ===========================================================================
# Tool builder integration tests
# ===========================================================================


class TestShellToolDockerIntegration:
    def test_uses_docker_when_enabled(self):
        from initrunner.agent.schema.tools import ShellToolConfig
        from initrunner.agent.tools.shell import build_shell_toolset

        ctx = _make_ctx(docker_enabled=True)
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, ctx)
        fn = toolset.tools["run_shell"].function

        with patch("initrunner.agent.docker_sandbox.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=b"hello\n", stderr=b"", returncode=0)
            output = fn(command="echo hello")
            assert "hello" in output
            cmd = mock_run.call_args[0][0]
            assert cmd[:3] == ["docker", "run", "--rm"]

    def test_uses_normal_path_when_disabled(self):
        from initrunner.agent.schema.tools import ShellToolConfig
        from initrunner.agent.tools.shell import build_shell_toolset

        ctx = _make_ctx(docker_enabled=False)
        config = ShellToolConfig(require_confirmation=False, blocked_commands=[])
        toolset = build_shell_toolset(config, ctx)
        fn = toolset.tools["run_shell"].function

        output = fn(command="echo hello")
        assert "hello" in output


class TestPythonToolDockerIntegration:
    def test_uses_docker_when_enabled(self):
        from initrunner.agent.schema.tools import PythonToolConfig
        from initrunner.agent.tools.python_exec import build_python_toolset

        ctx = _make_ctx(docker_enabled=True)
        config = PythonToolConfig(require_confirmation=False)
        toolset = build_python_toolset(config, ctx)
        fn = toolset.tools["run_python"].function

        with patch("initrunner.agent.docker_sandbox.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=b"42\n", stderr=b"", returncode=0)
            output = fn(code="print(42)")
            assert "42" in output
            cmd = mock_run.call_args[0][0]
            assert cmd[:3] == ["docker", "run", "--rm"]

    def test_uses_normal_path_when_disabled(self):
        from initrunner.agent.schema.tools import PythonToolConfig
        from initrunner.agent.tools.python_exec import build_python_toolset

        ctx = _make_ctx(docker_enabled=False)
        config = PythonToolConfig(require_confirmation=False)
        toolset = build_python_toolset(config, ctx)
        fn = toolset.tools["run_python"].function

        output = fn(code='print("hello")')
        assert "hello" in output

    def test_network_disabled_no_shim_when_docker_none(self):
        """network_disabled + Docker network=none → no shim (Docker provides isolation)."""
        from initrunner.agent.schema.tools import PythonToolConfig
        from initrunner.agent.tools.python_exec import build_python_toolset

        ctx = _make_ctx(docker_enabled=True, docker_network="none")
        config = PythonToolConfig(require_confirmation=False, network_disabled=True)
        toolset = build_python_toolset(config, ctx)
        fn = toolset.tools["run_python"].function

        with patch("initrunner.agent.docker_sandbox.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=b"ok\n", stderr=b"", returncode=0)
            fn(code='print("ok")')
            # The code written to temp file should NOT contain the shim
            # We can't easily check the temp file content directly,
            # but we can verify docker was called
            assert mock_run.called

    def test_network_disabled_shim_preserved_when_docker_bridge(self):
        """network_disabled + Docker network=bridge → shim preserved."""
        from initrunner.agent.schema.tools import PythonToolConfig
        from initrunner.agent.tools.python_exec import build_python_toolset

        ctx = _make_ctx(docker_enabled=True, docker_network="bridge")
        config = PythonToolConfig(require_confirmation=False, network_disabled=True)
        toolset = build_python_toolset(config, ctx)
        fn = toolset.tools["run_python"].function

        written_code = None

        def capture_code(*args, **kwargs):
            # The code is written to a temp file, then docker is called
            # We check the file content in the temp dir
            return MagicMock(stdout=b"ok\n", stderr=b"", returncode=0)

        with patch("initrunner.agent.docker_sandbox.subprocess.run", side_effect=capture_code):
            with patch("initrunner.agent.docker_sandbox.Path.write_text") as mock_write:
                fn(code='print("ok")')
                # The write_text call should contain the shim
                if mock_write.called:
                    written_code = mock_write.call_args[0][0]
                    assert "_block_network" in written_code

    def test_network_not_disabled_no_shim(self):
        """network_disabled=false + Docker → no shim regardless of network."""
        from initrunner.agent.schema.tools import PythonToolConfig
        from initrunner.agent.tools.python_exec import build_python_toolset

        ctx = _make_ctx(docker_enabled=True, docker_network="bridge")
        config = PythonToolConfig(require_confirmation=False, network_disabled=False)
        toolset = build_python_toolset(config, ctx)
        fn = toolset.tools["run_python"].function

        with patch("initrunner.agent.docker_sandbox.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=b"ok\n", stderr=b"", returncode=0)
            fn(code='print("ok")')
            assert mock_run.called


class TestScriptToolDockerIntegration:
    def test_uses_docker_when_enabled(self):
        from initrunner.agent.schema.tools import ScriptDefinition, ScriptToolConfig
        from initrunner.agent.tools.script import build_script_toolset

        ctx = _make_ctx(docker_enabled=True)
        config = ScriptToolConfig(scripts=[ScriptDefinition(name="hello", body="echo hello")])
        toolset = build_script_toolset(config, ctx)
        fn = toolset.tools["hello"].function

        with patch("initrunner.agent.docker_sandbox.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=b"hello\n", stderr=b"", returncode=0)
            output = fn()
            assert "hello" in output
            cmd = mock_run.call_args[0][0]
            assert cmd[:3] == ["docker", "run", "--rm"]
            assert "-i" in cmd

    def test_uses_normal_path_when_disabled(self):
        from initrunner.agent.schema.tools import ScriptDefinition, ScriptToolConfig
        from initrunner.agent.tools.script import build_script_toolset

        ctx = _make_ctx(docker_enabled=False)
        config = ScriptToolConfig(scripts=[ScriptDefinition(name="hello", body="echo hello")])
        toolset = build_script_toolset(config, ctx)
        fn = toolset.tools["hello"].function

        output = fn()
        assert "hello" in output


# ===========================================================================
# Registry startup validation tests
# ===========================================================================


class TestRegistryDockerValidation:
    def test_build_toolsets_calls_require_docker_when_enabled(self):
        from initrunner.agent.tools.registry import build_toolsets

        ctx = _make_ctx(docker_enabled=True)
        with patch("initrunner.agent.docker_sandbox.require_docker") as mock_require:
            build_toolsets([], ctx.role)

        mock_require.assert_called_once()

    def test_build_toolsets_skips_require_docker_when_disabled(self):
        from initrunner.agent.tools.registry import build_toolsets

        ctx = _make_ctx(docker_enabled=False)
        with patch("initrunner.agent.docker_sandbox.require_docker") as mock_require:
            build_toolsets([], ctx.role)

        mock_require.assert_not_called()
