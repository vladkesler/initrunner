"""Tests for the audio tool: YouTube transcript fetching and audio transcription."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent.schema.role import AgentSpec
from initrunner.agent.schema.tools import AudioToolConfig
from initrunner.agent.tools._registry import ToolBuildContext
from initrunner.agent.tools.audio import _extract_video_id, build_audio_toolset

# ---------------------------------------------------------------------------
# Fake exception classes for YouTube mocking
# ---------------------------------------------------------------------------


class _FakeTranscriptsDisabled(Exception):
    pass


class _FakeNoTranscriptFound(Exception):
    pass


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_ctx(provider: str = "openai", name: str = "gpt-4o") -> ToolBuildContext:
    """Build a minimal ToolBuildContext for tests."""
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": provider, "name": name},
            },
        }
    )
    return ToolBuildContext(role=role)


class _FakeSnippet:
    """Mimics FetchedTranscriptSnippet with attribute access."""

    def __init__(self, text: str, start: float, duration: float):
        self.text = text
        self.start = start
        self.duration = duration


def _make_yt_mock(
    entries: list[dict[str, str | float]] | None = None,
    list_side_effect: Exception | None = None,
    find_side_effect: Exception | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Return (mock_yt_module, mock_errors) for patching sys.modules."""
    raw = entries or [{"text": "Hello world", "start": 0.0, "duration": 1.0}]
    snippets = [_FakeSnippet(**e) for e in raw]  # type: ignore[invalid-argument-type]

    mock_transcript = MagicMock()
    mock_transcript.fetch.return_value = snippets

    mock_tlist = MagicMock()
    if find_side_effect is not None:
        mock_tlist.find_transcript.side_effect = find_side_effect
        mock_tlist.find_generated_transcript.side_effect = find_side_effect
    else:
        mock_tlist.find_transcript.return_value = mock_transcript
        mock_tlist.find_generated_transcript.return_value = mock_transcript

    mock_instance = MagicMock()
    if list_side_effect is not None:
        mock_instance.list.side_effect = list_side_effect
    else:
        mock_instance.list.return_value = mock_tlist

    mock_api_class = MagicMock(return_value=mock_instance)

    mock_yt_mod = MagicMock()
    mock_yt_mod.YouTubeTranscriptApi = mock_api_class

    mock_errors = MagicMock()
    mock_errors.NoTranscriptFound = _FakeNoTranscriptFound
    mock_errors.TranscriptsDisabled = _FakeTranscriptsDisabled

    return mock_yt_mod, mock_errors


_YT_MODULES = {
    "youtube_transcript_api": None,
    "youtube_transcript_api._errors": None,
}


# ---------------------------------------------------------------------------
# Schema / config tests
# ---------------------------------------------------------------------------


class TestAudioConfig:
    def test_defaults(self):
        config = AudioToolConfig()
        assert config.youtube_languages == ["en"]
        assert config.include_timestamps is False
        assert config.transcription_model is None
        assert config.max_audio_mb == 20.0
        assert config.max_transcript_chars == 50_000

    def test_summary(self):
        assert AudioToolConfig().summary() == "audio"

    def test_in_agent_spec(self):
        spec = AgentSpec.model_validate(
            {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-4o"},
                "tools": [{"type": "audio"}],
            }
        )
        assert len(spec.tools) == 1
        assert isinstance(spec.tools[0], AudioToolConfig)

    def test_custom_languages(self):
        config = AudioToolConfig(youtube_languages=["es", "fr"])
        assert config.youtube_languages == ["es", "fr"]

    def test_include_timestamps(self):
        config = AudioToolConfig(include_timestamps=True)
        assert config.include_timestamps is True

    def test_transcription_model_override(self):
        config = AudioToolConfig(transcription_model="openai:gpt-4o-audio-preview")
        assert config.transcription_model == "openai:gpt-4o-audio-preview"


# ---------------------------------------------------------------------------
# _extract_video_id helper
# ---------------------------------------------------------------------------


class TestExtractVideoId:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
            ("https://example.com/not-youtube", None),
            ("not a url at all", None),
        ],
    )
    def test_extract(self, url: str, expected: str | None):
        assert _extract_video_id(url) == expected


# ---------------------------------------------------------------------------
# Toolset builder
# ---------------------------------------------------------------------------


class TestAudioToolsetBuilder:
    def test_builds_toolset(self):
        config = AudioToolConfig()
        toolset = build_audio_toolset(config, _make_ctx())
        assert "get_youtube_transcript" in toolset.tools
        assert "transcribe_audio" in toolset.tools

    def test_registered_in_registry(self):
        from initrunner.agent.tools._registry import get_builder

        assert get_builder("audio") is not None


# ---------------------------------------------------------------------------
# get_youtube_transcript
# ---------------------------------------------------------------------------


class TestGetYoutubeTranscript:
    def _fn(self, config: AudioToolConfig | None = None):
        config = config or AudioToolConfig()
        return build_audio_toolset(config, _make_ctx()).tools["get_youtube_transcript"].function

    def test_success(self):
        mock_yt, mock_errors = _make_yt_mock(
            entries=[
                {"text": "Hello", "start": 0.0, "duration": 1.0},
                {"text": "world", "start": 1.0, "duration": 1.0},
            ]
        )
        with patch.dict(
            "sys.modules",
            {"youtube_transcript_api": mock_yt, "youtube_transcript_api._errors": mock_errors},
        ):
            result = self._fn()(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert result == "Hello world"

    def test_with_timestamps(self):
        mock_yt, mock_errors = _make_yt_mock(
            entries=[{"text": "Hi", "start": 5.0, "duration": 1.0}]
        )
        with patch.dict(
            "sys.modules",
            {"youtube_transcript_api": mock_yt, "youtube_transcript_api._errors": mock_errors},
        ):
            result = self._fn(AudioToolConfig(include_timestamps=True))(
                url="https://youtu.be/dQw4w9WgXcQ"
            )
        assert "[5.0s]" in result
        assert "Hi" in result

    def test_transcripts_disabled(self):
        mock_yt, mock_errors = _make_yt_mock(list_side_effect=_FakeTranscriptsDisabled("disabled"))
        with patch.dict(
            "sys.modules",
            {"youtube_transcript_api": mock_yt, "youtube_transcript_api._errors": mock_errors},
        ):
            result = self._fn()(url="https://youtu.be/dQw4w9WgXcQ")
        assert "Error" in result
        assert "disabled" in result.lower()

    def test_no_transcript_found(self):
        mock_yt, mock_errors = _make_yt_mock(
            list_side_effect=_FakeNoTranscriptFound("no transcript")
        )
        with patch.dict(
            "sys.modules",
            {"youtube_transcript_api": mock_yt, "youtube_transcript_api._errors": mock_errors},
        ):
            result = self._fn()(url="https://youtu.be/dQw4w9WgXcQ")
        assert "Error" in result

    def test_missing_package(self):
        with patch.dict("sys.modules", {"youtube_transcript_api": None}):
            result = self._fn()(url="https://youtu.be/dQw4w9WgXcQ")
        assert "initrunner[audio]" in result

    def test_bad_url(self):
        result = self._fn()(url="https://example.com/not-youtube")
        assert "Error" in result

    def test_truncation(self):
        long_entries = [{"text": "x" * 200, "start": float(i), "duration": 1.0} for i in range(10)]
        mock_yt, mock_errors = _make_yt_mock(entries=long_entries)
        with patch.dict(
            "sys.modules",
            {"youtube_transcript_api": mock_yt, "youtube_transcript_api._errors": mock_errors},
        ):
            result = self._fn(AudioToolConfig(max_transcript_chars=100))(
                url="https://youtu.be/dQw4w9WgXcQ"
            )
        assert "[truncated]" in result
        assert len(result) <= 100 + len("\n[truncated]")

    def test_language_override(self):
        mock_yt, mock_errors = _make_yt_mock()
        with patch.dict(
            "sys.modules",
            {"youtube_transcript_api": mock_yt, "youtube_transcript_api._errors": mock_errors},
        ):
            self._fn()(url="https://youtu.be/dQw4w9WgXcQ", language="es")
        mock_yt.YouTubeTranscriptApi.return_value.list.assert_called_once()

    def test_generic_error(self):
        mock_yt, mock_errors = _make_yt_mock(list_side_effect=RuntimeError("network error"))
        with patch.dict(
            "sys.modules",
            {"youtube_transcript_api": mock_yt, "youtube_transcript_api._errors": mock_errors},
        ):
            result = self._fn()(url="https://youtu.be/dQw4w9WgXcQ")
        assert "Error fetching transcript" in result
        assert "network error" in result


# ---------------------------------------------------------------------------
# transcribe_audio
# ---------------------------------------------------------------------------


class TestTranscribeAudio:
    def _fn(self, config: AudioToolConfig | None = None, ctx: ToolBuildContext | None = None):
        config = config or AudioToolConfig()
        ctx = ctx or _make_ctx()
        return build_audio_toolset(config, ctx).tools["transcribe_audio"].function

    def test_success(self, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake audio data")

        mock_result = MagicMock()
        mock_result.output = "Hello, this is the transcript."
        mock_agent = MagicMock()
        mock_agent.run_sync.return_value = mock_result

        with patch("initrunner.agent.tools.audio.Agent", return_value=mock_agent):
            result = self._fn()(file_path=str(audio_file))

        assert result == "Hello, this is the transcript."

    def test_uses_role_model(self, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"data")

        mock_result = MagicMock()
        mock_result.output = "transcript"
        mock_agent = MagicMock()
        mock_agent.run_sync.return_value = mock_result

        with patch("initrunner.agent.tools.audio.Agent", return_value=mock_agent) as MockAgent:
            self._fn(ctx=_make_ctx("anthropic", "claude-3-5-sonnet-latest"))(
                file_path=str(audio_file)
            )

        MockAgent.assert_called_once_with("anthropic:claude-3-5-sonnet-latest")

    def test_transcription_model_override(self, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"data")

        mock_result = MagicMock()
        mock_result.output = "transcript"
        mock_agent = MagicMock()
        mock_agent.run_sync.return_value = mock_result

        with patch("initrunner.agent.tools.audio.Agent", return_value=mock_agent) as MockAgent:
            self._fn(config=AudioToolConfig(transcription_model="openai:gpt-4o-audio-preview"))(
                file_path=str(audio_file)
            )

        MockAgent.assert_called_once_with("openai:gpt-4o-audio-preview")

    def test_file_not_found(self):
        result = self._fn()(file_path="/nonexistent/path/file.mp3")
        assert "Error" in result
        assert "not found" in result

    def test_unsupported_format(self, tmp_path):
        txt_file = tmp_path / "file.txt"
        txt_file.write_text("not audio")
        result = self._fn()(file_path=str(txt_file))
        assert "Error" in result
        assert "unsupported" in result.lower()

    def test_file_too_large(self, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"x")
        result = self._fn(config=AudioToolConfig(max_audio_mb=0.0))(file_path=str(audio_file))
        assert "Error" in result
        assert "MB" in result

    def test_model_error(self, tmp_path):
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"data")

        mock_agent = MagicMock()
        mock_agent.run_sync.side_effect = Exception("audio not supported by this model")

        with patch("initrunner.agent.tools.audio.Agent", return_value=mock_agent):
            result = self._fn()(file_path=str(audio_file))

        assert "Error" in result
        assert "audio not supported" in result

    def test_output_truncation(self, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"data")

        mock_result = MagicMock()
        mock_result.output = "x" * 100_000
        mock_agent = MagicMock()
        mock_agent.run_sync.return_value = mock_result

        with patch("initrunner.agent.tools.audio.Agent", return_value=mock_agent):
            result = self._fn(config=AudioToolConfig(max_transcript_chars=500))(
                file_path=str(audio_file)
            )

        assert "[truncated]" in result
        assert len(result) <= 500 + len("\n[truncated]")

    def test_uses_mimetypes_for_known_extension(self, tmp_path):
        """Standard mimetypes are resolved via the stdlib mimetypes module."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"data")

        mock_result = MagicMock()
        mock_result.output = "transcript"
        mock_agent = MagicMock()
        mock_agent.run_sync.return_value = mock_result

        with patch("initrunner.agent.tools.audio.Agent", return_value=mock_agent):
            with patch(
                "initrunner.agent.tools.audio.mimetypes.guess_type",
                return_value=("audio/mpeg", None),
            ):
                result = self._fn()(file_path=str(audio_file))

        assert result == "transcript"

    def test_fallback_mime_when_mimetypes_returns_none(self, tmp_path):
        """Falls back to _FALLBACK_MIME dict when mimetypes.guess_type returns None."""
        audio_file = tmp_path / "test.flac"
        audio_file.write_bytes(b"data")

        mock_result = MagicMock()
        mock_result.output = "transcript"
        mock_agent = MagicMock()
        mock_agent.run_sync.return_value = mock_result

        captured_calls: list = []

        def capture_run_sync(prompt_parts):
            captured_calls.append(prompt_parts)
            return mock_result

        mock_agent.run_sync.side_effect = capture_run_sync

        with patch("initrunner.agent.tools.audio.Agent", return_value=mock_agent):
            with patch(
                "initrunner.agent.tools.audio.mimetypes.guess_type", return_value=(None, None)
            ):
                self._fn()(file_path=str(audio_file))

        assert len(captured_calls) == 1
        binary_part = captured_calls[0][1]
        assert binary_part.media_type == "audio/flac"
