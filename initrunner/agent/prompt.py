"""Multimodal prompt builder for PydanticAI agents.

Converts text + optional file/URL attachments into the ``UserPrompt`` type
accepted by ``agent.run_sync()``.
"""

from __future__ import annotations

import mimetypes
import os
from collections.abc import Sequence
from pathlib import Path

from pydantic_ai.messages import (
    AudioUrl,
    BinaryContent,
    DocumentUrl,
    ImageUrl,
    UserContent,
    VideoUrl,
)

# Type alias matching PydanticAI's run_sync signature
UserPrompt = str | Sequence[UserContent]

_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

# Extension → media type overrides for types mimetypes may not handle well
_MIME_OVERRIDES: dict[str, str] = {
    ".webp": "image/webp",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# Supported extensions grouped by category
_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})
_AUDIO_EXTS = frozenset({".mp3", ".wav", ".ogg", ".flac", ".aac"})
_VIDEO_EXTS = frozenset({".mp4", ".webm", ".mov", ".mkv"})
_BINARY_DOC_EXTS = frozenset({".pdf", ".docx", ".xlsx"})
_TEXT_DOC_EXTS = frozenset({".txt", ".md", ".csv", ".html"})

_ALL_SUPPORTED_EXTS = _IMAGE_EXTS | _AUDIO_EXTS | _VIDEO_EXTS | _BINARY_DOC_EXTS | _TEXT_DOC_EXTS

# URL extension → PydanticAI URL type mapping
_URL_IMAGE_EXTS = _IMAGE_EXTS
_URL_AUDIO_EXTS = _AUDIO_EXTS
_URL_VIDEO_EXTS = _VIDEO_EXTS
_URL_DOC_EXTS = _BINARY_DOC_EXTS | _TEXT_DOC_EXTS

# Category labels for attachment_summary
_CATEGORY_NAMES = {
    "image": "image(s)",
    "audio": "audio",
    "video": "video",
    "document": "document(s)",
    "text": "text file(s)",
}


def _get_media_type(path: str) -> str:
    """Return MIME type for a file path, using overrides then mimetypes."""
    ext = os.path.splitext(path)[1].lower()
    if ext in _MIME_OVERRIDES:
        return _MIME_OVERRIDES[ext]
    mt, _ = mimetypes.guess_type(path)
    return mt or "application/octet-stream"


def _classify_media_type(media_type: str) -> str:
    """Return category ('image', 'audio', 'video', 'document') from a MIME type."""
    if media_type.startswith("image/"):
        return "image"
    if media_type.startswith("audio/"):
        return "audio"
    if media_type.startswith("video/"):
        return "video"
    return "document"


def render_content_as_text(item: UserContent) -> str:
    """Render a single UserContent item as display text."""
    if isinstance(item, str):
        return item
    if isinstance(item, ImageUrl):
        return "[image]"
    if isinstance(item, AudioUrl):
        return "[audio]"
    if isinstance(item, VideoUrl):
        return "[video]"
    if isinstance(item, DocumentUrl):
        return "[document]"
    if isinstance(item, BinaryContent):
        mt = str(item.media_type)
        return f"[{_classify_media_type(mt)}]"
    return ""


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _ext_from_url(url: str) -> str:
    """Extract file extension from URL path (ignoring query params)."""
    from urllib.parse import urlparse

    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext.lower()


def _build_url_content(url: str) -> UserContent:
    """Build the appropriate PydanticAI URL type from a URL string."""
    ext = _ext_from_url(url)
    if ext in _URL_AUDIO_EXTS:
        return AudioUrl(url=url)
    if ext in _URL_VIDEO_EXTS:
        return VideoUrl(url=url)
    if ext in _URL_DOC_EXTS:
        return DocumentUrl(url=url)
    # Default to ImageUrl for image extensions or ambiguous/missing extensions
    return ImageUrl(url=url)


def _build_file_content(file_path: str) -> UserContent | str:
    """Build content from a local file. Returns str for text-readable files."""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Attachment file not found: {file_path}")

    ext = p.suffix.lower()
    if not ext:
        raise ValueError(f"Cannot determine file type — file has no extension: {file_path}")
    if ext not in _ALL_SUPPORTED_EXTS:
        raise ValueError(
            f"Unsupported file type '{ext}' for: {file_path}. "
            f"Supported: {', '.join(sorted(_ALL_SUPPORTED_EXTS))}"
        )

    size = p.stat().st_size
    if size > _MAX_FILE_SIZE:
        raise ValueError(
            f"File too large ({size / 1024 / 1024:.1f} MB): {file_path}. "
            f"Maximum: {_MAX_FILE_SIZE / 1024 / 1024:.0f} MB"
        )

    # Text-readable files: read as UTF-8 and return as str
    if ext in _TEXT_DOC_EXTS:
        return p.read_text(encoding="utf-8")

    # Binary files: read and wrap in BinaryContent
    data = p.read_bytes()
    media_type = _get_media_type(file_path)
    return BinaryContent(data=data, media_type=media_type)


def build_multimodal_prompt(
    text: str,
    attachments: list[str] | None = None,
) -> UserPrompt:
    """Build a prompt from text and optional attachments.

    If no attachments, returns *text* as a plain ``str`` (fully backward
    compatible).  Otherwise builds a ``list[UserContent]`` with the text
    first, then appropriate PydanticAI types for each attachment.

    Raises:
        FileNotFoundError: If a local file attachment does not exist.
        ValueError: If a file is too large, has an unsupported extension,
            has no extension, or a URL is not well-formed.
    """
    if not attachments:
        return text

    parts: list[UserContent] = []
    text_parts: list[str] = [text]

    for attachment in attachments:
        if _is_url(attachment):
            parts.append(_build_url_content(attachment))
        else:
            content = _build_file_content(attachment)
            if isinstance(content, str):
                # Text-readable file — inline into text portion
                text_parts.append(content)
            else:
                parts.append(content)

    # Combine all text parts as the first element
    combined_text = "\n\n".join(text_parts)

    # If all attachments were text files, just return combined text
    if not parts:
        return combined_text

    return [combined_text, *parts]


def extract_text_from_prompt(prompt: UserPrompt) -> str:
    """Extract just the text portions from a prompt.

    Used for audit logging, content validation, and display.
    Returns *prompt* as-is if it's a plain ``str``.
    For sequences, joins all ``str`` parts with newlines.
    """
    if isinstance(prompt, str):
        return prompt

    text_parts: list[str] = []
    for part in prompt:
        if isinstance(part, str):
            text_parts.append(part)
    return "\n".join(text_parts)


def attachment_summary(prompt: UserPrompt) -> str | None:
    """Return a summary like ``"[+2 image(s), +1 document(s)]"`` or None.

    Returns None if the prompt is a plain string (no attachments).
    """
    if isinstance(prompt, str):
        return None

    counts: dict[str, int] = {}
    for part in prompt:
        if isinstance(part, str):
            continue
        if isinstance(part, ImageUrl):
            key = "image"
        elif isinstance(part, AudioUrl):
            key = "audio"
        elif isinstance(part, VideoUrl):
            key = "video"
        elif isinstance(part, DocumentUrl):
            key = "document"
        elif isinstance(part, BinaryContent):
            mt = part.media_type if isinstance(part.media_type, str) else str(part.media_type)
            key = _classify_media_type(mt)
        else:
            continue
        counts[key] = counts.get(key, 0) + 1

    if not counts:
        return None

    segments = []
    for key in ("image", "audio", "video", "document"):
        n = counts.get(key, 0)
        if n > 0:
            segments.append(f"+{n} {_CATEGORY_NAMES[key]}")
    return "[" + ", ".join(segments) + "]"
