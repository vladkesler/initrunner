"""Tests for resolve_role_path() and resolve_role_paths()."""

from __future__ import annotations

from pathlib import Path

import click.exceptions
import pytest

from initrunner.cli._helpers import resolve_role_path, resolve_role_paths

# ---------------------------------------------------------------------------
# resolve_role_path
# ---------------------------------------------------------------------------


class TestResolveRolePath:
    def test_file_path_returned_unchanged(self, tmp_path: Path) -> None:
        f = tmp_path / "my-agent.yaml"
        f.write_text("apiVersion: initrunner/v1\nkind: Agent\n")
        assert resolve_role_path(f) == f

    def test_dir_with_role_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "role.yaml").write_text("apiVersion: initrunner/v1\nkind: Agent\n")
        assert resolve_role_path(tmp_path) == tmp_path / "role.yaml"

    def test_dir_with_role_yaml_preferred_over_others(self, tmp_path: Path) -> None:
        """role.yaml wins even if other Agent YAMLs exist."""
        (tmp_path / "role.yaml").write_text("apiVersion: initrunner/v1\nkind: Agent\n")
        (tmp_path / "other.yaml").write_text("apiVersion: initrunner/v1\nkind: Agent\n")
        assert resolve_role_path(tmp_path) == tmp_path / "role.yaml"

    def test_dir_with_single_agent_yaml(self, tmp_path: Path) -> None:
        agent = tmp_path / "pdf-agent.yaml"
        agent.write_text("apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: pdf\n")
        assert resolve_role_path(tmp_path) == agent

    def test_dir_with_single_team_yaml(self, tmp_path: Path) -> None:
        team = tmp_path / "my-team.yml"
        team.write_text("apiVersion: initrunner/v1\nkind: Team\n")
        assert resolve_role_path(tmp_path) == team

    def test_dir_ignores_non_initrunner_yaml(self, tmp_path: Path) -> None:
        """Non-initrunner YAML files (e.g. docker-compose) are not candidates."""
        agent = tmp_path / "coordinator.yaml"
        agent.write_text("apiVersion: initrunner/v1\nkind: Agent\n")
        (tmp_path / "docker-compose.yaml").write_text("version: '3'\nservices:\n  web:\n")
        assert resolve_role_path(tmp_path) == agent

    def test_dir_ignores_invalid_yaml(self, tmp_path: Path) -> None:
        agent = tmp_path / "agent.yaml"
        agent.write_text("apiVersion: initrunner/v1\nkind: Agent\n")
        (tmp_path / "broken.yaml").write_text("{{invalid yaml!!")
        assert resolve_role_path(tmp_path) == agent

    def test_dir_no_candidates_exits(self, tmp_path: Path) -> None:
        (tmp_path / "readme.md").write_text("# hello")
        with pytest.raises(click.exceptions.Exit):
            resolve_role_path(tmp_path)

    def test_dir_empty_exits(self, tmp_path: Path) -> None:
        with pytest.raises(click.exceptions.Exit):
            resolve_role_path(tmp_path)

    def test_dir_multiple_candidates_exits(self, tmp_path: Path) -> None:
        (tmp_path / "a.yaml").write_text("apiVersion: initrunner/v1\nkind: Agent\n")
        (tmp_path / "b.yaml").write_text("apiVersion: initrunner/v1\nkind: Team\n")
        with pytest.raises(click.exceptions.Exit):
            resolve_role_path(tmp_path)

    def test_nonexistent_path_exits(self, tmp_path: Path) -> None:
        with pytest.raises(click.exceptions.Exit):
            resolve_role_path(tmp_path / "no-such-dir")

    def test_dir_only_scans_top_level(self, tmp_path: Path) -> None:
        """Nested YAML files should not be discovered."""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.yaml").write_text("apiVersion: initrunner/v1\nkind: Agent\n")
        with pytest.raises(click.exceptions.Exit):
            resolve_role_path(tmp_path)


# ---------------------------------------------------------------------------
# resolve_role_paths
# ---------------------------------------------------------------------------


class TestResolveRolePaths:
    def test_mixed_files_and_dirs(self, tmp_path: Path) -> None:
        # A file
        f = tmp_path / "direct.yaml"
        f.write_text("apiVersion: initrunner/v1\nkind: Agent\n")
        # A directory with role.yaml
        d = tmp_path / "mydir"
        d.mkdir()
        (d / "role.yaml").write_text("apiVersion: initrunner/v1\nkind: Agent\n")

        result = resolve_role_paths([f, d])
        assert result == [f, d / "role.yaml"]

    def test_empty_list(self) -> None:
        assert resolve_role_paths([]) == []
