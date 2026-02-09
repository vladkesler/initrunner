"""Tests for systemd integration (compose/systemd.py)."""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock, patch

import pytest

from initrunner.compose.systemd import (
    SystemdError,
    UnitInfo,
    check_linger_enabled,
    check_systemd_available,
    find_initrunner_executable,
    generate_env_template,
    generate_unit_content,
    install_unit,
    resolve_compose_name,
    sanitize_unit_name,
    uninstall_unit,
    unit_name_for,
)

# ---------------------------------------------------------------------------
# sanitize_unit_name
# ---------------------------------------------------------------------------


class TestSanitizeUnitName:
    def test_simple_name(self):
        assert sanitize_unit_name("my-project") == "my-project"

    def test_spaces_replaced(self):
        assert sanitize_unit_name("my project") == "my-project"

    def test_special_chars(self):
        assert sanitize_unit_name("my@project!v2") == "my-project-v2"

    def test_consecutive_dashes_collapsed(self):
        assert sanitize_unit_name("my---project") == "my-project"

    def test_leading_trailing_dashes_stripped(self):
        assert sanitize_unit_name("-my-project-") == "my-project"

    def test_underscores_preserved(self):
        assert sanitize_unit_name("my_project") == "my_project"

    def test_empty_becomes_unnamed(self):
        assert sanitize_unit_name("@@@") == "unnamed"

    def test_dots_replaced(self):
        assert sanitize_unit_name("my.project.v1") == "my-project-v1"

    def test_disambiguates_with_hash(self, tmp_path):
        """When an existing unit has a different WorkingDirectory, appends hash."""
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        existing_unit = unit_dir / "initrunner-myproj.service"
        existing_unit.write_text("WorkingDirectory=/some/other/dir\n")

        compose_path = tmp_path / "sub" / "compose.yaml"
        compose_path.parent.mkdir(parents=True)
        compose_path.write_text("")

        with patch("initrunner.compose.systemd._UNIT_DIR", unit_dir):
            result = sanitize_unit_name("myproj", compose_path)

        # Should have a 4-char hash suffix
        assert result.startswith("myproj-")
        assert len(result) == len("myproj-") + 4

    def test_no_disambiguate_when_same_workdir(self, tmp_path):
        """When existing unit has the same WorkingDirectory, no hash appended."""
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)

        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")

        existing_unit = unit_dir / "initrunner-myproj.service"
        existing_unit.write_text(f"WorkingDirectory={tmp_path}\n")

        with patch("initrunner.compose.systemd._UNIT_DIR", unit_dir):
            result = sanitize_unit_name("myproj", compose_path)

        assert result == "myproj"


# ---------------------------------------------------------------------------
# unit_name_for
# ---------------------------------------------------------------------------


class TestUnitNameFor:
    def test_format(self):
        assert unit_name_for("my-project") == "initrunner-my-project.service"

    def test_sanitizes(self):
        assert unit_name_for("my project!") == "initrunner-my-project.service"


# ---------------------------------------------------------------------------
# generate_unit_content
# ---------------------------------------------------------------------------


class TestGenerateUnitContent:
    def test_contains_exec_start(self, tmp_path):
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")

        content = generate_unit_content("test-proj", compose_path, executable="/usr/bin/initrunner")
        assert f"ExecStart=/usr/bin/initrunner compose up {compose_path.resolve()}" in content

    def test_exec_start_quotes_path_with_spaces(self, tmp_path):
        spaced = tmp_path / "my project"
        spaced.mkdir()
        compose_path = spaced / "compose.yaml"
        compose_path.write_text("")

        content = generate_unit_content("test-proj", compose_path, executable="/usr/bin/initrunner")
        resolved = str(compose_path.resolve())
        assert f'ExecStart=/usr/bin/initrunner compose up "{resolved}"' in content

    def test_read_write_paths_quotes_spaces(self, tmp_path):
        spaced = tmp_path / "my project"
        spaced.mkdir()
        compose_path = spaced / "compose.yaml"
        compose_path.write_text("")

        content = generate_unit_content("test-proj", compose_path, executable="/usr/bin/initrunner")
        resolved_dir = str(compose_path.resolve().parent)
        assert f'"{resolved_dir}"' in content

    def test_contains_working_directory(self, tmp_path):
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")

        content = generate_unit_content("test-proj", compose_path)
        assert f"WorkingDirectory={tmp_path}" in content

    def test_contains_environment_file(self, tmp_path):
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")

        content = generate_unit_content("test-proj", compose_path)
        assert f"EnvironmentFile=-{tmp_path}/.env" in content

    def test_contains_kill_signal(self, tmp_path):
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")

        content = generate_unit_content("test-proj", compose_path)
        assert "KillSignal=SIGTERM" in content

    def test_contains_timeout_stop(self, tmp_path):
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")

        content = generate_unit_content("test-proj", compose_path)
        assert "TimeoutStopSec=30" in content

    def test_protect_system_strict(self, tmp_path):
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")

        content = generate_unit_content("test-proj", compose_path)
        assert "ProtectSystem=strict" in content
        assert "ProtectHome=read-only" in content
        assert "ReadWritePaths=" in content

    def test_custom_env_file(self, tmp_path):
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")
        env_file = tmp_path / "secrets.env"

        content = generate_unit_content("test-proj", compose_path, env_file=env_file)
        assert f"EnvironmentFile={env_file.resolve()}" in content

    def test_syslog_identifier(self, tmp_path):
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")

        content = generate_unit_content("test-proj", compose_path)
        assert "SyslogIdentifier=initrunner-test-proj" in content

    def test_managed_header(self, tmp_path):
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")

        content = generate_unit_content("test-proj", compose_path)
        assert "Managed by initrunner" in content


# ---------------------------------------------------------------------------
# generate_env_template
# ---------------------------------------------------------------------------


class TestGenerateEnvTemplate:
    def test_contains_placeholder_keys(self):
        content = generate_env_template("my-proj")
        assert "OPENAI_API_KEY" in content
        assert "ANTHROPIC_API_KEY" in content
        assert "my-proj" in content


# ---------------------------------------------------------------------------
# install_unit
# ---------------------------------------------------------------------------


class TestInstallUnit:
    @patch("initrunner.compose.systemd._systemctl")
    @patch("initrunner.compose.systemd.check_systemd_available")
    def test_creates_unit_file(self, mock_check, mock_ctl, tmp_path):
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")

        with patch("initrunner.compose.systemd._UNIT_DIR", unit_dir):
            info = install_unit("test-proj", compose_path, executable="/usr/bin/initrunner")

        assert info.unit_name == "initrunner-test-proj.service"
        assert info.unit_path.exists()
        assert "ExecStart" in info.unit_path.read_text()

    @patch("initrunner.compose.systemd._systemctl")
    @patch("initrunner.compose.systemd.check_systemd_available")
    def test_daemon_reload_called(self, mock_check, mock_ctl, tmp_path):
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")

        with patch("initrunner.compose.systemd._UNIT_DIR", unit_dir):
            install_unit("test-proj", compose_path, executable="/usr/bin/initrunner")

        mock_ctl.assert_called_once_with("daemon-reload")

    @patch("initrunner.compose.systemd._systemctl")
    @patch("initrunner.compose.systemd.check_systemd_available")
    def test_refuses_without_force(self, mock_check, mock_ctl, tmp_path):
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")
        (unit_dir / "initrunner-test-proj.service").write_text(f"WorkingDirectory={tmp_path}\n")

        with (
            patch("initrunner.compose.systemd._UNIT_DIR", unit_dir),
            pytest.raises(SystemdError, match="already exists"),
        ):
            install_unit("test-proj", compose_path, executable="/usr/bin/initrunner")

    @patch("initrunner.compose.systemd._systemctl")
    @patch("initrunner.compose.systemd.check_systemd_available")
    def test_force_overwrite(self, mock_check, mock_ctl, tmp_path):
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")
        existing = unit_dir / "initrunner-test-proj.service"
        existing.write_text("old content")

        with patch("initrunner.compose.systemd._UNIT_DIR", unit_dir):
            info = install_unit(
                "test-proj",
                compose_path,
                force=True,
                executable="/usr/bin/initrunner",
            )

        assert info.unit_path.exists()
        assert "old content" not in info.unit_path.read_text()

    @patch("initrunner.compose.systemd._systemctl")
    @patch("initrunner.compose.systemd.check_systemd_available")
    def test_returns_unit_info(self, mock_check, mock_ctl, tmp_path):
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text("")

        with patch("initrunner.compose.systemd._UNIT_DIR", unit_dir):
            info = install_unit("test-proj", compose_path, executable="/usr/bin/initrunner")

        assert isinstance(info, UnitInfo)
        assert info.compose_name == "test-proj"
        assert info.compose_path == compose_path.resolve()


# ---------------------------------------------------------------------------
# uninstall_unit
# ---------------------------------------------------------------------------


class TestUninstallUnit:
    @patch("initrunner.compose.systemd._systemctl")
    @patch("initrunner.compose.systemd.check_systemd_available")
    def test_stop_disable_remove_reload(self, mock_check, mock_ctl, tmp_path):
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit_file = unit_dir / "initrunner-test-proj.service"
        unit_file.write_text("unit content")

        with patch("initrunner.compose.systemd._UNIT_DIR", unit_dir):
            path = uninstall_unit("test-proj")

        assert path == unit_file
        assert not unit_file.exists()

        calls = [c.args for c in mock_ctl.call_args_list]
        assert ("stop", "initrunner-test-proj.service") in [c[:2] for c in calls]
        assert ("disable", "initrunner-test-proj.service") in [c[:2] for c in calls]
        assert ("daemon-reload",) in calls

    @patch("initrunner.compose.systemd.check_systemd_available")
    def test_raises_if_missing(self, mock_check, tmp_path):
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)

        with (
            patch("initrunner.compose.systemd._UNIT_DIR", unit_dir),
            pytest.raises(SystemdError, match="not found"),
        ):
            uninstall_unit("nonexistent")


# ---------------------------------------------------------------------------
# resolve_compose_name
# ---------------------------------------------------------------------------


class TestResolveComposeName:
    def test_from_yaml_path(self, tmp_path):
        compose_file = tmp_path / "compose.yaml"
        compose_file.write_text(
            textwrap.dedent("""\
                apiVersion: initrunner/v1
                kind: Compose
                metadata:
                  name: my-project
                spec:
                  services:
                    svc:
                      role: role.yaml
            """)
        )
        assert resolve_compose_name(str(compose_file)) == "my-project"

    def test_from_plain_name(self):
        assert resolve_compose_name("my-project") == "my-project"

    def test_raises_for_nonexistent_yaml(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            resolve_compose_name("/tmp/does-not-exist.yaml")

    def test_yml_extension(self, tmp_path):
        compose_file = tmp_path / "compose.yml"
        compose_file.write_text(
            textwrap.dedent("""\
                apiVersion: initrunner/v1
                kind: Compose
                metadata:
                  name: yml-project
                spec:
                  services:
                    svc:
                      role: role.yaml
            """)
        )
        assert resolve_compose_name(str(compose_file)) == "yml-project"


# ---------------------------------------------------------------------------
# check_systemd_available
# ---------------------------------------------------------------------------


class TestCheckSystemdAvailable:
    @patch("shutil.which", return_value="/usr/bin/systemctl")
    def test_present(self, mock_which):
        check_systemd_available()  # should not raise

    @patch("shutil.which", return_value=None)
    def test_absent(self, mock_which):
        with pytest.raises(SystemdError, match="systemctl not found"):
            check_systemd_available()


# ---------------------------------------------------------------------------
# check_linger_enabled
# ---------------------------------------------------------------------------


class TestCheckLingerEnabled:
    @patch("shutil.which", return_value="/usr/bin/loginctl")
    @patch("subprocess.run")
    def test_linger_yes(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(stdout="Linger=yes\n")
        assert check_linger_enabled() is True

    @patch("shutil.which", return_value="/usr/bin/loginctl")
    @patch("subprocess.run")
    def test_linger_no(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(stdout="Linger=no\n")
        assert check_linger_enabled() is False

    @patch("shutil.which", return_value=None)
    def test_loginctl_not_found(self, mock_which):
        """Falls back to True when loginctl is not available."""
        assert check_linger_enabled() is True

    @patch("shutil.which", return_value="/usr/bin/loginctl")
    @patch("subprocess.run", side_effect=OSError("mock error"))
    def test_oserror_fallback(self, mock_run, mock_which):
        assert check_linger_enabled() is True


# ---------------------------------------------------------------------------
# find_initrunner_executable
# ---------------------------------------------------------------------------


class TestFindInitrunnerExecutable:
    @patch("shutil.which", return_value="/usr/local/bin/initrunner")
    def test_shutil_which_success(self, mock_which):
        result = find_initrunner_executable()
        assert "initrunner" in result

    @patch("shutil.which", return_value=None)
    def test_sys_executable_fallback(self, mock_which):
        result = find_initrunner_executable()
        assert "-m initrunner" in result
