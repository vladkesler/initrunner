"""Base types shared across schema sub-modules."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from initrunner import __version__

_USER_AGENT = f"initrunner/{__version__}"


class ApiVersion(StrEnum):
    V1 = "initrunner/v1"


class Kind(StrEnum):
    AGENT = "Agent"


class BundleConfig(BaseModel):
    """Extra files to include in OCI bundles (glob patterns relative to role dir)."""

    include: list[str] = []


class Metadata(BaseModel):
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")]
    description: str = ""
    tags: list[str] = []
    author: str = ""
    version: str = ""
    dependencies: list[str] = []
    bundle: BundleConfig | None = None


class ModelConfig(BaseModel):
    provider: str = ""
    name: str
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.1
    max_tokens: Annotated[int, Field(ge=1, le=128000)] = 4096

    @model_validator(mode="before")
    @classmethod
    def _resolve_alias_or_split(cls, data: dict) -> dict:  # type: ignore[type-arg]
        if not isinstance(data, dict):
            return data
        provider = data.get("provider", "")
        name = data.get("name", "")
        if provider:
            # Explicit provider — no alias resolution
            return data
        # No provider: resolve alias or split on colon
        if ":" in name:
            prov, model_name = name.split(":", 1)
            data["provider"] = prov
            data["name"] = model_name
        else:
            # Could be an alias — resolve lazily
            from initrunner.model_aliases import resolve_model_alias

            resolved = resolve_model_alias(name)
            if ":" in resolved:
                prov, model_name = resolved.split(":", 1)
                data["provider"] = prov
                data["name"] = model_name
            # else: leave provider empty — after-validator will catch it
        return data

    @model_validator(mode="after")
    def _check_provider_resolved(self) -> ModelConfig:
        if not self.provider:
            raise ValueError(
                f"Could not resolve provider for model '{self.name}'. "
                f"Either specify 'provider' explicitly, use 'provider:model' format, "
                f"or add an alias to ~/.initrunner/models.yaml"
            )
        return self

    def to_model_string(self) -> str:
        return f"{self.provider}:{self.name}"

    def needs_custom_provider(self) -> bool:
        return self.provider == "ollama" or self.base_url is not None

    def is_reasoning_model(self) -> bool:
        """Return True for OpenAI models that drop sampling params when reasoning is active.

        Mirrors pydantic_ai's openai_model_profile() reasoning detection:
        - o-series (any model starting with 'o') always uses reasoning
        - gpt-5 (excluding gpt-5.1+/gpt-5.2+ and gpt-5-chat) always uses reasoning
        - gpt-5.1+ defaults to reasoning_effort='none' so sampling params are allowed
        """
        if self.provider.lower() != "openai":
            return False
        name = self.name.lower()
        if name.startswith("o"):
            return True
        if (
            name.startswith("gpt-5")
            and not name.startswith(("gpt-5.1", "gpt-5.2"))
            and "gpt-5-chat" not in name
        ):
            return True
        return False
