"""Audio tool: YouTube transcript fetching and audio file transcription via configured model."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.messages import BinaryContent
from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.schema.tools import AudioToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

_SUPPORTED_EXTS = frozenset({".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".webm", ".mpeg", ".flac"})

_FALLBACK_MIME: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".mpeg": "audio/mpeg",
    ".flac": "audio/flac",
}


_YT_PATTERNS = [
    re.compile(r"youtube\.com/watch.*[?&]v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/embed/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
]


def _extract_video_id(url: str) -> str | None:
    """Extract an 11-character YouTube video ID from various URL formats."""
    for pattern in _YT_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


@register_tool("audio", AudioToolConfig)
def build_audio_toolset(config: AudioToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for audio operations."""
    toolset = FunctionToolset()

    @toolset.tool
    def get_youtube_transcript(url: str, language: str = "") -> str:
        """Fetch the transcript/captions for a YouTube video.

        Returns the full transcript as a single block of text. Use language to
        request a specific language code (e.g. 'en', 'es'). Leave empty to use
        the languages configured on this tool.
        """
        try:
            from youtube_transcript_api import (  # type: ignore[import-not-found]
                YouTubeTranscriptApi,
            )
            from youtube_transcript_api._errors import (  # type: ignore[import-not-found]
                NoTranscriptFound,
                TranscriptsDisabled,
            )
        except ImportError:
            return (
                "Error: youtube-transcript-api is required. "
                "Install with: pip install initrunner[audio]"
            )

        video_id = _extract_video_id(url)
        if not video_id:
            return f"Error: could not extract a YouTube video ID from URL: {url!r}"

        langs = [language] if language else config.youtube_languages
        try:
            ytt = YouTubeTranscriptApi()
            transcript_list = ytt.list(video_id)
            try:
                transcript = transcript_list.find_transcript(langs)
            except NoTranscriptFound:
                transcript = transcript_list.find_generated_transcript(langs)
            entries = transcript.fetch()
        except TranscriptsDisabled:
            return "Error: transcripts are disabled for this video."
        except NoTranscriptFound:
            return f"Error: no transcript found for video {video_id!r} in languages {langs}."
        except Exception as exc:
            return f"Error fetching transcript: {exc}"

        parts: list[str] = []
        for entry in entries:
            text = entry.text
            if config.include_timestamps:
                text = f"[{entry.start:.1f}s] {text}"
            parts.append(text)

        result = " ".join(parts)
        if len(result) > config.max_transcript_chars:
            result = result[: config.max_transcript_chars] + "\n[truncated]"
        return result

    @toolset.tool
    def transcribe_audio(file_path: str) -> str:
        """Transcribe a local audio or video file to text using the configured model.

        Supported formats: mp3, mp4, m4a, wav, ogg, webm, mpeg, flac.
        The configured model must support multimodal audio input (e.g. GPT-4o, Gemini 1.5 Pro).
        Maximum file size is controlled by the max_audio_mb setting (default 20 MB).
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return f"Error: file not found: {file_path!r}"
        if not path.is_file():
            return f"Error: path is not a file: {file_path!r}"

        suffix = path.suffix.lower()
        if suffix not in _SUPPORTED_EXTS:
            supported = ", ".join(sorted(_SUPPORTED_EXTS))
            return f"Error: unsupported format {suffix!r}. Supported: {supported}"

        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > config.max_audio_mb:
            return (
                f"Error: file is {size_mb:.1f} MB, exceeds {config.max_audio_mb} MB limit. "
                "Please provide a shorter clip or compress the audio."
            )

        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type:
            mime_type = _FALLBACK_MIME.get(suffix, "application/octet-stream")

        model_str = config.transcription_model or ctx.role.spec.model.to_model_string()
        try:
            agent = Agent(model_str)
            result = agent.run_sync(
                [
                    "Transcribe this audio verbatim. Return only the transcript text.",
                    BinaryContent(data=path.read_bytes(), media_type=mime_type),
                ]
            )
            text = str(result.output)
        except Exception as exc:
            return f"Error: {exc}"

        if len(text) > config.max_transcript_chars:
            text = text[: config.max_transcript_chars] + "\n[truncated]"
        return text

    return toolset
