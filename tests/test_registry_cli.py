"""Tests for registry CLI commands (install, uninstall, list, search, update)."""

import json
import textwrap
from unittest.mock import MagicMock, patch

VALID_ROLE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: test-agent
      description: A test agent
      author: testuser
      version: "1.0.0"
      dependencies: []
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
""")


class TestCLIInstall:
    def test_install_owner_name_routes_to_hub(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", roles_dir / "registry.json"
        )

        from initrunner.hub import HubPackageInfo

        info = HubPackageInfo(
            owner="user",
            name="test-agent",
            description="Test",
            latest_version="1.0.0",
            versions=["1.0.0"],
        )

        def fake_extract(archive, dest):
            dest.mkdir(parents=True, exist_ok=True)
            m = MagicMock()
            m.name = "test-agent"
            return m

        with (
            patch("initrunner.hub.parse_hub_source", return_value=("user", "test-agent", None)),
            patch("initrunner.hub.hub_resolve", return_value=info),
            patch("initrunner.hub.hub_download", return_value=b"fake-bundle"),
            patch("initrunner.packaging.bundle.extract_bundle", side_effect=fake_extract),
        ):
            result = runner.invoke(app, ["install", "user/test-agent", "--yes"])

        assert result.exit_code == 0
        assert "Installed" in result.output

    def test_install_bare_name_shows_error(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()

        result = runner.invoke(app, ["install", "code-reviewer", "--yes"])

        assert result.exit_code == 1
        assert "Search InitHub" in result.output

    def test_install_not_found(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()

        from initrunner.hub import HubError

        with (
            patch("initrunner.hub.parse_hub_source", return_value=("user", "nonexistent", None)),
            patch(
                "initrunner.hub.hub_resolve",
                side_effect=HubError("Not found: /packages/user/nonexistent"),
            ),
        ):
            result = runner.invoke(app, ["install", "user/nonexistent", "--yes"])

        assert result.exit_code == 1
        assert "Not found" in result.output


class TestCLIUninstall:
    def test_uninstall_command(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)
        (roles_dir / "user__repo__test-agent.yaml").write_text(VALID_ROLE_YAML)
        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "test-agent": {
                            "local_path": "user__repo__test-agent.yaml",
                            "repo": "user/repo",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

        result = runner.invoke(app, ["uninstall", "test-agent"])
        assert result.exit_code == 0
        assert "Uninstalled" in result.output

    def test_uninstall_not_installed(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", tmp_path / "registry.json"
        )

        result = runner.invoke(app, ["uninstall", "nonexistent"])
        assert result.exit_code == 1


class TestCLIList:
    def test_list_empty(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", tmp_path / "registry.json"
        )

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "No roles installed" in result.output

    def test_list_with_roles(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()
        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "test-agent": {
                            "source_url": "https://example.com",
                            "repo": "user/repo",
                            "ref": "main",
                            "local_path": "user__repo__test-agent.yaml",
                            "installed_at": "2026-02-10T12:00:00",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "test-agent" in result.output


class TestCLISearch:
    def test_search_command(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app
        from initrunner.hub import HubSearchResult

        runner = CliRunner()
        hub_results = [
            HubSearchResult(
                owner="test",
                name="code-reviewer",
                description="Reviews code",
                tags=["code"],
                downloads=10,
                latest_version="1.0.0",
            )
        ]
        with patch("initrunner.hub.hub_search", return_value=hub_results):
            result = runner.invoke(app, ["search", "code"])

        assert result.exit_code == 0
        assert "code-reviewer" in result.output

    def test_search_no_results(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        with patch("initrunner.hub.hub_search", return_value=[]):
            result = runner.invoke(app, ["search", "nonexistent"])

        assert result.exit_code == 0
        assert "No packages found" in result.output


class TestCLIInstallHint:
    """Tests for install command post-install hint and list Run column."""

    def test_install_shows_run_hint(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", roles_dir / "registry.json"
        )

        from initrunner.hub import HubPackageInfo

        info = HubPackageInfo(
            owner="user",
            name="test-agent",
            description="Test",
            latest_version="1.0.0",
            versions=["1.0.0"],
        )

        def fake_extract(archive, dest):
            dest.mkdir(parents=True, exist_ok=True)
            m = MagicMock()
            m.name = "test-agent"
            return m

        with (
            patch("initrunner.hub.parse_hub_source", return_value=("user", "test-agent", None)),
            patch("initrunner.hub.hub_resolve", return_value=info),
            patch("initrunner.hub.hub_download", return_value=b"fake-bundle"),
            patch("initrunner.packaging.bundle.extract_bundle", side_effect=fake_extract),
        ):
            result = runner.invoke(app, ["install", "user/test-agent", "--yes"])

        assert result.exit_code == 0
        assert "Run:" in result.output
        assert "initrunner run test-agent" in result.output

    def test_list_shows_run_column(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()
        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "hub:alice/my-agent": {
                            "display_name": "my-agent",
                            "source_type": "hub",
                            "hub_owner": "alice",
                            "hub_name": "my-agent",
                            "hub_version": "1.0.0",
                            "local_path": "hub__alice__my-agent",
                            "installed_at": "2026-03-18T12:00:00",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry._manifest.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry._manifest.MANIFEST_PATH", manifest_path)

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "initrunner run my-agent" in result.output


class TestCLIUpdate:
    def test_update_all_command(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        monkeypatch.setattr(
            "initrunner.registry._manifest.MANIFEST_PATH", tmp_path / "registry.json"
        )

        result = runner.invoke(app, ["update"])
        assert result.exit_code == 0
        assert "No roles installed" in result.output
