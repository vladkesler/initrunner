"""Tests for the bubblewrap sandbox backend."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from initrunner.agent.runtime_sandbox import resolve_backend
from initrunner.agent.runtime_sandbox.base import SandboxConfigError
from initrunner.agent.runtime_sandbox.bwrap import BwrapBackend
from initrunner.agent.schema.security import SandboxConfig

_RUN = "initrunner.agent.runtime_sandbox.bwrap.subprocess.run"


@pytest.fixture(autouse=True)
def _no_systemd_run():
    """Keep the systemd-run wrapper out of the command line under test."""
    with patch("initrunner.agent.runtime_sandbox.bwrap._check_systemd_run", return_value=False):
        yield


def _ok():
    return MagicMock(stdout=b"", stderr=b"", returncode=0)


def _bwrap_cmd(config: SandboxConfig, tmp_path) -> list[str]:
    backend = BwrapBackend(config)
    with patch(_RUN, return_value=_ok()) as mock_run:
        backend.run(["true"], env={}, cwd=tmp_path, timeout=5)
    return mock_run.call_args[0][0]


def _make_ctx(network: str):
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
                "security": {"sandbox": {"backend": "bwrap", "network": network}},
            },
        }
    )
    backend = resolve_backend(role.spec.security.sandbox)
    return ToolBuildContext(role=role, sandbox_backend=backend)


class TestNetwork:
    def test_none_unshares_the_network(self, tmp_path):
        cmd = _bwrap_cmd(SandboxConfig(backend="bwrap", network="none"), tmp_path)
        assert cmd[0] == "bwrap"
        assert "--unshare-net" in cmd

    def test_host_keeps_the_host_network(self, tmp_path):
        cmd = _bwrap_cmd(SandboxConfig(backend="bwrap", network="host"), tmp_path)
        assert cmd[0] == "bwrap"
        assert "--unshare-net" not in cmd

    def test_bridge_rejected_when_the_config_loads(self):
        with pytest.raises(ValidationError, match="bridge is not supported with backend: bwrap"):
            SandboxConfig(backend="bwrap", network="bridge")

    def test_bridge_refused_by_a_backend_built_by_hand(self, tmp_path):
        # auto never hands bridge to bwrap; a backend constructed directly still refuses.
        backend = BwrapBackend(SandboxConfig(backend="auto", network="bridge"))
        with patch(_RUN, return_value=_ok()) as mock_run:
            with pytest.raises(SandboxConfigError, match="bridge is not supported"):
                backend.run(["true"], env={}, cwd=tmp_path, timeout=5)
        mock_run.assert_not_called()


class TestUnsetEnv:
    def test_named_variables_are_not_passed_through(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:3128")
        monkeypatch.setenv("TZ", "UTC")
        backend = BwrapBackend(SandboxConfig(backend="bwrap", env_passthrough=["HTTP_PROXY", "TZ"]))

        with patch(_RUN, return_value=_ok()) as mock_run:
            backend.run(["true"], env={}, unset_env=["HTTP_PROXY"], cwd=tmp_path, timeout=5)

        cmd = mock_run.call_args[0][0]
        assert "HTTP_PROXY" not in cmd
        assert cmd[cmd.index("TZ") - 1 : cmd.index("TZ") + 2] == ["--setenv", "TZ", "UTC"]


class TestPreflight:
    def test_probe_mounts_the_same_system_paths_as_a_run(self):
        """With only /usr mounted, /bin/true is missing wherever /bin links into /usr."""
        from initrunner.agent.runtime_sandbox.bwrap import _system_ro_binds

        backend = BwrapBackend(SandboxConfig(backend="bwrap"))
        with (
            patch("initrunner.agent.runtime_sandbox.bwrap.sys.platform", "linux"),
            patch(
                "initrunner.agent.runtime_sandbox.bwrap.shutil.which", return_value="/usr/bin/bwrap"
            ),
            patch(_RUN, return_value=_ok()) as mock_run,
        ):
            backend.preflight()

        probe = mock_run.call_args[0][0]
        assert probe == ["bwrap", *_system_ro_binds(), "--", "true"]
        assert ["--ro-bind", "/usr", "/usr"] == probe[1:4]


class TestLimits:
    @pytest.mark.parametrize(
        ("limit", "systemd_value"),
        [
            ("256m", "256M"),
            ("1g", "1G"),
            ("512K", "512K"),
            ("4096b", "4096"),
            ("1048576", "1048576"),
        ],
    )
    def test_memory_limit_is_written_the_way_systemd_reads_it(self, tmp_path, limit, systemd_value):
        backend = BwrapBackend(SandboxConfig(backend="bwrap", memory_limit=limit, cpu_limit=0.5))
        with (
            patch("initrunner.agent.runtime_sandbox.bwrap._check_systemd_run", return_value=True),
            patch(_RUN, return_value=_ok()) as mock_run,
        ):
            backend.run(["true"], env={}, cwd=tmp_path, timeout=5)

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "systemd-run"
        assert f"MemoryMax={systemd_value}" in cmd
        assert "CPUQuota=50%" in cmd


class TestAutoSelection:
    def test_bridge_goes_to_docker(self):
        with (
            patch("initrunner.agent.runtime_sandbox.select.sys.platform", "linux"),
            patch.object(BwrapBackend, "preflight") as bwrap_preflight,
            patch("initrunner.agent.runtime_sandbox.docker.DockerBackend.preflight"),
        ):
            backend = resolve_backend(SandboxConfig(backend="auto", network="bridge"))

        assert backend.name == "docker"
        bwrap_preflight.assert_not_called()

    def test_host_still_prefers_bwrap(self):
        with (
            patch("initrunner.agent.runtime_sandbox.select.sys.platform", "linux"),
            patch.object(BwrapBackend, "preflight"),
        ):
            backend = resolve_backend(SandboxConfig(backend="auto", network="host"))

        assert backend.name == "bwrap"


class TestShellToolIntegration:
    @pytest.mark.parametrize(("network", "unshared"), [("none", True), ("host", False)])
    def test_role_network_reaches_the_command_line(self, network, unshared):
        from initrunner.agent.schema.tools import ShellToolConfig
        from initrunner.agent.tools.shell import build_shell_toolset

        toolset = build_shell_toolset(
            ShellToolConfig(require_confirmation=False), _make_ctx(network)
        )
        fn = toolset.tools["run_shell"].function

        with patch(_RUN, return_value=_ok()) as mock_run:
            fn(command="echo hello")

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "bwrap"
        assert ("--unshare-net" in cmd) is unshared
