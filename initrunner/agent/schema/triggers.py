"""Trigger configuration models (discriminated union)."""

from __future__ import annotations

import secrets
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, PrivateAttr, model_validator


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
    _secret_from_user: bool = PrivateAttr(default=False)

    @model_validator(mode="after")
    def _auto_generate_secret(self) -> WebhookTriggerConfig:
        if self.secret is None:
            self._secret_from_user = False
            self.secret = secrets.token_urlsafe(32)
        else:
            self._secret_from_user = True
        return self

    def summary(self) -> str:
        return f"webhook: :{self.port}{self.path}"

    def omit_generated_secret(self, dumped: dict) -> None:
        """Drop auto-generated secrets so rewrites do not invent one."""
        if not self._secret_from_user:
            dumped.pop("secret", None)


class TelegramTriggerConfig(BaseModel):
    type: Literal["telegram"] = "telegram"
    token_env: str = "TELEGRAM_BOT_TOKEN"
    allowed_users: list[str] = []
    allowed_user_ids: list[int] = []
    allow_all: bool = False
    prompt_template: str = "{message}"
    autonomous: bool = False

    def summary(self) -> str:
        parts: list[str] = []
        if self.allowed_users:
            parts.append("users=" + ", ".join(self.allowed_users))
        if self.allowed_user_ids:
            parts.append("user_ids=" + ", ".join(str(i) for i in self.allowed_user_ids))
        return f"telegram: {'; '.join(parts)}" if parts else "telegram: users=all"


class DiscordTriggerConfig(BaseModel):
    type: Literal["discord"] = "discord"
    token_env: str = "DISCORD_BOT_TOKEN"
    channel_ids: list[str] = []
    allowed_roles: list[str] = []
    allowed_user_ids: list[str] = []
    allow_all: bool = False
    prompt_template: str = "{message}"
    autonomous: bool = False

    def summary(self) -> str:
        parts: list[str] = []
        if self.channel_ids:
            parts.append("channels=" + ", ".join(self.channel_ids))
        if self.allowed_roles:
            parts.append("roles=" + ", ".join(self.allowed_roles))
        if self.allowed_user_ids:
            parts.append("user_ids=" + ", ".join(self.allowed_user_ids))
        return f"discord: {'; '.join(parts)}" if parts else "discord: all channels (mention/DM)"


class SlackTriggerConfig(BaseModel):
    type: Literal["slack"] = "slack"
    app_token_env: str = "SLACK_APP_TOKEN"
    bot_token_env: str = "SLACK_BOT_TOKEN"
    channel_ids: list[str] = []
    allowed_user_ids: list[str] = []
    allow_all: bool = False
    respond_in_thread: bool = True
    prompt_template: str = "{message}"
    autonomous: bool = False

    def summary(self) -> str:
        parts: list[str] = []
        if self.channel_ids:
            parts.append("channels=" + ", ".join(self.channel_ids))
        if self.allowed_user_ids:
            parts.append("user_ids=" + ", ".join(self.allowed_user_ids))
        return f"slack: {'; '.join(parts)}" if parts else "slack: all channels (mention/DM)"


class HeartbeatTriggerConfig(BaseModel):
    type: Literal["heartbeat"] = "heartbeat"
    file: str
    interval_seconds: int = Field(default=3600, gt=0)
    prompt_prefix: str = (
        "You are processing a periodic task checklist. "
        "Review all items below and work through any that are not yet complete. "
        "Use your tools as needed. Report what you did for each item."
    )
    active_hours: list[int] | None = None
    timezone: str = "UTC"
    autonomous: bool = False

    @model_validator(mode="after")
    def _validate_active_hours(self) -> HeartbeatTriggerConfig:
        if self.active_hours is not None:
            if len(self.active_hours) != 2:
                raise ValueError("active_hours must be a list of exactly 2 integers [start, end]")
            for h in self.active_hours:
                if not (0 <= h <= 23):
                    raise ValueError(f"active_hours values must be 0-23, got {h}")
        return self

    @model_validator(mode="after")
    def _validate_timezone(self) -> HeartbeatTriggerConfig:
        try:
            ZoneInfo(self.timezone)
        except (KeyError, Exception) as exc:
            raise ValueError(f"Invalid timezone: {self.timezone!r}") from exc
        return self

    def summary(self) -> str:
        return f"heartbeat: {self.file} every {self.interval_seconds}s"


TriggerConfig = Annotated[
    CronTriggerConfig
    | FileWatchTriggerConfig
    | WebhookTriggerConfig
    | TelegramTriggerConfig
    | DiscordTriggerConfig
    | SlackTriggerConfig
    | HeartbeatTriggerConfig,
    Field(discriminator="type"),
]
