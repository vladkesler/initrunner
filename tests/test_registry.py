"""Tests for the role registry."""

import hashlib
import json
import textwrap
from unittest.mock import patch

import pytest

from initrunner.registry import (
    IndexEntry,
    NetworkError,
    RegistryError,
    RoleExistsError,
    RoleNotFoundError,
    _role_info_from_definition,
    _validate_yaml_content,
    check_dependencies,
    install_role,
    list_installed,
    load_manifest,
    resolve_source,
    save_manifest,
    search_index,
    uninstall_role,
    update_all,
    update_role,
)

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
        name: gpt-4o-mini
""")

VALID_ROLE_WITH_TOOLS_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: code-reviewer
      description: Reviews code
      author: jcdenton
    spec:
      role: You review code.
      model:
        provider: openai
        name: gpt-4o-mini
      tools:
        - type: filesystem
          root_path: /src
""")

VALID_ROLE_WITH_DEPS_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: dep-agent
      description: Agent with deps
      dependencies:
        - ffmpeg
        - python>=3.11
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-4o-mini
""")


# ---------------------------------------------------------------------------
# Source identifier parsing
# ---------------------------------------------------------------------------


class TestResolveSource:
    def test_user_repo(self):
        result = resolve_source("user/repo")
        assert result.owner == "user"
        assert result.repo == "repo"
        assert result.path == "role.yaml"
        assert result.ref == "main"
        assert "raw.githubusercontent.com/user/repo/main/role.yaml" in result.raw_url

    def test_user_repo_with_path(self):
        result = resolve_source("user/repo:path/to/role.yaml")
        assert result.owner == "user"
        assert result.repo == "repo"
        assert result.path == "path/to/role.yaml"
        assert result.ref == "main"

    def test_user_repo_with_ref(self):
        result = resolve_source("user/repo@v1.0")
        assert result.owner == "user"
        assert result.repo == "repo"
        assert result.path == "role.yaml"
        assert result.ref == "v1.0"

    def test_user_repo_with_path_and_ref(self):
        result = resolve_source("user/repo:path/role.yaml@v1.0")
        assert result.owner == "user"
        assert result.repo == "repo"
        assert result.path == "path/role.yaml"
        assert result.ref == "v1.0"

    def test_user_repo_with_sha_ref(self):
        result = resolve_source("user/repo@abc123f")
        assert result.ref == "abc123f"

    def test_full_repo(self):
        result = resolve_source("user/repo")
        assert result.full_repo == "user/repo"

    def test_bare_name_calls_index(self):
        mock_entries = [
            IndexEntry(
                name="my-role",
                description="A role",
                author="user",
                source="user/repo:roles/my-role.yaml",
                tags=[],
            )
        ]
        with patch("initrunner.registry._fetch_index", return_value=mock_entries):
            result = resolve_source("my-role")
        assert result.owner == "user"
        assert result.repo == "repo"
        assert result.path == "roles/my-role.yaml"

    def test_bare_name_not_found(self):
        with patch("initrunner.registry._fetch_index", return_value=[]):
            with pytest.raises(RoleNotFoundError, match="not found in community index"):
                resolve_source("nonexistent")

    def test_owner_with_dots_and_hyphens(self):
        result = resolve_source("my-user.name/my-repo.name")
        assert result.owner == "my-user.name"
        assert result.repo == "my-repo.name"


# ---------------------------------------------------------------------------
# Manifest CRUD
# ---------------------------------------------------------------------------


class TestManifest:
    def test_load_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")
        data = load_manifest()
        assert data == {"roles": {}}

    def test_save_and_load(self, tmp_path, monkeypatch):
        manifest_path = tmp_path / "roles" / "registry.json"
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", tmp_path / "roles")

        data = {"roles": {"test": {"source_url": "https://example.com", "ref": "main"}}}
        save_manifest(data)

        loaded = load_manifest()
        assert loaded == data

    def test_load_corrupt_json(self, tmp_path, monkeypatch):
        manifest_path = tmp_path / "registry.json"
        manifest_path.write_text("not json{{{")
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        data = load_manifest()
        assert data == {"roles": {}}

    def test_load_missing_roles_key(self, tmp_path, monkeypatch):
        manifest_path = tmp_path / "registry.json"
        manifest_path.write_text("{}")
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        data = load_manifest()
        assert "roles" in data


# ---------------------------------------------------------------------------
# YAML validation
# ---------------------------------------------------------------------------


class TestValidateYaml:
    def test_valid_role(self):
        role = _validate_yaml_content(VALID_ROLE_YAML)
        assert role.metadata.name == "test-agent"

    def test_invalid_yaml(self):
        with pytest.raises(RegistryError, match="not valid YAML"):
            _validate_yaml_content("{{{{invalid yaml")

    def test_not_a_mapping(self):
        with pytest.raises(RegistryError, match="expected YAML mapping"):
            _validate_yaml_content("- just\n- a\n- list")

    def test_invalid_role_schema(self):
        with pytest.raises(RegistryError, match="not a valid InitRunner role"):
            _validate_yaml_content("apiVersion: wrong\nkind: Agent\n")


# ---------------------------------------------------------------------------
# Dependency checking
# ---------------------------------------------------------------------------


class TestCheckDependencies:
    def test_no_deps(self):
        role = _validate_yaml_content(VALID_ROLE_YAML)
        warnings = check_dependencies(role)
        assert warnings == []

    def test_missing_binary(self):
        role = _validate_yaml_content(VALID_ROLE_WITH_DEPS_YAML)
        with patch("shutil.which", return_value=None):
            warnings = check_dependencies(role)
        assert any("ffmpeg" in w for w in warnings)

    def test_binary_found(self):
        role = _validate_yaml_content(VALID_ROLE_WITH_DEPS_YAML)
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            warnings = check_dependencies(role)
        binary_warnings = [w for w in warnings if "ffmpeg" in w]
        assert binary_warnings == []

    def test_python_version_satisfied(self):
        role = _validate_yaml_content(VALID_ROLE_WITH_DEPS_YAML)
        # python>=3.11 should be satisfied on 3.13+
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            warnings = check_dependencies(role)
        python_warnings = [w for w in warnings if "Python" in w]
        assert python_warnings == []


# ---------------------------------------------------------------------------
# Role info extraction
# ---------------------------------------------------------------------------


class TestRoleInfo:
    def test_basic_info(self):
        role = _validate_yaml_content(VALID_ROLE_YAML)
        info = _role_info_from_definition(role)
        assert info.name == "test-agent"
        assert info.description == "A test agent"
        assert info.author == "testuser"
        assert info.provider == "openai"
        assert info.model == "gpt-4o-mini"
        assert info.tools == []
        assert info.has_triggers is False
        assert info.has_ingestion is False
        assert info.has_memory is False

    def test_info_with_tools(self):
        role = _validate_yaml_content(VALID_ROLE_WITH_TOOLS_YAML)
        info = _role_info_from_definition(role)
        assert info.tools == ["filesystem"]


# ---------------------------------------------------------------------------
# Install flow
# ---------------------------------------------------------------------------


class TestInstallRole:
    def test_install_success(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", roles_dir / "registry.json")

        with (
            patch("initrunner.registry.download_yaml", return_value=VALID_ROLE_YAML),
            patch("initrunner.registry.fetch_commit_sha", return_value="abc123"),
        ):
            path = install_role("user/repo", yes=True)

        assert path.exists()
        assert path.name == "user__repo__test-agent.yaml"
        assert path.read_text() == VALID_ROLE_YAML

        # Check manifest
        manifest = json.loads((roles_dir / "registry.json").read_text())
        assert "test-agent" in manifest["roles"]
        entry = manifest["roles"]["test-agent"]
        assert entry["repo"] == "user/repo"
        assert entry["commit_sha"] == "abc123"
        assert entry["sha256"] == hashlib.sha256(VALID_ROLE_YAML.encode()).hexdigest()

    def test_install_collision_without_force(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)
        (roles_dir / "user__repo__test-agent.yaml").write_text("existing")
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", roles_dir / "registry.json")

        with patch("initrunner.registry.download_yaml", return_value=VALID_ROLE_YAML):
            with pytest.raises(RoleExistsError, match="already installed"):
                install_role("user/repo", yes=True)

    def test_install_collision_with_force(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)
        (roles_dir / "user__repo__test-agent.yaml").write_text("old")
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", roles_dir / "registry.json")

        with (
            patch("initrunner.registry.download_yaml", return_value=VALID_ROLE_YAML),
            patch("initrunner.registry.fetch_commit_sha", return_value="abc123"),
        ):
            path = install_role("user/repo", force=True, yes=True)

        assert path.read_text() == VALID_ROLE_YAML

    def test_install_invalid_yaml(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", roles_dir / "registry.json")

        with patch("initrunner.registry.download_yaml", return_value="not: valid: role"):
            with pytest.raises(RegistryError):
                install_role("user/repo", yes=True)

    def test_install_network_error(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)

        with patch(
            "initrunner.registry.download_yaml",
            side_effect=NetworkError("Connection failed"),
        ):
            with pytest.raises(NetworkError):
                install_role("user/repo", yes=True)

    def test_install_sha_fetch_failure_still_installs(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", roles_dir / "registry.json")

        with (
            patch("initrunner.registry.download_yaml", return_value=VALID_ROLE_YAML),
            patch(
                "initrunner.registry.fetch_commit_sha",
                side_effect=NetworkError("rate limited"),
            ),
        ):
            path = install_role("user/repo", yes=True)

        assert path.exists()
        manifest = json.loads((roles_dir / "registry.json").read_text())
        assert manifest["roles"]["test-agent"]["commit_sha"] == ""


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------


class TestUninstallRole:
    def test_uninstall_success(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)
        role_file = roles_dir / "user__repo__test-agent.yaml"
        role_file.write_text(VALID_ROLE_YAML)

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

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        uninstall_role("test-agent")

        assert not role_file.exists()
        manifest = json.loads(manifest_path.read_text())
        assert "test-agent" not in manifest["roles"]

    def test_uninstall_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")
        with pytest.raises(RoleNotFoundError, match="not installed"):
            uninstall_role("nonexistent")


# ---------------------------------------------------------------------------
# List installed
# ---------------------------------------------------------------------------


class TestListInstalled:
    def test_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")
        assert list_installed() == []

    def test_with_roles(self, tmp_path, monkeypatch):
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

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        roles = list_installed()
        assert len(roles) == 1
        assert roles[0].name == "test-agent"
        assert roles[0].repo == "user/repo"


# ---------------------------------------------------------------------------
# Search index
# ---------------------------------------------------------------------------


class TestSearchIndex:
    def _entry(self, name="role", desc="", author="a", source="a/b", tags=None):
        return IndexEntry(
            name=name, description=desc, author=author, source=source, tags=tags or []
        )

    def test_search_by_name(self):
        entries = [
            self._entry(name="code-reviewer", desc="Reviews code", tags=["code"]),
            self._entry(name="summarizer", desc="Summarizes text", author="b", source="b/c"),
        ]
        with patch("initrunner.registry._fetch_index", return_value=entries):
            results = search_index("code")
        assert len(results) == 1
        assert results[0].name == "code-reviewer"

    def test_search_by_description(self):
        entries = [self._entry(name="summarizer", desc="Summarizes text")]
        with patch("initrunner.registry._fetch_index", return_value=entries):
            results = search_index("text")
        assert len(results) == 1

    def test_search_by_tag(self):
        entries = [self._entry(name="reviewer", desc="Reviews", tags=["code", "review"])]
        with patch("initrunner.registry._fetch_index", return_value=entries):
            results = search_index("review")
        assert len(results) == 1

    def test_search_no_results(self):
        entries = [self._entry(name="something", desc="Something")]
        with patch("initrunner.registry._fetch_index", return_value=entries):
            results = search_index("nonexistent")
        assert results == []

    def test_search_case_insensitive(self):
        entries = [self._entry(name="Code-Reviewer", desc="Reviews code")]
        with patch("initrunner.registry._fetch_index", return_value=entries):
            results = search_index("code")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


class TestUpdateRole:
    def test_update_changed(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)
        role_file = roles_dir / "user__repo__test-agent.yaml"
        role_file.write_text("old content")

        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "test-agent": {
                            "source_url": "https://raw.githubusercontent.com/user/repo/main/role.yaml",
                            "repo": "user/repo",
                            "ref": "main",
                            "commit_sha": "old_sha",
                            "local_path": "user__repo__test-agent.yaml",
                            "sha256": "oldhash",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        with (
            patch("initrunner.registry.fetch_commit_sha", return_value="new_sha"),
            patch("initrunner.registry.download_yaml", return_value=VALID_ROLE_YAML),
        ):
            result = update_role("test-agent")

        assert result.updated is True
        assert result.old_sha == "old_sha"
        assert result.new_sha == "new_sha"
        assert result.message == "Updated."

    def test_update_unchanged(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)
        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "test-agent": {
                            "source_url": "https://example.com",
                            "repo": "user/repo",
                            "ref": "main",
                            "commit_sha": "same_sha",
                            "local_path": "user__repo__test-agent.yaml",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        with patch("initrunner.registry.fetch_commit_sha", return_value="same_sha"):
            result = update_role("test-agent")

        assert result.updated is False
        assert "up to date" in result.message

    def test_update_pinned_tag(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)
        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "test-agent": {
                            "source_url": "https://example.com",
                            "repo": "user/repo",
                            "ref": "v1.0",
                            "commit_sha": "sha",
                            "local_path": "user__repo__test-agent.yaml",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        result = update_role("test-agent")
        assert result.updated is False
        assert "immutable" in result.message

    def test_update_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")
        with pytest.raises(RoleNotFoundError, match="not installed"):
            update_role("nonexistent")


class TestUpdateAll:
    def test_update_all_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")
        results = update_all()
        assert results == []

    def test_update_all_multiple(self, tmp_path, monkeypatch):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)
        (roles_dir / "a__b__role-a.yaml").write_text("old")
        (roles_dir / "c__d__role-b.yaml").write_text("old")

        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "role-a": {
                            "source_url": "https://example.com/a",
                            "repo": "a/b",
                            "ref": "main",
                            "commit_sha": "old_a",
                            "local_path": "a__b__role-a.yaml",
                        },
                        "role-b": {
                            "source_url": "https://example.com/b",
                            "repo": "c/d",
                            "ref": "main",
                            "commit_sha": "old_b",
                            "local_path": "c__d__role-b.yaml",
                        },
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        with (
            patch("initrunner.registry.fetch_commit_sha", return_value="old_a"),
            patch("initrunner.registry.download_yaml", return_value=VALID_ROLE_YAML),
        ):
            results = update_all()

        assert len(results) == 2


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


class TestCLIInstall:
    def test_install_command(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", roles_dir / "registry.json")

        with (
            patch("initrunner.registry.download_yaml", return_value=VALID_ROLE_YAML),
            patch("initrunner.registry.fetch_commit_sha", return_value="abc123"),
        ):
            result = runner.invoke(app, ["install", "user/repo", "--yes"])

        assert result.exit_code == 0
        assert "Installed" in result.output

    def test_install_not_found(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()

        with patch(
            "initrunner.registry.download_yaml",
            side_effect=RoleNotFoundError("Not found"),
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

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        result = runner.invoke(app, ["uninstall", "test-agent"])
        assert result.exit_code == 0
        assert "Uninstalled" in result.output

    def test_uninstall_not_installed(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")

        result = runner.invoke(app, ["uninstall", "nonexistent"])
        assert result.exit_code == 1


class TestCLIList:
    def test_list_empty(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")

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

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "test-agent" in result.output


class TestCLISearch:
    def test_search_command(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        entries = [
            IndexEntry(
                name="code-reviewer",
                description="Reviews code",
                author="test",
                source="test/repo",
                tags=["code"],
            )
        ]
        with patch("initrunner.registry._fetch_index", return_value=entries):
            result = runner.invoke(app, ["search", "code"])

        assert result.exit_code == 0
        assert "code-reviewer" in result.output

    def test_search_no_results(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        with patch("initrunner.registry._fetch_index", return_value=[]):
            result = runner.invoke(app, ["search", "nonexistent"])

        assert result.exit_code == 0
        assert "No roles found" in result.output


class TestCLIUpdate:
    def test_update_all_command(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", tmp_path / "registry.json")

        result = runner.invoke(app, ["update"])
        assert result.exit_code == 0
        assert "No roles installed" in result.output


# ---------------------------------------------------------------------------
# Schema extension
# ---------------------------------------------------------------------------


class TestSchemaExtension:
    def test_author_field(self):
        role = _validate_yaml_content(VALID_ROLE_YAML)
        assert role.metadata.author == "testuser"

    def test_version_field(self):
        role = _validate_yaml_content(VALID_ROLE_YAML)
        assert role.metadata.version == "1.0.0"

    def test_dependencies_field(self):
        role = _validate_yaml_content(VALID_ROLE_WITH_DEPS_YAML)
        assert role.metadata.dependencies == ["ffmpeg", "python>=3.11"]

    def test_backwards_compatible(self):
        """Existing roles without new fields should still validate."""
        yaml_content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: old-agent
            spec:
              role: You are helpful.
              model:
                provider: openai
                name: gpt-4o-mini
        """)
        role = _validate_yaml_content(yaml_content)
        assert role.metadata.author == ""
        assert role.metadata.version == ""
        assert role.metadata.dependencies == []
