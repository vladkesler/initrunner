"""Tests for chat UI helpers (_to_json rendering, temp file cleanup)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ImageUrl,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from initrunner.agent.prompt import render_content_as_text

# ---------------------------------------------------------------------------
# _to_json multimodal rendering
# ---------------------------------------------------------------------------


class TestToJsonMultimodal:
    def test_to_json_multimodal_uses_placeholders(self):
        """_to_json should render multimodal content as '[image] text', not Python repr."""

        def _to_json(messages):
            result = []
            for msg in messages:
                if isinstance(msg, ModelRequest):
                    for part in msg.parts:
                        if isinstance(part, UserPromptPart):
                            if isinstance(part.content, str):
                                content = part.content
                            elif isinstance(part.content, list):
                                content = " ".join(
                                    render_content_as_text(item) for item in part.content
                                )
                            else:
                                content = str(part.content)
                            result.append({"role": "user", "content": content})
                elif isinstance(msg, ModelResponse):
                    for part in msg.parts:
                        if isinstance(part, TextPart):
                            result.append({"role": "assistant", "content": part.content})
            return result

        messages = [
            ModelRequest(
                parts=[
                    UserPromptPart(
                        content=[
                            "describe this",
                            ImageUrl(url="https://example.com/img.png"),
                        ]
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content="It is an image.")]),
        ]

        result = _to_json(messages)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "describe this [image]"
        assert "ImageUrl" not in result[0]["content"]
        assert result[1]["content"] == "It is an image."


# ---------------------------------------------------------------------------
# Temp file cleanup
# ---------------------------------------------------------------------------


class TestTempFileCleanup:
    def test_staged_temp_file_deleted_on_success(self, tmp_path):
        """Temp files from staging should be cleaned up after build_multimodal_prompt."""
        from initrunner.agent.prompt import build_multimodal_prompt

        tmp_file = tmp_path / "upload.png"
        tmp_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        assert tmp_file.exists()

        resolved_paths = [str(tmp_file)]
        try:
            build_multimodal_prompt("describe", resolved_paths)
        finally:
            for p in resolved_paths:
                Path(p).unlink(missing_ok=True)

        assert not tmp_file.exists()

    def test_staged_temp_file_deleted_on_error(self, tmp_path):
        """Temp files should be cleaned up even when build_multimodal_prompt raises."""
        from initrunner.agent.prompt import build_multimodal_prompt

        tmp_file = tmp_path / "upload.xyz"
        tmp_file.write_bytes(b"data")
        assert tmp_file.exists()

        resolved_paths = [str(tmp_file)]
        with pytest.raises(ValueError, match="Unsupported file type"):
            try:
                build_multimodal_prompt("describe", resolved_paths)
            finally:
                for p in resolved_paths:
                    Path(p).unlink(missing_ok=True)

        assert not tmp_file.exists()
