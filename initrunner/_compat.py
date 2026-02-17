"""Optional dependency helpers with actionable error messages."""

from __future__ import annotations

import importlib

_PROVIDER_PACKAGES: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google.generativeai",
    "groq": "groq",
    "mistral": "mistralai",
    "cohere": "cohere",
}

_PROVIDER_EXTRAS: dict[str, str] = {
    "anthropic": "anthropic",
    "google": "google",
    "groq": "groq",
    "mistral": "mistral",
    "cohere": "all-models",
}

_INGEST_PACKAGES: dict[str, str] = {
    "pymupdf4llm": "pymupdf4llm",
    "docx": "python-docx",
    "openpyxl": "openpyxl",
}


def require_provider(provider: str) -> None:
    """Check that the SDK for *provider* is importable, or raise with install hint."""
    if provider in ("openai", "ollama"):
        return  # openai SDK always available with core install; ollama uses it
    module = _PROVIDER_PACKAGES.get(provider)
    if module is None:
        raise RuntimeError(f"Unknown provider '{provider}'")
    try:
        importlib.import_module(module)
    except ImportError:
        extra = _PROVIDER_EXTRAS.get(provider, "all-models")
        raise RuntimeError(
            f"Provider '{provider}' requires: pip install initrunner[{extra}]"
        ) from None


def require_observability() -> None:
    """Check that opentelemetry-sdk is importable, or raise with install hint."""
    try:
        importlib.import_module("opentelemetry.sdk")
    except ImportError:
        raise RuntimeError(
            "OpenTelemetry observability requires: pip install initrunner[observability]"
        ) from None


def require_ingest(package: str) -> None:
    """Check that a heavy ingest dependency is importable, or raise with install hint."""
    try:
        importlib.import_module(package)
    except ImportError:
        pip_name = _INGEST_PACKAGES.get(package, package)
        raise RuntimeError(
            f"'{pip_name}' is required for this file type: pip install initrunner[ingest]"
        ) from None
