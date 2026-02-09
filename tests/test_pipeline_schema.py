"""Tests for pipeline schema and loader."""

import textwrap

import pytest
from pydantic import ValidationError

from initrunner.pipeline.loader import PipelineLoadError, load_pipeline
from initrunner.pipeline.schema import (
    PipelineDefinition,
    PipelineSpec,
    PipelineStep,
)


def _minimal_pipeline_data() -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Pipeline",
        "metadata": {"name": "test-pipeline"},
        "spec": {
            "steps": [
                {
                    "name": "step1",
                    "role_file": "./roles/agent.yaml",
                    "prompt": "Do something",
                }
            ]
        },
    }


class TestPipelineStep:
    def test_defaults(self):
        s = PipelineStep(name="step1", role_file="a.yaml", prompt="hello")
        assert s.mode == "inline"
        assert s.depends_on == []
        assert s.timeout_seconds == 300
        assert s.retry_count == 0
        assert s.output_format == "text"
        assert s.condition is None
        assert s.headers_env == {}

    def test_mcp_step(self):
        s = PipelineStep(
            name="remote",
            url="http://agent:8000",
            mode="mcp",
            prompt="hello",
        )
        assert s.mode == "mcp"
        assert s.url == "http://agent:8000"

    def test_json_output_format(self):
        s = PipelineStep(
            name="step1",
            role_file="a.yaml",
            prompt="hello",
            output_format="json",
        )
        assert s.output_format == "json"


class TestPipelineSpec:
    def test_valid_simple(self):
        spec = PipelineSpec(steps=[PipelineStep(name="step1", role_file="a.yaml", prompt="hello")])
        assert len(spec.steps) == 1
        assert spec.error_strategy == "fail-fast"
        assert spec.max_parallel == 4

    def test_valid_with_dependencies(self):
        spec = PipelineSpec(
            steps=[
                PipelineStep(name="a", role_file="a.yaml", prompt="hello"),
                PipelineStep(name="b", role_file="b.yaml", prompt="hello", depends_on=["a"]),
            ]
        )
        assert len(spec.steps) == 2

    def test_duplicate_step_names(self):
        with pytest.raises(ValidationError, match="Duplicate step name"):
            PipelineSpec(
                steps=[
                    PipelineStep(name="a", role_file="a.yaml", prompt="hello"),
                    PipelineStep(name="a", role_file="b.yaml", prompt="world"),
                ]
            )

    def test_unknown_dependency(self):
        with pytest.raises(ValidationError, match="unknown step"):
            PipelineSpec(
                steps=[
                    PipelineStep(
                        name="a",
                        role_file="a.yaml",
                        prompt="hello",
                        depends_on=["nonexistent"],
                    )
                ]
            )

    def test_cycle_detection_simple(self):
        with pytest.raises(ValidationError, match="cycle"):
            PipelineSpec(
                steps=[
                    PipelineStep(name="a", role_file="a.yaml", prompt="p", depends_on=["b"]),
                    PipelineStep(name="b", role_file="b.yaml", prompt="p", depends_on=["a"]),
                ]
            )

    def test_cycle_detection_three_nodes(self):
        with pytest.raises(ValidationError, match="cycle"):
            PipelineSpec(
                steps=[
                    PipelineStep(name="a", role_file="a.yaml", prompt="p", depends_on=["c"]),
                    PipelineStep(name="b", role_file="b.yaml", prompt="p", depends_on=["a"]),
                    PipelineStep(name="c", role_file="c.yaml", prompt="p", depends_on=["b"]),
                ]
            )

    def test_inline_requires_role_file(self):
        with pytest.raises(ValidationError, match="role_file"):
            PipelineSpec(steps=[PipelineStep(name="a", mode="inline", prompt="hello")])

    def test_mcp_requires_url(self):
        with pytest.raises(ValidationError, match="url"):
            PipelineSpec(steps=[PipelineStep(name="a", mode="mcp", prompt="hello")])

    def test_empty_steps(self):
        with pytest.raises(ValidationError):
            PipelineSpec(steps=[])

    def test_mixed_modes(self):
        spec = PipelineSpec(
            steps=[
                PipelineStep(name="local", role_file="a.yaml", prompt="hello"),
                PipelineStep(
                    name="remote",
                    url="http://agent:8000",
                    mode="mcp",
                    prompt="hello",
                    depends_on=["local"],
                ),
            ]
        )
        assert spec.steps[0].mode == "inline"
        assert spec.steps[1].mode == "mcp"


class TestPipelineDefinition:
    def test_valid(self):
        data = _minimal_pipeline_data()
        p = PipelineDefinition.model_validate(data)
        assert p.kind == "Pipeline"
        assert p.metadata.name == "test-pipeline"
        assert len(p.spec.steps) == 1

    def test_invalid_kind(self):
        data = _minimal_pipeline_data()
        data["kind"] = "Agent"
        with pytest.raises(ValidationError):
            PipelineDefinition.model_validate(data)

    def test_continue_strategy(self):
        data = _minimal_pipeline_data()
        data["spec"]["error_strategy"] = "continue"
        p = PipelineDefinition.model_validate(data)
        assert p.spec.error_strategy == "continue"


class TestPipelineLoader:
    def test_load_valid(self, tmp_path):
        f = tmp_path / "pipeline.yaml"
        f.write_text(
            textwrap.dedent("""\
                apiVersion: initrunner/v1
                kind: Pipeline
                metadata:
                  name: test-pipeline
                spec:
                  steps:
                    - name: step1
                      role_file: ./agent.yaml
                      prompt: "Do something"
            """)
        )
        p = load_pipeline(f)
        assert p.metadata.name == "test-pipeline"

    def test_load_file_not_found(self, tmp_path):
        with pytest.raises(PipelineLoadError, match="Cannot read"):
            load_pipeline(tmp_path / "nonexistent.yaml")

    def test_load_invalid_yaml(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text(":\n  invalid: [yaml\n")
        with pytest.raises(PipelineLoadError, match="Invalid YAML"):
            load_pipeline(f)

    def test_load_invalid_schema(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text(
            textwrap.dedent("""\
                apiVersion: initrunner/v1
                kind: Pipeline
                metadata:
                  name: bad
                spec:
                  steps: []
            """)
        )
        with pytest.raises(PipelineLoadError, match="Validation failed"):
            load_pipeline(f)

    def test_load_non_mapping(self, tmp_path):
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        with pytest.raises(PipelineLoadError, match="Expected a YAML mapping"):
            load_pipeline(f)
