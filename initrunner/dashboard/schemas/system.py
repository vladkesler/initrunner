"""System health, doctor, provider config, and key management models."""

from __future__ import annotations

from pydantic import BaseModel

from initrunner.dashboard.schemas._common import ProviderStatus

__all__ = [
    "DefaultModelResponse",
    "DoctorCheck",
    "DoctorResponse",
    "HealthResponse",
    "ProviderResponse",
    "ProviderStatusResponse",
    "SaveDefaultModelRequest",
    "SaveKeyRequest",
    "SaveKeyResponse",
    "ToolTypeResponse",
]


class ProviderResponse(BaseModel):
    provider: str
    model: str


class HealthResponse(BaseModel):
    status: str
    version: str


class DoctorCheck(BaseModel):
    name: str
    status: str  # "ok" | "warn" | "fail"
    message: str


class DoctorResponse(BaseModel):
    checks: list[DoctorCheck]
    embedding_checks: list[DoctorCheck] = []


class ToolTypeResponse(BaseModel):
    name: str
    description: str


class DefaultModelResponse(BaseModel):
    """Current default model with provenance."""

    provider: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None
    source: str  # "initrunner_model_env" | "run_yaml" | "auto_detected" | "none"


class SaveDefaultModelRequest(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None


# -- Key management ------------------------------------------------------------


class SaveKeyRequest(BaseModel):
    provider: str | None = None  # standard provider name (e.g. "openai", "anthropic")
    preset: str | None = None  # e.g. "openrouter" -- uses known env var name
    base_url: str | None = None  # for custom -- derives env var name from URL
    api_key: str
    verify: bool = False  # attempt real API call validation (openai/anthropic only)


class SaveKeyResponse(BaseModel):
    env_var: str
    validated: bool = False
    validation_supported: bool = False


class ProviderStatusResponse(BaseModel):
    providers: list[ProviderStatus]
    detected_provider: str | None = None
    detected_model: str | None = None
