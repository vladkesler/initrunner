"""Tests for ``initrunner compose new`` scaffolding."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from initrunner.cli.main import app
from initrunner.services.compose import scaffold_compose_project

runner = CliRunner()


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------


class TestPipelinePattern:
    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        result = scaffold_compose_project("my-proj", output_dir=tmp_path, provider="openai")
        assert result.project_dir == tmp_path / "my-proj"
        assert result.compose_path.exists()
        assert (tmp_path / "my-proj" / "roles").is_dir()
        assert len(result.role_paths) == 3

    def test_compose_yaml_is_valid(self, tmp_path: Path) -> None:
        from initrunner.compose.loader import load_compose

        result = scaffold_compose_project("p", output_dir=tmp_path, provider="openai")
        compose = load_compose(result.compose_path)
        assert compose.metadata.name == "p"
        assert set(compose.spec.services.keys()) == {"step-1", "step-2", "step-3"}

    def test_role_files_are_valid(self, tmp_path: Path) -> None:
        from initrunner.agent.loader import load_role

        result = scaffold_compose_project("p", output_dir=tmp_path, provider="openai")
        for rp in result.role_paths:
            role = load_role(rp)
            assert role.spec.model.provider == "openai"

    def test_default_service_count(self, tmp_path: Path) -> None:
        result = scaffold_compose_project("p", output_dir=tmp_path, provider="openai")
        assert len(result.role_paths) == 3

    def test_custom_service_count(self, tmp_path: Path) -> None:
        result = scaffold_compose_project("p", services=5, output_dir=tmp_path, provider="openai")
        assert len(result.role_paths) == 5
        data = yaml.safe_load(result.compose_path.read_text())
        assert len(data["spec"]["services"]) == 5

    def test_min_services(self, tmp_path: Path) -> None:
        result = scaffold_compose_project("p", services=2, output_dir=tmp_path, provider="openai")
        assert len(result.role_paths) == 2

    def test_below_min_services_errors(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            scaffold_compose_project("p", services=1, output_dir=tmp_path, provider="openai")

    def test_sink_chain(self, tmp_path: Path) -> None:
        result = scaffold_compose_project("p", services=3, output_dir=tmp_path, provider="openai")
        data = yaml.safe_load(result.compose_path.read_text())
        svcs = data["spec"]["services"]
        assert svcs["step-1"]["sink"]["target"] == "step-2"
        assert svcs["step-2"]["sink"]["target"] == "step-3"
        assert "sink" not in svcs["step-3"]


class TestFanOutPattern:
    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        result = scaffold_compose_project(
            "fo", pattern="fan-out", output_dir=tmp_path, provider="openai"
        )
        assert result.compose_path.exists()
        assert len(result.role_paths) == 3

    def test_dispatcher_sinks_to_workers(self, tmp_path: Path) -> None:
        result = scaffold_compose_project(
            "fo", pattern="fan-out", output_dir=tmp_path, provider="openai"
        )
        data = yaml.safe_load(result.compose_path.read_text())
        svcs = data["spec"]["services"]
        assert svcs["dispatcher"]["sink"]["target"] == ["worker-1", "worker-2"]

    def test_compose_yaml_is_valid(self, tmp_path: Path) -> None:
        from initrunner.compose.loader import load_compose

        result = scaffold_compose_project(
            "fo", pattern="fan-out", output_dir=tmp_path, provider="openai"
        )
        compose = load_compose(result.compose_path)
        assert "dispatcher" in compose.spec.services

    def test_custom_service_count(self, tmp_path: Path) -> None:
        result = scaffold_compose_project(
            "fo", pattern="fan-out", services=6, output_dir=tmp_path, provider="openai"
        )
        assert len(result.role_paths) == 6
        data = yaml.safe_load(result.compose_path.read_text())
        assert len(data["spec"]["services"]["dispatcher"]["sink"]["target"]) == 5

    def test_below_min_services_errors(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="at least 3"):
            scaffold_compose_project(
                "fo", pattern="fan-out", services=2, output_dir=tmp_path, provider="openai"
            )


class TestRoutePattern:
    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        result = scaffold_compose_project(
            "rt", pattern="route", output_dir=tmp_path, provider="openai"
        )
        assert result.compose_path.exists()
        assert len(result.role_paths) == 4

    def test_fixed_topology(self, tmp_path: Path) -> None:
        result = scaffold_compose_project(
            "rt", pattern="route", output_dir=tmp_path, provider="openai"
        )
        data = yaml.safe_load(result.compose_path.read_text())
        assert set(data["spec"]["services"].keys()) == {
            "intake",
            "researcher",
            "responder",
            "escalator",
        }

    def test_sense_strategy(self, tmp_path: Path) -> None:
        result = scaffold_compose_project(
            "rt", pattern="route", output_dir=tmp_path, provider="openai"
        )
        data = yaml.safe_load(result.compose_path.read_text())
        sink = data["spec"]["services"]["intake"]["sink"]
        assert sink["strategy"] == "sense"

    def test_specialist_tags(self, tmp_path: Path) -> None:
        from initrunner.agent.loader import load_role

        result = scaffold_compose_project(
            "rt", pattern="route", output_dir=tmp_path, provider="openai"
        )
        roles_dir = result.project_dir / "roles"
        researcher = load_role(roles_dir / "researcher.yaml")
        assert "research" in researcher.metadata.tags

    def test_ignores_custom_service_count(self, tmp_path: Path) -> None:
        """Route has a fixed 4-service topology; service_count is silently ignored."""
        result = scaffold_compose_project(
            "rt", pattern="route", services=5, output_dir=tmp_path, provider="openai"
        )
        assert len(result.role_paths) == 4
        data = yaml.safe_load(result.compose_path.read_text())
        assert set(data["spec"]["services"].keys()) == {
            "intake",
            "researcher",
            "responder",
            "escalator",
        }

    def test_compose_yaml_is_valid(self, tmp_path: Path) -> None:
        from initrunner.compose.loader import load_compose

        result = scaffold_compose_project(
            "rt", pattern="route", output_dir=tmp_path, provider="openai"
        )
        load_compose(result.compose_path)

    def test_role_files_are_valid(self, tmp_path: Path) -> None:
        from initrunner.agent.loader import load_role

        result = scaffold_compose_project(
            "rt", pattern="route", output_dir=tmp_path, provider="openai"
        )
        for rp in result.role_paths:
            load_role(rp)


class TestSharedMemory:
    def test_injects_shared_memory(self, tmp_path: Path) -> None:
        result = scaffold_compose_project(
            "sm", shared_memory=True, output_dir=tmp_path, provider="openai"
        )
        data = yaml.safe_load(result.compose_path.read_text())
        sm = data["spec"]["shared_memory"]
        assert sm["enabled"] is True
        assert sm["store_path"] == ".memory"

    def test_works_with_fan_out(self, tmp_path: Path) -> None:
        result = scaffold_compose_project(
            "sm", pattern="fan-out", shared_memory=True, output_dir=tmp_path, provider="openai"
        )
        data = yaml.safe_load(result.compose_path.read_text())
        assert data["spec"]["shared_memory"]["enabled"] is True
        assert "dispatcher" in data["spec"]["services"]

    def test_works_with_route(self, tmp_path: Path) -> None:
        result = scaffold_compose_project(
            "sm", pattern="route", shared_memory=True, output_dir=tmp_path, provider="openai"
        )
        data = yaml.safe_load(result.compose_path.read_text())
        assert data["spec"]["shared_memory"]["enabled"] is True

    def test_compose_valid_with_shared_memory(self, tmp_path: Path) -> None:
        from initrunner.compose.loader import load_compose

        result = scaffold_compose_project(
            "sm", shared_memory=True, output_dir=tmp_path, provider="openai"
        )
        compose = load_compose(result.compose_path)
        assert compose.spec.shared_memory.enabled is True


class TestOptions:
    def test_provider_propagated(self, tmp_path: Path) -> None:
        result = scaffold_compose_project("p", output_dir=tmp_path, provider="anthropic")
        for rp in result.role_paths:
            data = yaml.safe_load(rp.read_text())
            assert data["spec"]["model"]["provider"] == "anthropic"

    def test_model_propagated(self, tmp_path: Path) -> None:
        result = scaffold_compose_project(
            "p", output_dir=tmp_path, provider="openai", model_name="gpt-4o"
        )
        for rp in result.role_paths:
            data = yaml.safe_load(rp.read_text())
            assert data["spec"]["model"]["name"] == "gpt-4o"

    def test_output_directory(self, tmp_path: Path) -> None:
        subdir = tmp_path / "sub"
        subdir.mkdir()
        result = scaffold_compose_project("p", output_dir=subdir, provider="openai")
        assert result.project_dir == subdir / "p"

    def test_force_overwrites(self, tmp_path: Path) -> None:
        scaffold_compose_project("p", output_dir=tmp_path, provider="openai")
        result = scaffold_compose_project("p", output_dir=tmp_path, provider="openai", force=True)
        assert result.compose_path.exists()

    def test_refuses_overwrite_without_force(self, tmp_path: Path) -> None:
        scaffold_compose_project("p", output_dir=tmp_path, provider="openai")
        with pytest.raises(FileExistsError):
            scaffold_compose_project("p", output_dir=tmp_path, provider="openai")

    def test_invalid_pattern_errors(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unknown pattern"):
            scaffold_compose_project("p", pattern="nope", output_dir=tmp_path, provider="openai")


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestComposeNewCLI:
    def test_list_patterns(self) -> None:
        result = runner.invoke(app, ["compose", "new", "x", "--list-patterns"])
        assert result.exit_code == 0
        assert "chain" in result.output
        assert "fan-out" in result.output
        assert "route" in result.output

    def test_end_to_end(self, tmp_path: Path) -> None:
        with patch("initrunner.agent.loader._load_dotenv"):
            result = runner.invoke(
                app,
                [
                    "compose",
                    "new",
                    "demo",
                    "--output",
                    str(tmp_path),
                    "--provider",
                    "openai",
                ],
            )
        assert result.exit_code == 0
        assert "Created" in result.output
        assert "compose.yaml" in result.output
        assert "Next steps" in result.output

    def test_invalid_pattern_exits_1(self, tmp_path: Path) -> None:
        with patch("initrunner.agent.loader._load_dotenv"):
            result = runner.invoke(
                app,
                [
                    "compose",
                    "new",
                    "demo",
                    "--pattern",
                    "bogus",
                    "--output",
                    str(tmp_path),
                    "--provider",
                    "openai",
                ],
            )
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_overwrite_refused(self, tmp_path: Path) -> None:
        (tmp_path / "demo").mkdir()
        (tmp_path / "demo" / "compose.yaml").write_text("existing")
        with patch("initrunner.agent.loader._load_dotenv"):
            result = runner.invoke(
                app,
                [
                    "compose",
                    "new",
                    "demo",
                    "--output",
                    str(tmp_path),
                    "--provider",
                    "openai",
                ],
            )
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_shared_memory_flag(self, tmp_path: Path) -> None:
        with patch("initrunner.agent.loader._load_dotenv"):
            result = runner.invoke(
                app,
                [
                    "compose",
                    "new",
                    "demo",
                    "--shared-memory",
                    "--output",
                    str(tmp_path),
                    "--provider",
                    "openai",
                ],
            )
        assert result.exit_code == 0
        data = yaml.safe_load((tmp_path / "demo" / "compose.yaml").read_text())
        assert data["spec"]["shared_memory"]["enabled"] is True
