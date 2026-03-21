"""Tests for the image_gen tool: config, generation, editing, and registration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.agent.schema.tools import ImageGenToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, get_tool_types
from initrunner.agent.tools.image_gen import (
    _save_image,
    build_image_gen_toolset,
)


def _make_ctx(prefer_async: bool = False):
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
    )
    return ToolBuildContext(role=role, prefer_async=prefer_async)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestImageGenConfig:
    def test_defaults(self):
        config = ImageGenToolConfig()
        assert config.type == "image_gen"
        assert config.provider == "openai"
        assert config.api_key_env == "${OPENAI_API_KEY}"
        assert config.default_size == "1024x1024"

    def test_stability_no_default_key(self):
        config = ImageGenToolConfig(provider="stability", api_key_env="${STABILITY_KEY}")
        assert config.api_key_env == "${STABILITY_KEY}"

    def test_summary(self):
        assert ImageGenToolConfig().summary() == "image_gen: openai"
        config = ImageGenToolConfig(provider="stability", api_key_env="${KEY}")
        assert config.summary() == "image_gen: stability"

    def test_round_trip(self):
        config = ImageGenToolConfig(output_dir="/tmp/images")
        data = config.model_dump()
        restored = ImageGenToolConfig.model_validate(data)
        assert restored.output_dir == "/tmp/images"

    def test_from_dict(self):
        config = ImageGenToolConfig.model_validate({"type": "image_gen"})
        assert config.type == "image_gen"

    def test_in_agent_spec(self):
        from initrunner.agent.schema.role import parse_tool_list

        tools = parse_tool_list([{"type": "image_gen", "provider": "openai"}])
        assert len(tools) == 1
        assert isinstance(tools[0], ImageGenToolConfig)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestSaveImage:
    def test_saves_to_dir(self, tmp_path: Path):
        data = b"\x89PNG\r\n\x1a\nfake image data"
        path_str = _save_image(data, tmp_path)
        path = Path(path_str)
        assert path.exists()
        assert path.parent == tmp_path
        assert path.suffix == ".png"
        assert path.read_bytes() == data

    def test_creates_dir(self, tmp_path: Path):
        sub = tmp_path / "nested" / "dir"
        data = b"test"
        path_str = _save_image(data, sub)
        assert Path(path_str).exists()


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


class TestGenerateImage:
    def test_openai_generate(self, tmp_path: Path):
        fake_b64 = "aGVsbG8="  # base64 of "hello"
        mock_response = MagicMock()
        mock_response.data = [MagicMock(b64_json=fake_b64)]

        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("initrunner.agent.tools.image_gen._generate_openai") as mock_gen:
            mock_gen.return_value = b"hello"

            config = ImageGenToolConfig(output_dir=str(tmp_path))
            toolset = build_image_gen_toolset(config, _make_ctx())
            fn = toolset.tools["generate_image"].function
            result = fn(prompt="a cat")

            assert tmp_path.name in result or "image_" in result
            mock_gen.assert_called_once()

    def test_stability_generate(self, tmp_path: Path):
        with patch("initrunner.agent.tools.image_gen._generate_stability") as mock_gen:
            mock_gen.return_value = b"image_data"

            config = ImageGenToolConfig(
                provider="stability",
                api_key_env="${STABILITY_KEY}",
                output_dir=str(tmp_path),
            )
            toolset = build_image_gen_toolset(config, _make_ctx())
            fn = toolset.tools["generate_image"].function
            result = fn(prompt="a dog")

            assert "image_" in result
            mock_gen.assert_called_once()

    def test_generate_error(self, tmp_path: Path):
        with patch("initrunner.agent.tools.image_gen._generate_openai") as mock_gen:
            mock_gen.side_effect = RuntimeError("API error")

            config = ImageGenToolConfig(output_dir=str(tmp_path))
            toolset = build_image_gen_toolset(config, _make_ctx())
            fn = toolset.tools["generate_image"].function
            result = fn(prompt="a cat")
            assert "Error:" in result
            assert "API error" in result


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------


class TestEditImage:
    def test_path_inside_output_dir(self, tmp_path: Path):
        img_file = tmp_path / "source.png"
        img_file.write_bytes(b"\x89PNG fake")

        with patch("initrunner.agent.tools.image_gen.validate_path_within") as mock_validate:
            mock_validate.return_value = (None, img_file)

            mock_response = MagicMock()
            mock_response.data = [MagicMock(b64_json="aGVsbG8=")]

            with patch("openai.OpenAI") as mock_openai_cls:
                mock_client = MagicMock()
                mock_client.images.edit.return_value = mock_response
                mock_openai_cls.return_value = mock_client

                config = ImageGenToolConfig(output_dir=str(tmp_path))
                toolset = build_image_gen_toolset(config, _make_ctx())
                fn = toolset.tools["edit_image"].function
                result = fn(image_path=str(img_file), prompt="make it blue")

                assert "image_" in result

    def test_path_outside_allowed_roots(self, tmp_path: Path):
        config = ImageGenToolConfig(output_dir=str(tmp_path))
        toolset = build_image_gen_toolset(config, _make_ctx())
        fn = toolset.tools["edit_image"].function
        result = fn(image_path="/etc/passwd", prompt="edit")
        assert "Error:" in result

    def test_path_with_input_root(self, tmp_path: Path):
        input_dir = tmp_path / "inputs"
        input_dir.mkdir()
        img_file = input_dir / "source.png"
        img_file.write_bytes(b"\x89PNG fake")

        with patch("initrunner.agent.tools.image_gen.validate_path_within") as mock_validate:
            mock_validate.return_value = (None, img_file)

            mock_response = MagicMock()
            mock_response.data = [MagicMock(b64_json="aGVsbG8=")]

            with patch("openai.OpenAI") as mock_openai_cls:
                mock_client = MagicMock()
                mock_client.images.edit.return_value = mock_response
                mock_openai_cls.return_value = mock_client

                config = ImageGenToolConfig(
                    output_dir=str(tmp_path / "output"),
                    input_root=str(input_dir),
                )
                toolset = build_image_gen_toolset(config, _make_ctx())
                fn = toolset.tools["edit_image"].function
                result = fn(image_path=str(img_file), prompt="make it blue")

                assert "image_" in result

    def test_file_not_found(self, tmp_path: Path):
        config = ImageGenToolConfig(output_dir=str(tmp_path))
        toolset = build_image_gen_toolset(config, _make_ctx())
        fn = toolset.tools["edit_image"].function
        result = fn(image_path=str(tmp_path / "nope.png"), prompt="edit")
        assert "Error:" in result


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


class TestAsyncPath:
    def test_async_builder_registers_async_tools(self, tmp_path: Path):
        config = ImageGenToolConfig(output_dir=str(tmp_path))
        toolset = build_image_gen_toolset(config, _make_ctx(prefer_async=True))
        assert "generate_image" in toolset.tools
        assert "edit_image" in toolset.tools
        # The tool function should be a coroutine function
        import inspect

        assert inspect.iscoroutinefunction(toolset.tools["generate_image"].function)

    def test_async_generate(self, tmp_path: Path):
        with patch("initrunner.agent.tools.image_gen._generate_openai_async") as mock_gen:
            mock_gen.return_value = b"hello"

            config = ImageGenToolConfig(output_dir=str(tmp_path))
            toolset = build_image_gen_toolset(config, _make_ctx(prefer_async=True))
            fn = toolset.tools["generate_image"].function
            result = asyncio.run(fn(prompt="a cat"))
            assert "image_" in result


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestImageGenRegistration:
    def test_registered_in_tool_types(self):
        types = get_tool_types()
        assert "image_gen" in types
        assert types["image_gen"] is ImageGenToolConfig

    def test_builds_both_tools(self, tmp_path: Path):
        config = ImageGenToolConfig(output_dir=str(tmp_path))
        toolset = build_image_gen_toolset(config, _make_ctx())
        assert "generate_image" in toolset.tools
        assert "edit_image" in toolset.tools
