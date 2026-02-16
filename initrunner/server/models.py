"""Pydantic models for the OpenAI chat completions wire format."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ContentPart(BaseModel):
    """Multimodal content part (OpenAI format)."""

    type: str  # "text", "image_url", "input_audio", etc.
    text: str | None = None
    image_url: dict | None = None  # {"url": "..."}
    input_audio: dict | None = None  # {"data": "base64...", "format": "mp3"}


class ChatMessage(BaseModel):
    role: str
    content: str | list[ContentPart] | None = None


class ChatCompletionRequest(BaseModel):
    model: str = ""
    messages: list[ChatMessage] = []
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class Choice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage = Usage()


class DeltaMessage(BaseModel):
    role: str | None = None
    content: str | None = None


class StreamChoice(BaseModel):
    index: int = 0
    delta: DeltaMessage
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[StreamChoice]
    usage: Usage | None = None


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "initrunner"


class ModelListResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo] = Field(default_factory=list)
