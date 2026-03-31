"""Communication tool configurations: Slack, email."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from initrunner.agent.schema.tools._base import ToolConfigBase


class SlackToolConfig(ToolConfigBase):
    type: Literal["slack"] = "slack"
    webhook_url: str
    default_channel: str | None = None
    username: str | None = None
    icon_emoji: str | None = None
    timeout_seconds: int = 30
    max_response_bytes: int = 1024

    def summary(self) -> str:
        return "slack: webhook"


class EmailToolConfig(ToolConfigBase):
    type: Literal["email"] = "email"
    imap_host: str
    smtp_host: str = ""
    imap_port: int = 993
    smtp_port: int = 587
    username: str
    password: str
    use_ssl: bool = True
    default_folder: str = "INBOX"
    read_only: bool = True
    max_results: int = 20
    max_body_chars: int = 50_000
    timeout_seconds: int = 30

    @model_validator(mode="after")
    def _validate_smtp_for_write(self) -> EmailToolConfig:
        if not self.read_only and not self.smtp_host:
            raise ValueError("smtp_host is required when read_only is false")
        return self

    def summary(self) -> str:
        return f"email: {self.imap_host} (ro={self.read_only})"
