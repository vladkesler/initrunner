"""Tests for ``initrunner flow new`` scaffolding."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from initrunner.cli.main import app
from initrunner.services.flow import scaffold_flow_project

runner = CliRunner()


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------


class TestPipelinePattern:
    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        result = scaffold_flow_project("my-proj", output_dir=tmp_path, provider="openai")
        assert result.project_dir == tmp_path / "my-proj"
        assert result.flow_path.exists()
        assert (tmp_path / "my-proj" / "roles").is_dir()
        assert len(result.role_paths) == 3

    def test_flow_yaml_is_valid(self, tmp_path: Path) -> None:
        from initrunner.flow.loader import load_flow

        result = scaffold_flow_project("p", output_dir=tmp_path, provider="openai")
        flow = load_flow(result.flow_path)
        assert flow.metadata.name == "p"
        assert set(flow.spec.agents.keys()) == {"step-1", "step-2", "step-3"}

    def test_role_files_are_valid(self, tmp_path: Path) -> None:
        from initrunner.agent.loader import load_role

        result = scaffold_flow_project("p", output_dir=tmp_path, provider="openai")
        for rp in result.role_paths:
            role = load_role(rp)
            assert role.spec.model is not None
            assert role.spec.model.provider == "openai"

    def test_default_agent_count(self, tmp_path: Path) -> None:
        result = scaffold_flow_project("p", output_dir=tmp_path, provider="openai")
        assert len(result.role_paths) == 3

    def test_custom_agent_count(self, tmp_path: Path) -> None:
        result = scaffold_flow_project("p", agents=5, output_dir=tmp_path, provider="openai")
        assert len(result.role_paths) == 5
        data = yaml.safe_load(result.flow_path.read_text())
        assert len(data["spec"]["agents"]) == 5

    def test_min_agents(self, tmp_path: Path) -> None:
        result = scaffold_flow_project("p", agents=2, output_dir=tmp_path, provider="openai")
        assert len(result.role_paths) == 2

    def test_below_min_agents_errors(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            scaffold_flow_project("p", agents=1, output_dir=tmp_path, provider="openai")

    def test_sink_chain(self, tmp_path: Path) -> None:
        result = scaffold_flow_project("p", agents=3, output_dir=tmp_path, provider="openai")
        data = yaml.safe_load(result.flow_path.read_text())
        agents = data["spec"]["agents"]
        assert agents["step-1"]["sink"]["target"] == "step-2"
        assert agents["step-2"]["sink"]["target"] == "step-3"
        assert "sink" not in agents["step-3"]


class TestFanOutPattern:
    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        result = scaffold_flow_project(
            "fo", pattern="fan-out", output_dir=tmp_path, provider="openai"
        )
        assert result.flow_path.exists()
        assert len(result.role_paths) == 3

    def test_dispatcher_sinks_to_workers(self, tmp_path: Path) -> None:
        result = scaffold_flow_project(
            "fo", pattern="fan-out", output_dir=tmp_path, provider="openai"
        )
        data = yaml.safe_load(result.flow_path.read_text())
        agents = data["spec"]["agents"]
        assert agents["dispatcher"]["sink"]["target"] == ["worker-1", "worker-2"]

    def test_flow_yaml_is_valid(self, tmp_path: Path) -> None:
        from initrunner.flow.loader import load_flow

        result = scaffold_flow_project(
            "fo", pattern="fan-out", output_dir=tmp_path, provider="openai"
        )
        flow = load_flow(result.flow_path)
        assert "dispatcher" in flow.spec.agents

    def test_custom_agent_count(self, tmp_path: Path) -> None:
        result = scaffold_flow_project(
            "fo", pattern="fan-out", agents=6, output_dir=tmp_path, provider="openai"
        )
        assert len(result.role_paths) == 6
        data = yaml.safe_load(result.flow_path.read_text())
        assert len(data["spec"]["agents"]["dispatcher"]["sink"]["target"]) == 5

    def test_below_min_agents_errors(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="at least 3"):
            scaffold_flow_project(
                "fo", pattern="fan-out", agents=2, output_dir=tmp_path, provider="openai"
            )


class TestRoutePattern:
    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        result = scaffold_flow_project(
            "rt", pattern="route", agents=4, output_dir=tmp_path, provider="openai"
        )
        assert result.flow_path.exists()
        assert len(result.role_paths) == 4

    def test_default_three_agents(self, tmp_path: Path) -> None:
        result = scaffold_flow_project(
            "rt", pattern="route", output_dir=tmp_path, provider="openai"
        )
        data = yaml.safe_load(result.flow_path.read_text())
        assert set(data["spec"]["agents"].keys()) == {
            "intake",
            "researcher",
            "responder",
        }

    def test_four_agents(self, tmp_path: Path) -> None:
        result = scaffold_flow_project(
            "rt", pattern="route", agents=4, output_dir=tmp_path, provider="openai"
        )
        data = yaml.safe_load(result.flow_path.read_text())
        assert set(data["spec"]["agents"].keys()) == {
            "intake",
            "researcher",
            "responder",
            "escalator",
        }

    def test_sense_strategy(self, tmp_path: Path) -> None:
        result = scaffold_flow_project(
            "rt", pattern="route", output_dir=tmp_path, provider="openai"
        )
        data = yaml.safe_load(result.flow_path.read_text())
        sink = data["spec"]["agents"]["intake"]["sink"]
        assert sink["strategy"] == "sense"

    def test_specialist_tags(self, tmp_path: Path) -> None:
        from initrunner.agent.loader import load_role

        result = scaffold_flow_project(
            "rt", pattern="route", output_dir=tmp_path, provider="openai"
        )
        roles_dir = result.project_dir / "roles"
        researcher = load_role(roles_dir / "researcher.yaml")
        assert "research" in researcher.metadata.tags

    def test_variable_agent_count(self, tmp_path: Path) -> None:
        """Route supports variable specialist count (3-10 agents)."""
        result = scaffold_flow_project(
            "rt", pattern="route", agents=5, output_dir=tmp_path, provider="openai"
        )
        assert len(result.role_paths) == 5
        data = yaml.safe_load(result.flow_path.read_text())
        assert "intake" in data["spec"]["agents"]
        # 4 specialist targets
        sink = data["spec"]["agents"]["intake"]["sink"]
        assert len(sink["target"]) == 4

    def test_flow_yaml_is_valid(self, tmp_path: Path) -> None:
        from initrunner.flow.loader import load_flow

        result = scaffold_flow_project(
            "rt", pattern="route", output_dir=tmp_path, provider="openai"
        )
        load_flow(result.flow_path)

    def test_role_files_are_valid(self, tmp_path: Path) -> None:
        from initrunner.agent.loader import load_role

        result = scaffold_flow_project(
            "rt", pattern="route", output_dir=tmp_path, provider="openai"
        )
        for rp in result.role_paths:
            load_role(rp)


class TestSharedMemory:
    def test_injects_shared_memory(self, tmp_path: Path) -> None:
        result = scaffold_flow_project(
            "sm", shared_memory=True, output_dir=tmp_path, provider="openai"
        )
        data = yaml.safe_load(result.flow_path.read_text())
        sm = data["spec"]["shared_memory"]
        assert sm["enabled"] is True
        assert sm["store_path"] == ".memory"

    def test_works_with_fan_out(self, tmp_path: Path) -> None:
        result = scaffold_flow_project(
            "sm", pattern="fan-out", shared_memory=True, output_dir=tmp_path, provider="openai"
        )
        data = yaml.safe_load(result.flow_path.read_text())
        assert data["spec"]["shared_memory"]["enabled"] is True
        assert "dispatcher" in data["spec"]["agents"]

    def test_works_with_route(self, tmp_path: Path) -> None:
        result = scaffold_flow_project(
            "sm", pattern="route", shared_memory=True, output_dir=tmp_path, provider="openai"
        )
        data = yaml.safe_load(result.flow_path.read_text())
        assert data["spec"]["shared_memory"]["enabled"] is True

    def test_flow_valid_with_shared_memory(self, tmp_path: Path) -> None:
        from initrunner.flow.loader import load_flow

        result = scaffold_flow_project(
            "sm", shared_memory=True, output_dir=tmp_path, provider="openai"
        )
        flow = load_flow(result.flow_path)
        assert flow.spec.shared_memory.enabled is True


class TestOptions:
    def test_provider_propagated(self, tmp_path: Path) -> None:
        result = scaffold_flow_project("p", output_dir=tmp_path, provider="anthropic")
        for rp in result.role_paths:
            data = yaml.safe_load(rp.read_text())
            assert data["spec"]["model"]["provider"] == "anthropic"

    def test_model_propagated(self, tmp_path: Path) -> None:
        result = scaffold_flow_project(
            "p", output_dir=tmp_path, provider="openai", model_name="gpt-4o"
        )
        for rp in result.role_paths:
            data = yaml.safe_load(rp.read_text())
            assert data["spec"]["model"]["name"] == "gpt-4o"

    def test_output_directory(self, tmp_path: Path) -> None:
        subdir = tmp_path / "sub"
        subdir.mkdir()
        result = scaffold_flow_project("p", output_dir=subdir, provider="openai")
        assert result.project_dir == subdir / "p"

    def test_force_overwrites(self, tmp_path: Path) -> None:
        scaffold_flow_project("p", output_dir=tmp_path, provider="openai")
        result = scaffold_flow_project("p", output_dir=tmp_path, provider="openai", force=True)
        assert result.flow_path.exists()

    def test_refuses_overwrite_without_force(self, tmp_path: Path) -> None:
        scaffold_flow_project("p", output_dir=tmp_path, provider="openai")
        with pytest.raises(FileExistsError):
            scaffold_flow_project("p", output_dir=tmp_path, provider="openai")

    def test_invalid_pattern_errors(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unknown pattern"):
            scaffold_flow_project("p", pattern="nope", output_dir=tmp_path, provider="openai")


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestFlowNewCLI:
    def test_list_patterns(self) -> None:
        result = runner.invoke(app, ["flow", "new", "x", "--list-patterns"])
        assert result.exit_code == 0
        assert "chain" in result.output
        assert "fan-out" in result.output
        assert "route" in result.output

    def test_end_to_end(self, tmp_path: Path) -> None:
        with patch("initrunner.agent.loader._load_dotenv"):
            result = runner.invoke(
                app,
                [
                    "flow",
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
        assert "flow.yaml" in result.output
        assert "Next steps" in result.output

    def test_invalid_pattern_exits_1(self, tmp_path: Path) -> None:
        with patch("initrunner.agent.loader._load_dotenv"):
            result = runner.invoke(
                app,
                [
                    "flow",
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
        (tmp_path / "demo" / "flow.yaml").write_text("existing")
        with patch("initrunner.agent.loader._load_dotenv"):
            result = runner.invoke(
                app,
                [
                    "flow",
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
                    "flow",
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
        data = yaml.safe_load((tmp_path / "demo" / "flow.yaml").read_text())
        assert data["spec"]["shared_memory"]["enabled"] is True
