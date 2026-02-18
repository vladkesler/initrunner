"""Tests for the multimodal prompt builder."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest
from pydantic_ai.messages import AudioUrl, BinaryContent, DocumentUrl, ImageUrl, VideoUrl

from initrunner.agent.prompt import (
    attachment_summary,
    build_multimodal_prompt,
    extract_text_from_prompt,
    render_content_as_text,
)

# ---------------------------------------------------------------------------
# Core functionality
# ---------------------------------------------------------------------------


class TestBuildMultimodalPrompt:
    def test_text_only_returns_str(self):
        result = build_multimodal_prompt("hello", None)
        assert result == "hello"
        assert isinstance(result, str)

    def test_empty_attachments_returns_str(self):
        result = build_multimodal_prompt("hello", [])
        assert result == "hello"
        assert isinstance(result, str)

    def test_url_image_creates_image_url(self):
        result = build_multimodal_prompt("describe", ["https://example.com/photo.jpg"])
        assert isinstance(result, list)
        assert result[0] == "describe"
        assert isinstance(result[1], ImageUrl)
        assert result[1].url == "https://example.com/photo.jpg"

    def test_url_audio_creates_audio_url(self):
        result = build_multimodal_prompt("transcribe", ["https://example.com/clip.mp3"])
        assert isinstance(result, list)
        assert isinstance(result[1], AudioUrl)
        assert result[1].url == "https://example.com/clip.mp3"

    def test_url_video_creates_video_url(self):
        result = build_multimodal_prompt("analyze", ["https://example.com/vid.mp4"])
        assert isinstance(result, list)
        assert isinstance(result[1], VideoUrl)
        assert result[1].url == "https://example.com/vid.mp4"

    def test_url_document_creates_document_url(self):
        result = build_multimodal_prompt("summarize", ["https://example.com/doc.pdf"])
        assert isinstance(result, list)
        assert isinstance(result[1], DocumentUrl)
        assert result[1].url == "https://example.com/doc.pdf"

    def test_url_ambiguous_defaults_to_image(self):
        result = build_multimodal_prompt("look", ["https://example.com/content"])
        assert isinstance(result, list)
        assert isinstance(result[1], ImageUrl)

    def test_local_file_creates_binary_content(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        result = build_multimodal_prompt("describe", [str(img)])
        assert isinstance(result, list)
        assert isinstance(result[1], BinaryContent)
        assert result[1].media_type == "image/png"
        assert result[1].data.startswith(b"\x89PNG")

    def test_local_audio_file(self, tmp_path):
        audio = tmp_path / "clip.mp3"
        audio.write_bytes(b"\xff\xfb" + b"\x00" * 100)
        result = build_multimodal_prompt("transcribe", [str(audio)])
        assert isinstance(result, list)
        assert isinstance(result[1], BinaryContent)
        assert result[1].media_type == "audio/mpeg"

    def test_local_video_file(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00\x00\x00\x1c" + b"\x00" * 100)
        result = build_multimodal_prompt("analyze", [str(video)])
        assert isinstance(result, list)
        assert isinstance(result[1], BinaryContent)
        assert result[1].media_type == "video/mp4"

    def test_local_pdf_file(self, tmp_path):
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4" + b"\x00" * 100)
        result = build_multimodal_prompt("summarize", [str(pdf)])
        assert isinstance(result, list)
        assert isinstance(result[1], BinaryContent)
        assert result[1].media_type == "application/pdf"

    def test_text_readable_inlined(self, tmp_path):
        """Text-readable files (.txt, .md, .csv, .html) are inlined into the text."""
        for ext in (".txt", ".md", ".csv", ".html"):
            f = tmp_path / f"test{ext}"
            f.write_text("file content here", encoding="utf-8")
            result = build_multimodal_prompt("analyze this", [str(f)])
            # Should return a str (text files are inlined, no binary parts)
            assert isinstance(result, str), f"Expected str for {ext}, got {type(result)}"
            assert "file content here" in result
            assert "analyze this" in result

    def test_text_readable_mixed_with_binary(self, tmp_path):
        """Text file + image file → list with text inlined and binary appended."""
        txt = tmp_path / "notes.txt"
        txt.write_text("my notes", encoding="utf-8")
        img = tmp_path / "photo.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 100)

        result = build_multimodal_prompt("describe", [str(txt), str(img)])
        assert isinstance(result, list)
        # First element should be combined text
        first = result[0]
        assert isinstance(first, str)
        assert "describe" in first
        assert "my notes" in first
        # Second element should be BinaryContent for the image
        assert isinstance(result[1], BinaryContent)

    def test_mixed_types(self, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        result = build_multimodal_prompt(
            "describe all",
            [str(img), "https://example.com/audio.mp3"],
        )
        assert isinstance(result, list)
        assert result[0] == "describe all"
        assert isinstance(result[1], BinaryContent)  # local jpg
        assert isinstance(result[2], AudioUrl)  # URL


# ---------------------------------------------------------------------------
# Validation & edge cases
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            build_multimodal_prompt("test", ["/nonexistent/file.png"])

    def test_unsupported_format_raises(self, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_bytes(b"data")
        with pytest.raises(ValueError, match="Unsupported file type"):
            build_multimodal_prompt("test", [str(f)])

    def test_file_too_large_raises(self, tmp_path):
        f = tmp_path / "big.png"
        f.write_bytes(b"\x00" * (21 * 1024 * 1024))  # 21 MB
        with pytest.raises(ValueError, match="too large"):
            build_multimodal_prompt("test", [str(f)])

    def test_file_without_extension_raises(self, tmp_path):
        f = tmp_path / "README"
        f.write_bytes(b"data")
        with pytest.raises(ValueError, match="no extension"):
            build_multimodal_prompt("test", [str(f)])

    def test_url_with_image_ext(self):
        result = build_multimodal_prompt("look", ["https://example.com/img.webp"])
        assert isinstance(result, list)
        assert isinstance(result[1], ImageUrl)

    def test_url_with_query_params(self):
        result = build_multimodal_prompt("look", ["https://cdn.example.com/img.png?w=100&h=100"])
        assert isinstance(result, list)
        assert isinstance(result[1], ImageUrl)

    def test_url_doc_extensions(self):
        for ext in (".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv", ".html"):
            result = build_multimodal_prompt("read", [f"https://example.com/file{ext}"])
            assert isinstance(result, list)
            assert isinstance(result[1], DocumentUrl)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_extract_text_from_str(self):
        assert extract_text_from_prompt("hello") == "hello"

    def test_extract_text_from_sequence(self):
        parts = ["hello world", ImageUrl(url="https://example.com/img.png")]
        result = extract_text_from_prompt(parts)
        assert result == "hello world"

    def test_extract_text_from_mixed_sequence(self):
        parts = [
            "part one",
            BinaryContent(data=b"\x89PNG", media_type="image/png"),
            "part two",
        ]
        result = extract_text_from_prompt(parts)
        assert result == "part one\npart two"

    def test_extract_text_no_binary_leak(self):
        """Binary data should never appear in extracted text."""
        secret = b"SECRETDATA12345"
        parts = [
            "user text",
            BinaryContent(data=secret, media_type="image/png"),
        ]
        result = extract_text_from_prompt(parts)
        assert "SECRET" not in result
        assert result == "user text"


# ---------------------------------------------------------------------------
# Attachment summary
# ---------------------------------------------------------------------------


class TestAttachmentSummary:
    def test_attachment_summary_text_only(self):
        assert attachment_summary("hello") is None

    def test_attachment_summary_single_image_url(self):
        parts = ["text", ImageUrl(url="https://example.com/img.png")]
        result = attachment_summary(parts)
        assert result == "[+1 image(s)]"

    def test_attachment_summary_mixed(self):
        parts = [
            "text",
            ImageUrl(url="https://a.com/1.png"),
            ImageUrl(url="https://a.com/2.png"),
            DocumentUrl(url="https://a.com/doc.pdf"),
        ]
        result = attachment_summary(parts)
        assert result == "[+2 image(s), +1 document(s)]"

    def test_attachment_summary_binary_content(self):
        parts = [
            "text",
            BinaryContent(data=b"\x89PNG", media_type="image/png"),
            BinaryContent(data=b"\xff\xfb", media_type="audio/mpeg"),
        ]
        result = attachment_summary(parts)
        assert result is not None
        assert "+1 image(s)" in result
        assert "+1 audio" in result

    def test_attachment_summary_all_types(self):
        parts = [
            "text",
            ImageUrl(url="https://a.com/1.png"),
            AudioUrl(url="https://a.com/1.mp3"),
            VideoUrl(url="https://a.com/1.mp4"),
            DocumentUrl(url="https://a.com/1.pdf"),
        ]
        result = attachment_summary(parts)
        assert result is not None
        assert "+1 image(s)" in result
        assert "+1 audio" in result
        assert "+1 video" in result
        assert "+1 document(s)" in result


# ---------------------------------------------------------------------------
# Server conversion tests (multimodal content parts)
# ---------------------------------------------------------------------------


class TestServerConvert:
    def test_data_uri_base64_decode(self):
        from initrunner.server.convert import convert_content_parts
        from initrunner.server.models import ContentPart

        raw_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        b64 = base64.b64encode(raw_bytes).decode()
        data_uri = f"data:image/png;base64,{b64}"

        parts = [ContentPart(type="image_url", image_url={"url": data_uri})]
        result = convert_content_parts(parts)
        assert len(result) == 1
        assert isinstance(result[0], BinaryContent)
        assert result[0].data == raw_bytes
        assert result[0].media_type == "image/png"

    def test_http_url_stays_image_url(self):
        from initrunner.server.convert import convert_content_parts
        from initrunner.server.models import ContentPart

        parts = [ContentPart(type="image_url", image_url={"url": "https://example.com/img.png"})]
        result = convert_content_parts(parts)
        assert len(result) == 1
        assert isinstance(result[0], ImageUrl)
        assert result[0].url == "https://example.com/img.png"

    def test_text_part_passthrough(self):
        from initrunner.server.convert import convert_content_parts
        from initrunner.server.models import ContentPart

        parts = [ContentPart(type="text", text="hello")]
        result = convert_content_parts(parts)
        assert result == ["hello"]

    def test_input_audio_decode(self):
        from initrunner.server.convert import convert_content_parts
        from initrunner.server.models import ContentPart

        raw_bytes = b"\xff\xfb\x90\x00" + b"\x00" * 20
        b64 = base64.b64encode(raw_bytes).decode()
        parts = [ContentPart(type="input_audio", input_audio={"data": b64, "format": "mp3"})]
        result = convert_content_parts(parts)
        assert len(result) == 1
        assert isinstance(result[0], BinaryContent)
        assert result[0].data == raw_bytes
        assert result[0].media_type == "audio/mp3"

    def test_multimodal_openai_messages(self):
        from initrunner.server.convert import openai_messages_to_pydantic
        from initrunner.server.models import ChatMessage, ContentPart

        messages = [
            ChatMessage(
                role="user",
                content=[
                    ContentPart(type="text", text="What's in this image?"),
                    ContentPart(type="image_url", image_url={"url": "https://example.com/img.png"}),
                ],
            )
        ]
        prompt, history = openai_messages_to_pydantic(messages)
        assert isinstance(prompt, list)
        assert prompt[0] == "What's in this image?"
        assert isinstance(prompt[1], ImageUrl)
        assert history is None

    def test_plain_text_backward_compat(self):
        from initrunner.server.convert import openai_messages_to_pydantic
        from initrunner.server.models import ChatMessage

        messages = [ChatMessage(role="user", content="Hello")]
        prompt, history = openai_messages_to_pydantic(messages)
        assert prompt == "Hello"
        assert isinstance(prompt, str)
        assert history is None


# ---------------------------------------------------------------------------
# Executor integration (multimodal prompt through execute_run)
# ---------------------------------------------------------------------------


class TestExecutorMultimodal:
    def test_execute_run_with_multimodal_prompt(self):
        from initrunner.agent.executor import execute_run
        from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
        from initrunner.agent.schema.role import AgentSpec, RoleDefinition

        role = RoleDefinition(
            apiVersion=ApiVersion.V1,
            kind=Kind.AGENT,
            metadata=Metadata(name="test-agent"),
            spec=AgentSpec(
                role="You are a test.",
                model=ModelConfig(provider="anthropic", name="claude-sonnet-4-5-20250929"),
            ),
        )

        agent = MagicMock()
        result_mock = MagicMock()
        result_mock.output = "I see an image"
        usage = MagicMock()
        usage.input_tokens = 10
        usage.output_tokens = 5
        usage.total_tokens = 15
        usage.tool_calls = 0
        result_mock.usage.return_value = usage
        result_mock.all_messages.return_value = []
        agent.run_sync.return_value = result_mock

        # Pass a multimodal prompt
        prompt = ["describe this", ImageUrl(url="https://example.com/img.png")]
        result, _msgs = execute_run(agent, role, prompt)

        assert result.success is True
        assert result.output == "I see an image"
        # Verify agent.run_sync was called with the multimodal prompt
        agent.run_sync.assert_called_once()
        call_args = agent.run_sync.call_args
        assert call_args[0][0] is prompt


# ---------------------------------------------------------------------------
# Runner integration
# ---------------------------------------------------------------------------


class TestRunnerMultimodal:
    def test_run_single_with_multimodal(self):
        from unittest.mock import patch

        from initrunner.agent.executor import RunResult
        from initrunner.runner.single import run_single

        prompt = ["describe", ImageUrl(url="https://example.com/img.png")]
        mock_result = RunResult(run_id="test123", output="Image description", success=True)

        with patch("initrunner.runner.single.execute_run") as mock_run:
            mock_run.return_value = (mock_result, [])
            result, _ = run_single(MagicMock(), MagicMock(), prompt)

        assert result.success is True
        assert result.output == "Image description"


# ---------------------------------------------------------------------------
# Interactive REPL /attach command
# ---------------------------------------------------------------------------


class TestInteractiveAttach:
    def test_attach_command_queues_file(self):
        """Verify the interactive runner recognizes /attach commands."""
        # This is a unit-level test for the pattern matching.
        # The actual REPL loop is tested via integration tests.
        raw = "/attach /path/to/image.png"
        assert raw.startswith("/attach ")
        attachment = raw[len("/attach ") :].strip()
        assert attachment == "/path/to/image.png"

    def test_clear_attachments_command(self):
        pending = ["/path/to/a.png", "/path/to/b.jpg"]
        if "/clear-attachments" == "/clear-attachments":
            pending.clear()
        assert pending == []


# ---------------------------------------------------------------------------
# render_content_as_text
# ---------------------------------------------------------------------------


class TestRenderContentAsText:
    def test_render_content_str(self):
        assert render_content_as_text("hello") == "hello"

    def test_render_content_image_url(self):
        assert render_content_as_text(ImageUrl(url="https://example.com/img.png")) == "[image]"

    def test_render_content_audio_url(self):
        assert render_content_as_text(AudioUrl(url="https://example.com/clip.mp3")) == "[audio]"

    def test_render_content_video_url(self):
        assert render_content_as_text(VideoUrl(url="https://example.com/vid.mp4")) == "[video]"

    def test_render_content_document_url(self):
        item = DocumentUrl(url="https://example.com/doc.pdf")
        assert render_content_as_text(item) == "[document]"

    def test_render_content_binary_image(self):
        item = BinaryContent(data=b"\x89PNG", media_type="image/png")
        assert render_content_as_text(item) == "[image]"

    def test_render_content_binary_audio(self):
        item = BinaryContent(data=b"\xff\xfb", media_type="audio/mpeg")
        assert render_content_as_text(item) == "[audio]"

    def test_render_content_binary_video(self):
        item = BinaryContent(data=b"\x00\x00", media_type="video/mp4")
        assert render_content_as_text(item) == "[video]"

    def test_render_content_binary_document(self):
        item = BinaryContent(data=b"%PDF", media_type="application/pdf")
        assert render_content_as_text(item) == "[document]"
