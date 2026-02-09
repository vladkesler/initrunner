"""Tests for the compose CLI commands."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from initrunner.audit.logger import AuditLogger
from initrunner.cli.main import app

runner = CliRunner()


def _write_compose(tmp_path: Path) -> Path:
    compose_yaml = textwrap.dedent("""\
        apiVersion: initrunner/v1
        kind: Compose
        metadata:
          name: test-compose
        spec:
          services:
            agent-a:
              role: roles/a.yaml
            agent-b:
              role: roles/b.yaml
              sink:
                type: delegate
                target: agent-a
    """)
    f = tmp_path / "compose.yaml"
    f.write_text(compose_yaml)
    return f


def _write_roles(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    for name in ("a", "b"):
        role = textwrap.dedent(f"""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: agent-{name}
              description: Test agent {name}
            spec:
              role: You are agent {name}.
              model:
                provider: openai
                name: gpt-4o-mini
        """)
        (roles_dir / f"{name}.yaml").write_text(role)


class TestComposeValidate:
    def test_valid_compose(self, tmp_path):
        compose_file = _write_compose(tmp_path)
        _write_roles(tmp_path)

        result = runner.invoke(app, ["compose", "validate", str(compose_file)])
        assert result.exit_code == 0
        assert "Valid" in result.output

    def test_missing_compose_file(self, tmp_path):
        result = runner.invoke(app, ["compose", "validate", str(tmp_path / "nope.yaml")])
        assert result.exit_code == 1

    def test_invalid_compose(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("apiVersion: initrunner/v1\nkind: Compose\n")
        result = runner.invoke(app, ["compose", "validate", str(f)])
        assert result.exit_code == 1

    def test_missing_role_files(self, tmp_path):
        compose_file = _write_compose(tmp_path)
        # Don't create roles directory
        result = runner.invoke(app, ["compose", "validate", str(compose_file)])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_displays_service_table(self, tmp_path):
        compose_file = _write_compose(tmp_path)
        _write_roles(tmp_path)

        result = runner.invoke(app, ["compose", "validate", str(compose_file)])
        assert "agent-a" in result.output
        assert "agent-b" in result.output
        assert "delegate" in result.output


class TestComposeUp:
    @patch("initrunner.cli.compose_cmd.create_audit_logger")
    @patch("initrunner.compose.orchestrator.run_compose")
    @patch("initrunner.compose.loader.load_compose")
    def test_up_calls_run_compose(self, mock_load, mock_run, mock_audit, tmp_path):
        from initrunner.compose.schema import ComposeDefinition

        compose_file = _write_compose(tmp_path)
        mock_compose = MagicMock(spec=ComposeDefinition)
        mock_load.return_value = mock_compose
        mock_audit.return_value = None

        runner.invoke(app, ["compose", "up", str(compose_file)])
        mock_run.assert_called_once()

    def test_up_missing_file(self, tmp_path):
        result = runner.invoke(app, ["compose", "up", str(tmp_path / "nope.yaml")])
        assert result.exit_code == 1

    def test_up_invalid_compose(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("not: valid\n")
        result = runner.invoke(app, ["compose", "up", str(f)])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# systemd lifecycle CLI tests
# ---------------------------------------------------------------------------


class TestComposeInstall:
    @patch("initrunner.compose.systemd.check_linger_enabled", return_value=True)
    @patch("initrunner.compose.systemd.install_unit")
    def test_valid_compose(self, mock_install, mock_linger, tmp_path):
        from initrunner.compose.systemd import UnitInfo

        compose_file = _write_compose(tmp_path)
        unit_path = tmp_path / "initrunner-test-compose.service"
        mock_install.return_value = UnitInfo(
            unit_name="initrunner-test-compose.service",
            unit_path=unit_path,
            compose_name="test-compose",
            compose_path=compose_file.resolve(),
        )

        result = runner.invoke(app, ["compose", "install", str(compose_file)])
        assert result.exit_code == 0
        assert "Installed" in result.output
        assert "initrunner-test-compose.service" in result.output
        mock_install.assert_called_once()

    def test_invalid_compose(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("not: valid\n")
        result = runner.invoke(app, ["compose", "install", str(f)])
        assert result.exit_code == 1

    def test_missing_compose_file(self, tmp_path):
        result = runner.invoke(app, ["compose", "install", str(tmp_path / "nope.yaml")])
        assert result.exit_code == 1

    @patch("initrunner.compose.systemd.check_linger_enabled", return_value=True)
    @patch("initrunner.compose.systemd.install_unit")
    def test_force_overwrite(self, mock_install, mock_linger, tmp_path):
        from initrunner.compose.systemd import UnitInfo

        compose_file = _write_compose(tmp_path)
        mock_install.return_value = UnitInfo(
            unit_name="initrunner-test-compose.service",
            unit_path=tmp_path / "unit.service",
            compose_name="test-compose",
            compose_path=compose_file.resolve(),
        )

        result = runner.invoke(app, ["compose", "install", "--force", str(compose_file)])
        assert result.exit_code == 0
        call_kwargs = mock_install.call_args
        assert call_kwargs[1]["force"] is True

    @patch("initrunner.compose.systemd.install_unit")
    @patch("initrunner.compose.systemd.check_linger_enabled", return_value=False)
    def test_linger_warning(self, mock_linger, mock_install, tmp_path):
        from initrunner.compose.systemd import UnitInfo

        compose_file = _write_compose(tmp_path)
        mock_install.return_value = UnitInfo(
            unit_name="initrunner-test-compose.service",
            unit_path=tmp_path / "unit.service",
            compose_name="test-compose",
            compose_path=compose_file.resolve(),
        )

        result = runner.invoke(app, ["compose", "install", str(compose_file)])
        assert result.exit_code == 0
        assert "lingering" in result.output.lower()

    @patch("initrunner.compose.systemd.check_linger_enabled", return_value=True)
    @patch("initrunner.compose.systemd.install_unit")
    def test_generate_env(self, mock_install, mock_linger, tmp_path):
        from initrunner.compose.systemd import UnitInfo

        compose_file = _write_compose(tmp_path)
        mock_install.return_value = UnitInfo(
            unit_name="initrunner-test-compose.service",
            unit_path=tmp_path / "unit.service",
            compose_name="test-compose",
            compose_path=compose_file.resolve(),
        )

        result = runner.invoke(app, ["compose", "install", "--generate-env", str(compose_file)])
        assert result.exit_code == 0
        env_path = tmp_path / ".env"
        assert env_path.exists()
        assert "OPENAI_API_KEY" in env_path.read_text()


class TestComposeUninstall:
    @patch("initrunner.compose.systemd.uninstall_unit")
    def test_by_name(self, mock_uninstall):
        unit = Path("/home/user/.config/systemd/user/initrunner-proj.service")
        mock_uninstall.return_value = unit
        result = runner.invoke(app, ["compose", "uninstall", "proj"])
        assert result.exit_code == 0
        assert "Uninstalled" in result.output

    @patch("initrunner.compose.systemd.uninstall_unit")
    @patch("initrunner.compose.systemd.resolve_compose_name", return_value="test-compose")
    def test_by_path(self, mock_resolve, mock_uninstall, tmp_path):
        compose_file = _write_compose(tmp_path)
        mock_uninstall.return_value = Path(
            "/home/user/.config/systemd/user/initrunner-test-compose.service"
        )
        result = runner.invoke(app, ["compose", "uninstall", str(compose_file)])
        assert result.exit_code == 0
        mock_resolve.assert_called_once_with(str(compose_file))


class TestComposeStart:
    @patch("subprocess.run")
    @patch("initrunner.compose.systemd.check_systemd_available")
    def test_calls_systemctl(self, mock_check, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["compose", "start", "my-proj"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["systemctl", "--user", "start", "initrunner-my-proj.service"]


class TestComposeStop:
    @patch("subprocess.run")
    @patch("initrunner.compose.systemd.check_systemd_available")
    def test_calls_systemctl(self, mock_check, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["compose", "stop", "my-proj"])
        assert result.exit_code == 0
        args = mock_run.call_args[0][0]
        assert args == ["systemctl", "--user", "stop", "initrunner-my-proj.service"]


class TestComposeRestart:
    @patch("subprocess.run")
    @patch("initrunner.compose.systemd.check_systemd_available")
    def test_calls_systemctl(self, mock_check, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["compose", "restart", "my-proj"])
        assert result.exit_code == 0
        args = mock_run.call_args[0][0]
        assert args == ["systemctl", "--user", "restart", "initrunner-my-proj.service"]


class TestComposeStatus:
    @patch("initrunner.compose.systemd.get_unit_status", return_value="active (running)")
    def test_output_forwarded(self, mock_status):
        result = runner.invoke(app, ["compose", "status", "my-proj"])
        assert result.exit_code == 0
        assert "active (running)" in result.output

    @patch(
        "initrunner.compose.systemd.get_unit_status",
        side_effect=lambda n: (_ for _ in ()).throw(
            __import__("initrunner.compose.systemd", fromlist=["SystemdError"]).SystemdError(
                "not found"
            )
        ),
    )
    def test_error_handling(self, mock_status):
        from initrunner.compose.systemd import SystemdError

        with patch("initrunner.compose.systemd.get_unit_status", side_effect=SystemdError("fail")):
            result = runner.invoke(app, ["compose", "status", "my-proj"])
        assert result.exit_code == 1


class TestComposeLogs:
    @patch("subprocess.run")
    @patch("initrunner.compose.systemd.check_systemd_available")
    def test_journalctl_args(self, mock_check, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["compose", "logs", "my-proj"])
        assert result.exit_code == 0
        args = mock_run.call_args[0][0]
        assert "journalctl" in args
        assert "--user" in args
        assert "--unit=initrunner-my-proj.service" in args
        assert "--lines=50" in args
        assert "--no-pager" in args
        assert "--follow" not in args

    @patch("subprocess.run")
    @patch("initrunner.compose.systemd.check_systemd_available")
    def test_follow_flag(self, mock_check, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["compose", "logs", "--follow", "my-proj"])
        assert result.exit_code == 0
        args = mock_run.call_args[0][0]
        assert "--follow" in args

    @patch("subprocess.run")
    @patch("initrunner.compose.systemd.check_systemd_available")
    def test_custom_lines(self, mock_check, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["compose", "logs", "--lines", "100", "my-proj"])
        assert result.exit_code == 0
        args = mock_run.call_args[0][0]
        assert "--lines=100" in args


class TestComposeEvents:
    def test_no_db_exits_with_error(self, tmp_path):
        result = runner.invoke(
            app,
            ["compose", "events", "--audit-db", str(tmp_path / "nonexistent.db")],
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_empty_db_shows_message(self, tmp_path):
        db_path = tmp_path / "audit.db"
        with AuditLogger(db_path):
            pass

        result = runner.invoke(
            app,
            ["compose", "events", "--audit-db", str(db_path)],
        )
        assert result.exit_code == 0
        assert "No delegate events found" in result.output

    def test_renders_table_with_seeded_data(self, tmp_path):
        db_path = tmp_path / "audit.db"
        with AuditLogger(db_path) as logger:
            logger.log_delegate_event(
                source_service="agent-a",
                target_service="agent-b",
                status="delivered",
                source_run_id="run-1",
                trace="agent-a",
                payload_preview="hello world",
            )
            logger.log_delegate_event(
                source_service="agent-b",
                target_service="agent-c",
                status="dropped",
                source_run_id="run-2",
                reason="queue_full",
            )

        result = runner.invoke(
            app,
            ["compose", "events", "--audit-db", str(db_path)],
        )
        assert result.exit_code == 0
        assert "agent-a" in result.output
        assert "agent-b" in result.output
        assert "delivered" in result.output
        assert "dropped" in result.output
        assert "queue_full" in result.output

    def test_status_filter(self, tmp_path):
        db_path = tmp_path / "audit.db"
        with AuditLogger(db_path) as logger:
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="delivered",
                source_run_id="r1",
            )
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="filtered",
                source_run_id="r2",
                reason="fail",
            )

        result = runner.invoke(
            app,
            ["compose", "events", "--status", "filtered", "--audit-db", str(db_path)],
        )
        assert result.exit_code == 0
        assert "filtered" in result.output
        assert "fail" in result.output

    def test_run_id_filter(self, tmp_path):
        db_path = tmp_path / "audit.db"
        with AuditLogger(db_path) as logger:
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="delivered",
                source_run_id="target-run",
            )
            logger.log_delegate_event(
                source_service="a",
                target_service="b",
                status="delivered",
                source_run_id="other-run",
            )

        result = runner.invoke(
            app,
            ["compose", "events", "--run-id", "target-run", "--audit-db", str(db_path)],
        )
        assert result.exit_code == 0
        assert "target-run" in result.output
