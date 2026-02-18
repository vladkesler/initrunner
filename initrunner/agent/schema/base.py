"""Base types shared across schema sub-modules."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field

from initrunner import __version__

_USER_AGENT = f"initrunner/{__version__}"


class ApiVersion(StrEnum):
    V1 = "initrunner/v1"


class Kind(StrEnum):
    AGENT = "Agent"


class Metadata(BaseModel):
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")]
    description: str = ""
    tags: list[str] = []
    author: str = ""
    version: str = ""
    dependencies: list[str] = []


class ModelConfig(BaseModel):
    provider: str
    name: str
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.1
    max_tokens: Annotated[int, Field(ge=1, le=128000)] = 4096

    def to_model_string(self) -> str:
        return f"{self.provider}:{self.name}"

    def needs_custom_provider(self) -> bool:
        return self.provider == "ollama" or self.base_url is not None
