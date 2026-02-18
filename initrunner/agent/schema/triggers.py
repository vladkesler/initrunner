"""Trigger configuration models (discriminated union)."""

from __future__ import annotations

import secrets
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class CronTriggerConfig(BaseModel):
    type: Literal["cron"] = "cron"
    schedule: str
    prompt: str
    timezone: str = "UTC"
    autonomous: bool = False

    def summary(self) -> str:
        return f"cron: {self.schedule}"


class FileWatchTriggerConfig(BaseModel):
    type: Literal["file_watch"] = "file_watch"
    paths: list[str]
    extensions: list[str] = []
    prompt_template: str = "File changed: {path}"
    debounce_seconds: float = 1.0
    process_existing: bool = False
    autonomous: bool = False

    def summary(self) -> str:
        return f"file_watch: {', '.join(self.paths)}"


class WebhookTriggerConfig(BaseModel):
    type: Literal["webhook"] = "webhook"
    path: str = "/webhook"
    port: int = 8080
    method: str = "POST"
    secret: str | None = None
    rate_limit_rpm: int = 60
    autonomous: bool = False

    @model_validator(mode="after")
    def _auto_generate_secret(self) -> WebhookTriggerConfig:
        if self.secret is None:
            self.secret = secrets.token_urlsafe(32)
        return self

    def summary(self) -> str:
        return f"webhook: :{self.port}{self.path}"


TriggerConfig = Annotated[
    CronTriggerConfig | FileWatchTriggerConfig | WebhookTriggerConfig,
    Field(discriminator="type"),
]
