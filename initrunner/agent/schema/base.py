"""Base types shared across schema sub-modules."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from initrunner import __version__

_USER_AGENT = f"initrunner/{__version__}"

ThinkingEffort = Literal[False, "minimal", "low", "medium", "high", "xhigh"]
"""Extended-thinking effort levels accepted by ``ModelSettings['thinking']``.

``False`` explicitly disables thinking; the string levels map directly onto
PydanticAI's ``ThinkingLevel``. ``None`` (the field default) leaves the
setting unset so the provider applies its own default.
"""

# PydanticAI exception names accepted in ``model.fallback_on``, mapped to their
# classes in initrunner.agent.loader. ``ModelAPIError`` is the base for API/HTTP
# failures (PydanticAI's own default); the rest narrow or broaden the trigger.
FALLBACK_ON_EXCEPTIONS = frozenset(
    {"ModelAPIError", "ModelHTTPError", "UnexpectedModelBehavior", "ContentFilterError"}
)


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


class ModelConcurrencyConfig(BaseModel):
    """Cap concurrent model requests, optionally sharing the cap across agents.

    Maps to PydanticAI's ``ConcurrencyLimitedModel`` + ``ConcurrencyLimiter``.
    Distinct from ``execution.max_concurrency``, which bounds an agent's
    parallel *tool* execution. This bounds in-flight *model requests* -- useful
    when several agents in one process (compose services, team personas, flow
    nodes) share a provider rate-limit budget.
    """

    max_running: Annotated[int, Field(ge=1)]
    """Maximum concurrent in-flight model requests."""
    max_queued: Annotated[int, Field(ge=0)] | None = None
    """Maximum requests allowed to wait; excess is rejected. ``None`` = unbounded."""
    share: str | None = None
    """Name of a shared limiter. Agents (in the same process) whose model config
    uses the same ``share`` name coordinate against one combined budget. Without
    a name, the cap is per-agent."""


class PromptCacheConfig(BaseModel):
    """Provider-native prompt caching for the static prefix of a request.

    Maps to Anthropic's ``anthropic_cache_*`` and Bedrock's ``bedrock_cache_*``
    model settings. Caching the system instructions and tool definitions lets
    repeated runs of a role (daemons, triggers, REPLs) reuse the cached prefix,
    cutting input-token cost. Only ``anthropic`` and ``bedrock`` support it.
    """

    instructions: bool = True
    """Cache the system instructions (role prompt + skill prompts)."""
    tools: bool = True
    """Cache the tool definitions block."""
    ttl: Literal["5m", "1h"] = "5m"
    """Cache time-to-live. ``1h`` needs provider support for extended caching."""


class PartialModelConfig(BaseModel):
    """YAML-facing model config. Provider and name may be omitted for auto-detection."""

    provider: str = ""
    name: str = ""
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.1
    max_tokens: Annotated[int, Field(ge=1, le=128000)] = 4096
    context_window: Annotated[int, Field(gt=0)] | None = None
    concurrency: ModelConcurrencyConfig | None = None
    fallback: list[str] = []
    fallback_on: list[str] = []
    """Exception types that trigger failover to the next fallback model. Names
    from PydanticAI's exceptions (``ModelAPIError``, ``ModelHTTPError``,
    ``UnexpectedModelBehavior``, ``ContentFilterError``). Empty uses PydanticAI's
    default (``ModelAPIError``). Only valid when ``fallback`` is set."""
    prompt_cache: PromptCacheConfig | None = None
    """Provider-native prompt caching. ``prompt_cache: true`` enables caching
    of instructions and tool definitions; a mapping tunes it. Anthropic and
    Bedrock only."""
    top_p: Annotated[float, Field(gt=0.0, le=1.0)] | None = None
    top_k: Annotated[int, Field(ge=1)] | None = None
    seed: int | None = None
    stop_sequences: list[str] | None = None
    parallel_tool_calls: bool | None = None
    presence_penalty: Annotated[float, Field(ge=-2.0, le=2.0)] | None = None
    frequency_penalty: Annotated[float, Field(ge=-2.0, le=2.0)] | None = None
    logit_bias: dict[str, int] | None = None
    extra_headers: dict[str, str] | None = None
    extra_body: dict[str, object] | None = None
    tool_choice: Literal["auto", "none"] | None = None
    """Static tool-choice policy passed to ``ModelSettings['tool_choice']``.

    Only ``auto`` (provider default) and ``none`` (text-only mode, tools
    disabled) are valid here: PydanticAI rejects a static ``required`` or
    tool-name list because it would lock every step into a tool call and
    prevent a final response. Per-step forcing needs a dynamic capability.
    """
    thinking: ThinkingEffort | None = None
    """Native extended-thinking effort. Maps to ``ModelSettings['thinking']``.

    Only supported on reasoning-capable OpenAI models (the o-series and the
    gpt-5 family). Leave unset to use the provider default. This is distinct
    from ``spec.reasoning``, which orchestrates InitRunner's cross-turn
    reasoning patterns rather than model-level thinking.
    """

    @model_validator(mode="before")
    @classmethod
    def _explain_dynamic_tool_choice(cls, data: dict) -> dict:  # type: ignore[type-arg]
        if isinstance(data, dict) and (
            data.get("tool_choice") == "required" or isinstance(data.get("tool_choice"), list)
        ):
            raise ValueError(
                "tool_choice: 'required' and tool-name lists cannot be set statically -- "
                "they would force a tool call on every step and prevent a final response. "
                "Use 'auto' or 'none' here; per-step forcing requires a dynamic capability."
            )
        return data

    @model_validator(mode="before")
    @classmethod
    def _coerce_prompt_cache_shorthand(cls, data: dict) -> dict:  # type: ignore[type-arg]
        """Allow ``prompt_cache: true`` as shorthand for the default config."""
        if isinstance(data, dict):
            value = data.get("prompt_cache")
            if value is True:
                data = {**data, "prompt_cache": {}}
            elif value is False:
                data = {**data, "prompt_cache": None}
        return data

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

    @model_validator(mode="after")
    def _check_fallback_on(self) -> PartialModelConfig:
        """Validate ``fallback_on`` names and require ``fallback`` to be set."""
        if not self.fallback_on:
            return self
        if not self.fallback:
            raise ValueError(
                "fallback_on has no effect without fallback models. "
                "Add a 'fallback' list or remove 'fallback_on'."
            )
        unknown = [n for n in self.fallback_on if n not in FALLBACK_ON_EXCEPTIONS]
        if unknown:
            raise ValueError(
                f"Unknown fallback_on exception(s): {unknown}. "
                f"Valid names: {sorted(FALLBACK_ON_EXCEPTIONS)}."
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

    def supports_thinking(self) -> bool:
        """Return True for OpenAI models that accept a native ``thinking`` setting.

        Covers the whole reasoning-capable OpenAI surface: every o-series
        model and the entire gpt-5 family (including gpt-5.1+, which accepts a
        reasoning_effort). The non-chat restriction matches the providers that
        actually honor the thinking knob -- ``gpt-5-chat`` does not.
        """
        if not self.provider or self.provider.lower() != "openai":
            return False
        name = self.name.lower()
        if name.startswith("o"):
            return True
        return name.startswith("gpt-5") and "gpt-5-chat" not in name

    @model_validator(mode="after")
    def _check_thinking_supported(self) -> PartialModelConfig:
        """Reject ``thinking`` on providers/models that do not support it.

        Skips the check when provider or name is still empty (a partial config
        awaiting auto-detection) so resolution can fill them in first.
        """
        if self.thinking is None:
            return self
        if not self.provider or not self.name:
            return self
        if not self.supports_thinking():
            raise ValueError(
                f"thinking is only supported on reasoning-capable OpenAI models "
                f"(the o-series and the gpt-5 family), not '{self.provider}:{self.name}'. "
                f"Remove the thinking field or switch to a supported model."
            )
        return self

    def supports_prompt_cache(self) -> bool:
        """Return True for providers with native prompt-cache settings."""
        return self.provider.lower() in ("anthropic", "bedrock")

    @model_validator(mode="after")
    def _check_prompt_cache_supported(self) -> PartialModelConfig:
        """Reject ``prompt_cache`` on providers without native cache settings.

        Skips the check when the provider is still empty (a partial config
        awaiting auto-detection).
        """
        if self.prompt_cache is None:
            return self
        if not self.provider:
            return self
        if not self.supports_prompt_cache():
            raise ValueError(
                f"prompt_cache is only supported on Anthropic and Bedrock, not "
                f"'{self.provider}'. Remove prompt_cache or switch providers."
            )
        return self


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
