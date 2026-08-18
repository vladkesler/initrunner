"""Convert between InitRunner prompts/output and A2A 1.0 Parts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from a2a.helpers.proto_helpers import new_data_part, new_text_part  # type: ignore[import-not-found]
from a2a.types import Message, Part  # type: ignore[import-not-found]
from google.protobuf.json_format import MessageToDict, ParseDict
from pydantic_ai.messages import AudioUrl, BinaryContent, DocumentUrl, ImageUrl, VideoUrl

from initrunner.agent.prompt import _MAX_FILE_SIZE as MAX_INBOUND_BYTES
from initrunner.agent.prompt import (
    UserPrompt,
    _build_url_content,
)

INPUT_MODES = [
    "text/plain",
    "application/json",
    "image/*",
    "audio/*",
    "video/*",
    "application/pdf",
    "application/octet-stream",
]


class PartTooLargeError(ValueError):
    """Raised when an inbound raw part exceeds the file size cap."""


def output_to_parts(output: Any) -> list[Part]:
    """Serialize agent output as A2A parts for both the artifact and status message.

    Strings become a single text part. Structured values become a data part
    whose ``metadata.json_schema`` is the Pydantic serialization schema.
    """
    if isinstance(output, str):
        return [new_text_part(output)]

    from pydantic import TypeAdapter

    adapter = TypeAdapter(type(output))
    part = new_data_part(adapter.dump_python(output, mode="json"))
    ParseDict(
        {"json_schema": adapter.json_schema(mode="serialization")},
        part.metadata,
    )
    return [part]


def _url_part_to_content(part: Part) -> ImageUrl | AudioUrl | VideoUrl | DocumentUrl:
    media_type = (part.media_type or "").lower()
    if media_type.startswith("image/"):
        return ImageUrl(url=part.url)
    if media_type.startswith("audio/"):
        return AudioUrl(url=part.url)
    if media_type.startswith("video/"):
        return VideoUrl(url=part.url)
    if media_type:
        return DocumentUrl(url=part.url)
    content = _build_url_content(part.url)
    assert isinstance(content, ImageUrl | AudioUrl | VideoUrl | DocumentUrl)
    return content


def parts_to_prompt(parts: Sequence[Part]) -> UserPrompt:
    """Map inbound A2A parts to a PydanticAI prompt.

    Text and data parts are joined as text. URL parts become ImageUrl /
    AudioUrl / VideoUrl / DocumentUrl (media type first, then extension).
    Raw parts become ``BinaryContent`` and are rejected above 20 MB.
    Returns a plain ``str`` when the message is text-only.
    """
    texts: list[str] = []
    extras: list[Any] = []
    for part in parts:
        if part.HasField("text"):
            if part.text:
                texts.append(part.text)
        elif part.HasField("url"):
            extras.append(_url_part_to_content(part))
        elif part.HasField("raw"):
            if len(part.raw) > MAX_INBOUND_BYTES:
                raise PartTooLargeError(
                    f"Raw part exceeds {MAX_INBOUND_BYTES // (1024 * 1024)} MB cap"
                )
            extras.append(
                BinaryContent(
                    data=bytes(part.raw),
                    media_type=part.media_type or "application/octet-stream",
                )
            )
        elif part.HasField("data"):
            texts.append(json.dumps(MessageToDict(part.data)))
    joined = "\n".join(texts)
    if not extras:
        return joined
    content: list[Any] = []
    if joined:
        content.append(joined)
    content.extend(extras)
    return content


def message_to_prompt(message: Message | None) -> UserPrompt:
    """Extract a prompt from an A2A user message, or ``""`` if missing."""
    if message is None:
        return ""
    return parts_to_prompt(message.parts)
