"""Media tool configurations: audio, image generation."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from initrunner.agent.schema.tools._base import ToolConfigBase


class AudioToolConfig(ToolConfigBase):
    type: Literal["audio"] = "audio"
    youtube_languages: list[str] = ["en"]
    include_timestamps: bool = False
    transcription_model: str | None = None
    max_audio_mb: float = 20.0
    max_transcript_chars: int = 50_000

    def summary(self) -> str:
        return "audio"


class ImageGenToolConfig(ToolConfigBase):
    type: Literal["image_gen"] = "image_gen"
    provider: Literal["openai", "stability"] = "openai"
    api_key_env: str = ""
    default_size: str = "1024x1024"
    default_quality: str = "standard"
    default_style: str = "natural"
    output_dir: str = ""
    input_root: str = ""
    model: str = ""
    timeout_seconds: int = 120

    @model_validator(mode="after")
    def _default_api_key(self) -> ImageGenToolConfig:
        if not self.api_key_env and self.provider == "openai":
            self.api_key_env = "${OPENAI_API_KEY}"
        return self

    def summary(self) -> str:
        return f"image_gen: {self.provider}"
