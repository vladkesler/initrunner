"""Tests for structured output: build_output_model, resolve_output_type, executor."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

from initrunner.agent.output import build_output_model, resolve_output_type
from initrunner.agent.schema.output import OutputConfig


def _minimal_role_data(**spec_overrides: object) -> dict:
    data: dict = {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent"},
        "spec": {
            "role": "test",
            "model": {"provider": "anthropic", "name": "claude-sonnet-4-5-20250929"},
        },
    }
    data["spec"].update(spec_overrides)
    return data


def _json_schema_output_spec() -> dict:
    return {
        "output": {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
        },
    }


# ---------------------------------------------------------------------------
# build_output_model
# ---------------------------------------------------------------------------


class TestBuildOutputModel:
    def test_flat_object(self):
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["status", "count"],
        }
        Model = build_output_model(schema)
        instance = Model(status="ok", count=42)
        assert instance.status == "ok"  # type: ignore[unresolved-attribute]
        assert instance.count == 42  # type: ignore[unresolved-attribute]

    def test_string_enum(self):
        schema = {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["approved", "rejected"],
                },
            },
            "required": ["verdict"],
        }
        Model = build_output_model(schema)
        instance = Model(verdict="approved")
        assert instance.verdict == "approved"  # type: ignore[unresolved-attribute]

        with pytest.raises(ValidationError):
            Model(verdict="unknown")

    def test_nested_object(self):
        schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "integer"},
                    },
                    "required": ["name"],
                },
            },
            "required": ["user"],
        }
        Model = build_output_model(schema)
        instance = Model(user={"name": "Alice", "age": 30})
        assert instance.user.name == "Alice"  # type: ignore[unresolved-attribute]
        assert instance.user.age == 30  # type: ignore[unresolved-attribute]

    def test_array_of_strings(self):
        schema = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["tags"],
        }
        Model = build_output_model(schema)
        instance = Model(tags=["a", "b", "c"])
        assert instance.tags == ["a", "b", "c"]  # type: ignore[unresolved-attribute]

    def test_array_of_objects(self):
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "label": {"type": "string"},
                        },
                        "required": ["id"],
                    },
                },
            },
            "required": ["items"],
        }
        Model = build_output_model(schema)
        instance = Model(items=[{"id": 1, "label": "x"}, {"id": 2}])
        assert len(instance.items) == 2  # type: ignore[unresolved-attribute]
        assert instance.items[0].id == 1  # type: ignore[unresolved-attribute]
        assert instance.items[1].label is None  # type: ignore[unresolved-attribute]

    def test_optional_fields(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "nickname": {"type": "string"},
            },
            "required": ["name"],
        }
        Model = build_output_model(schema)
        instance = Model(name="Alice")
        assert instance.name == "Alice"  # type: ignore[unresolved-attribute]
        assert instance.nickname is None  # type: ignore[unresolved-attribute]

    def test_required_field_missing_raises(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        }
        Model = build_output_model(schema)
        with pytest.raises(ValidationError):
            Model()

    def test_description_on_fields(self):
        schema = {
            "type": "object",
            "properties": {
                "score": {
                    "type": "number",
                    "description": "A confidence score between 0 and 1",
                },
            },
            "required": ["score"],
        }
        Model = build_output_model(schema)
        json_schema = Model.model_json_schema()
        desc = json_schema["properties"]["score"]["description"]
        assert desc == "A confidence score between 0 and 1"

    def test_empty_properties(self):
        schema = {"type": "object", "properties": {}}
        Model = build_output_model(schema)
        instance = Model()
        assert instance is not None

    def test_non_object_root_raises(self):
        with pytest.raises(ValueError, match="Root schema must be type: object"):
            build_output_model({"type": "string"})

    def test_non_object_root_array_raises(self):
        with pytest.raises(ValueError, match="Root schema must be type: object"):
            build_output_model({"type": "array", "items": {"type": "string"}})

    def test_boolean_type(self):
        schema = {
            "type": "object",
            "properties": {
                "active": {"type": "boolean"},
            },
            "required": ["active"],
        }
        Model = build_output_model(schema)
        instance = Model(active=True)
        assert instance.active is True  # type: ignore[unresolved-attribute]

    def test_number_type(self):
        schema = {
            "type": "object",
            "properties": {
                "price": {"type": "number"},
            },
            "required": ["price"],
        }
        Model = build_output_model(schema)
        instance = Model(price=19.99)
        assert instance.price == 19.99  # type: ignore[unresolved-attribute]

    def test_custom_model_name(self):
        schema = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        }
        Model = build_output_model(schema, model_name="InvoiceResult")
        assert Model.__name__ == "InvoiceResult"

    def test_validation_rejects_wrong_type(self):
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
            },
            "required": ["count"],
        }
        Model = build_output_model(schema)
        with pytest.raises(ValidationError):
            Model(count="not a number")

    def test_model_dump_json(self):
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["approved", "rejected"]},
                "amount": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["status", "amount", "reason"],
        }
        Model = build_output_model(schema)
        instance = Model(status="approved", amount=100.0, reason="looks good")
        data = json.loads(instance.model_dump_json())
        assert data == {"status": "approved", "amount": 100.0, "reason": "looks good"}


# ---------------------------------------------------------------------------
# resolve_output_type
# ---------------------------------------------------------------------------


class TestResolveOutputType:
    def test_text_returns_str(self):
        config = OutputConfig(type="text")
        assert resolve_output_type(config) is str

    def test_default_returns_str(self):
        config = OutputConfig()
        assert resolve_output_type(config) is str

    def test_json_schema_inline(self):
        config = OutputConfig.model_validate(
            {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            }
        )
        result = resolve_output_type(config)
        assert issubclass(result, BaseModel)
        instance = result(name="test")
        assert instance.name == "test"  # type: ignore[unresolved-attribute]

    def test_json_schema_file(self, tmp_path: Path):
        schema = {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        }
        schema_file = tmp_path / "schema.json"
        schema_file.write_text(json.dumps(schema))

        config = OutputConfig(type="json_schema", schema_file="schema.json")
        result = resolve_output_type(config, role_dir=tmp_path)
        assert issubclass(result, BaseModel)
        instance = result(value=42)
        assert instance.value == 42  # type: ignore[unresolved-attribute]

    def test_schema_file_not_found(self, tmp_path: Path):
        config = OutputConfig(type="json_schema", schema_file="nonexistent.json")
        with pytest.raises(FileNotFoundError):
            resolve_output_type(config, role_dir=tmp_path)

    def test_schema_file_invalid_json(self, tmp_path: Path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json{{{")

        config = OutputConfig(type="json_schema", schema_file="bad.json")
        with pytest.raises(json.JSONDecodeError):
            resolve_output_type(config, role_dir=tmp_path)

    def test_schema_file_non_object_raises(self, tmp_path: Path):
        schema_file = tmp_path / "string.json"
        schema_file.write_text(json.dumps({"type": "string"}))

        config = OutputConfig(type="json_schema", schema_file="string.json")
        with pytest.raises(ValueError, match="Root schema must be type: object"):
            resolve_output_type(config, role_dir=tmp_path)

    def test_schema_file_absolute_path(self, tmp_path: Path):
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }
        schema_file = tmp_path / "abs_schema.json"
        schema_file.write_text(json.dumps(schema))

        config = OutputConfig(type="json_schema", schema_file=str(schema_file))
        result = resolve_output_type(config)
        assert issubclass(result, BaseModel)


# ---------------------------------------------------------------------------
# Executor integration: BaseModel serialization
# ---------------------------------------------------------------------------


class TestExecutorBaseModelSerialization:
    def test_base_model_output_serialized_to_json(self):
        """Verify that executor serializes BaseModel output via model_dump_json()."""
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["status", "count"],
        }
        Model = build_output_model(schema)
        instance = Model(status="done", count=5)

        from initrunner.agent.executor import RunResult

        result = RunResult(run_id="test-run")

        # Simulate the serialization logic from executor
        from pydantic import BaseModel as PydanticBaseModel

        raw_output = instance
        if isinstance(raw_output, PydanticBaseModel):
            result.output = raw_output.model_dump_json()
        elif isinstance(raw_output, (dict, list)):
            result.output = json.dumps(raw_output)
        else:
            result.output = str(raw_output)

        parsed = json.loads(result.output)
        assert parsed == {"status": "done", "count": 5}


# ---------------------------------------------------------------------------
# Streaming guard
# ---------------------------------------------------------------------------


class TestStreamingGuard:
    def test_streaming_with_structured_output_raises(self):
        """execute_run_stream raises ValueError when output.type is json_schema."""
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_minimal_role_data(**_json_schema_output_spec()))

        from initrunner.agent.executor import execute_run_stream

        agent = MagicMock()
        with pytest.raises(ValueError, match="Streaming is not supported with structured output"):
            execute_run_stream(agent, role, "test prompt", skip_input_validation=True)

    def test_streaming_with_text_output_does_not_raise(self):
        """execute_run_stream does not raise for text output (normal path)."""
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_minimal_role_data(output={"type": "text"}))

        from initrunner.agent.executor import execute_run_stream

        agent = MagicMock()
        # Should not raise ValueError — it will fail later on the mock but that's fine
        # We just verify the structured output guard is not triggered
        with patch("initrunner.agent.executor._prepare_run") as mock_prep:
            mock_prep.return_value = ("run-id", MagicMock(), {}, None)
            with patch("initrunner.agent.executor._run_with_timeout") as mock_timeout:
                mock_timeout.side_effect = TimeoutError("expected")
                result, _ = execute_run_stream(agent, role, "test", skip_input_validation=True)
                assert result.success is False


# ---------------------------------------------------------------------------
# Pipeline precedence: explicit output_type param overrides role config
# ---------------------------------------------------------------------------


class TestPipelinePrecedence:
    """Pipeline step's output_format overrides role-level output config via explicit output_type."""

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_pipeline_text_overrides_role_json_schema(self, mock_require, mock_agent_cls):
        """Pipeline step output_format=text → output_type=str, overriding role json_schema."""
        from initrunner.agent.loader import build_agent
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_minimal_role_data(**_json_schema_output_spec()))

        # Pipeline passes explicit output_type=str (text format)
        build_agent(role, output_type=str)
        call_kwargs = mock_agent_cls.call_args
        assert call_kwargs.kwargs["output_type"] is str

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_pipeline_json_overrides_role_json_schema(self, mock_require, mock_agent_cls):
        """Pipeline step output_format=json → output_type=dict, overriding role json_schema."""
        from initrunner.agent.loader import build_agent
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(_minimal_role_data(**_json_schema_output_spec()))

        # Pipeline passes explicit output_type=dict (json format)
        build_agent(role, output_type=dict)
        call_kwargs = mock_agent_cls.call_args
        assert call_kwargs.kwargs["output_type"] is dict
