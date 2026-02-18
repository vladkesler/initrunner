"""Sink configuration models (discriminated union)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class WebhookSinkConfig(BaseModel):
    type: Literal["webhook"] = "webhook"
    url: str
    method: str = "POST"
    headers: dict[str, str] = {}
    timeout_seconds: int = 30
    retry_count: int = 0

    def summary(self) -> str:
        return f"webhook: {self.url}"


class FileSinkConfig(BaseModel):
    type: Literal["file"] = "file"
    path: str
    format: Literal["json", "text"] = "json"

    def summary(self) -> str:
        return f"file: {self.path} ({self.format})"


class CustomSinkConfig(BaseModel):
    type: Literal["custom"] = "custom"
    module: str
    function: str

    def summary(self) -> str:
        return f"custom: {self.module}.{self.function}"


SinkConfig = Annotated[
    WebhookSinkConfig | FileSinkConfig | CustomSinkConfig,
    Field(discriminator="type"),
]
