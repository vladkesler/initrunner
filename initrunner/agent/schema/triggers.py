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


class TelegramTriggerConfig(BaseModel):
    type: Literal["telegram"] = "telegram"
    token_env: str = "TELEGRAM_BOT_TOKEN"
    allowed_users: list[str] = []
    prompt_template: str = "{message}"
    autonomous: bool = False

    def summary(self) -> str:
        users = ", ".join(self.allowed_users) if self.allowed_users else "all"
        return f"telegram: users={users}"


class DiscordTriggerConfig(BaseModel):
    type: Literal["discord"] = "discord"
    token_env: str = "DISCORD_BOT_TOKEN"
    channel_ids: list[str] = []
    allowed_roles: list[str] = []
    prompt_template: str = "{message}"
    autonomous: bool = False

    def summary(self) -> str:
        if self.channel_ids:
            return f"discord: channels={', '.join(self.channel_ids)}"
        return "discord: all channels (mention/DM)"


TriggerConfig = Annotated[
    CronTriggerConfig
    | FileWatchTriggerConfig
    | WebhookTriggerConfig
    | TelegramTriggerConfig
    | DiscordTriggerConfig,
    Field(discriminator="type"),
]
