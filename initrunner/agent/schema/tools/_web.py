"""Web tool configurations: HTTP, web reader, web scraper, search."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from initrunner.agent.schema.base import _USER_AGENT
from initrunner.agent.schema.tools._base import ToolConfigBase


class HttpToolConfig(ToolConfigBase):
    type: Literal["http"] = "http"
    base_url: str
    allowed_methods: list[str] = ["GET"]
    headers: dict[str, str] = {}

    def summary(self) -> str:
        return f"http: {self.base_url}"


class WebReaderToolConfig(ToolConfigBase):
    type: Literal["web_reader"] = "web_reader"
    allowed_domains: list[str] = []
    blocked_domains: list[str] = []
    max_content_bytes: int = 512_000
    timeout_seconds: int = 15
    user_agent: str = _USER_AGENT

    def summary(self) -> str:
        if self.allowed_domains:
            return f"web_reader: {', '.join(self.allowed_domains[:3])}"
        return "web_reader"


class WebScraperToolConfig(ToolConfigBase):
    type: Literal["web_scraper"] = "web_scraper"
    allowed_domains: list[str] = []
    blocked_domains: list[str] = []
    max_content_bytes: int = 512_000
    timeout_seconds: int = 15
    user_agent: str = _USER_AGENT

    def summary(self) -> str:
        if self.allowed_domains:
            return f"web_scraper: {', '.join(self.allowed_domains[:3])}"
        return "web_scraper"


class SearchToolConfig(ToolConfigBase):
    type: Literal["search"] = "search"
    provider: Literal["duckduckgo", "serpapi", "brave", "tavily"] = "duckduckgo"
    api_key: str = ""
    max_results: int = 10
    safe_search: bool = True
    timeout_seconds: int = 15

    @model_validator(mode="after")
    def _validate_api_key_for_paid(self) -> SearchToolConfig:
        if self.provider != "duckduckgo" and not self.api_key:
            raise ValueError(f"provider '{self.provider}' requires 'api_key'")
        return self

    def summary(self) -> str:
        return f"search: {self.provider}"
