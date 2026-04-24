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
    team: str = ""
    version: str = ""
    dependencies: list[str] = []
    bundle: BundleConfig | None = None


class RoleMetadata(Metadata):
    spec_version: int = 1


def _split_provider_and_name(spec: str) -> tuple[str, str]:
    """Resolve ``spec`` (``provider:model`` or an alias) to ``(provider, name)``.

    Returns ``("", spec)`` when the input is neither a ``provider:model``
    string nor a known alias.  Callers decide how to handle the unresolved
    case (e.g. model auto-detection vs. hard error).
    """
    if ":" in spec:
        prov, model_name = spec.split(":", 1)
        return prov, model_name
    from initrunner.model_aliases import resolve_model_alias

    resolved = resolve_model_alias(spec)
    if ":" in resolved:
        prov, model_name = resolved.split(":", 1)
        return prov, model_name
    return "", spec


class PartialModelConfig(BaseModel):
    """YAML-facing model config. Provider and name may be omitted for auto-detection."""

    provider: str = ""
    name: str = ""
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.1
    max_tokens: Annotated[int, Field(ge=1, le=128000)] = 4096
    context_window: Annotated[int, Field(gt=0)] | None = None
    fallback: list[str] = []

    def is_resolved(self) -> bool:
        """Return True when both provider and name are set."""
        return bool(self.provider and self.name)

    def to_model_string(self) -> str:
        return f"{self.provider}:{self.name}"

    def needs_custom_provider(self) -> bool:
        return self.provider == "ollama" or self.base_url is not None

    @model_validator(mode="after")
    def _check_fallbacks_resolvable(self) -> PartialModelConfig:
        """Each fallback entry must resolve to a non-Ollama ``provider:model`` pair.

        Ollama (and any other provider that needs a custom ``base_url``) is
        rejected because fallback entries are bare strings -- they cannot
        carry the extra config needed to reach a local or self-hosted
        endpoint.  Aliases defined in ``~/.initrunner/models.yaml`` are
        resolved inline.
        """
        for entry in self.fallback:
            prov, _ = _split_provider_and_name(entry)
            if not prov:
                raise ValueError(
                    f"Could not resolve fallback model '{entry}'. "
                    f"Use 'provider:model' or add an alias to ~/.initrunner/models.yaml."
                )
            if prov == "ollama":
                raise ValueError(
                    f"Fallback model '{entry}' targets Ollama, which requires a custom "
                    f"base_url. Fallback entries must be standard providers "
                    f"(anthropic, openai, google, groq, mistral, cohere, xai, ...)."
                )
        return self

    def is_reasoning_model(self) -> bool:
        """Return True for OpenAI models that drop sampling params when reasoning is active.

        Mirrors pydantic_ai's openai_model_profile() reasoning detection:
        - o-series (any model starting with 'o') always uses reasoning
        - gpt-5 (excluding gpt-5.1+/gpt-5.2+ and gpt-5-chat) always uses reasoning
        - gpt-5.1+ defaults to reasoning_effort='none' so sampling params are allowed
        """
        if not self.provider or self.provider.lower() != "openai":
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


class ModelConfig(PartialModelConfig):
    """Concrete runtime model config. Provider and name are guaranteed non-empty."""

    name: str  # override: required (no default)

    @model_validator(mode="before")
    @classmethod
    def _resolve_alias_or_split(cls, data: dict) -> dict:  # type: ignore[type-arg]
        if not isinstance(data, dict):
            return data
        if data.get("provider"):
            return data
        prov, model_name = _split_provider_and_name(data.get("name", ""))
        if prov:
            data["provider"] = prov
            data["name"] = model_name
        # else: leave provider empty -- _check_provider_resolved will catch it
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
