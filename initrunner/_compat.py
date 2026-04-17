"""Optional dependency helpers with actionable error messages."""

from __future__ import annotations

import importlib

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class MissingExtraError(RuntimeError):
    """Raised when an optional dependency is not installed."""


# ---------------------------------------------------------------------------
# Unified extra-package mapping
# ---------------------------------------------------------------------------

# module_to_import -> (extra_name, pip_install_name)
_EXTRA_PACKAGES: dict[str, tuple[str, str]] = {
    "ddgs": ("search", "ddgs"),
    "youtube_transcript_api": ("audio", "youtube-transcript-api"),
    "better_profanity": ("safety", "better-profanity"),
    "telegram": ("telegram", "python-telegram-bot"),
    "discord": ("discord", "discord.py"),
    "slack_sdk": ("slack", "slack-sdk"),
    "webview": ("desktop", "pywebview"),
    "fasta2a": ("a2a", "pydantic-ai-slim[a2a]"),
    "cryptography": ("vault", "cryptography"),
    "keyring": ("vault-keyring", "keyring"),
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def require_extra(
    module: str,
    extra: str | None = None,
    pip_name: str | None = None,
) -> None:
    """Check that *module* is importable, or raise ``MissingExtraError``.

    If *extra* and *pip_name* are omitted they are looked up from
    ``_EXTRA_PACKAGES``.  Falls back to a generic hint when the module
    is unknown.
    """
    try:
        importlib.import_module(module)
    except ImportError:
        if extra is None or pip_name is None:
            entry = _EXTRA_PACKAGES.get(module)
            if entry is not None:
                extra = extra or entry[0]
                pip_name = pip_name or entry[1]
        if extra is not None:
            msg = f"'{pip_name or module}' is required: uv pip install initrunner[{extra}]"
        else:
            msg = f"'{pip_name or module}' is required: uv pip install {pip_name or module}"
        raise MissingExtraError(msg) from None


def is_extra_available(module: str) -> bool:
    """Return ``True`` if *module* is importable.  Never raises."""
    try:
        importlib.import_module(module)
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# Provider checks (special-cased: openai/ollama/xai skip logic)
# ---------------------------------------------------------------------------

_PROVIDER_PACKAGES: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google.generativeai",
    "groq": "groq",
    "mistral": "mistralai",
    "cohere": "cohere",
    "bedrock": "boto3",
}

_PROVIDER_EXTRAS: dict[str, str] = {
    "anthropic": "anthropic",
    "google": "google",
    "groq": "groq",
    "mistral": "mistral",
    "cohere": "all-models",
    "bedrock": "all-models",
}


def require_provider(provider: str) -> None:
    """Check that the SDK for *provider* is importable, or raise with install hint."""
    if provider in ("openai", "ollama", "xai"):
        return  # openai SDK always available with core install; ollama and xai use it
    module = _PROVIDER_PACKAGES.get(provider)
    if module is None:
        raise RuntimeError(f"Unknown provider '{provider}'")
    try:
        importlib.import_module(module)
    except ImportError:
        extra = _PROVIDER_EXTRAS.get(provider, "all-models")
        raise RuntimeError(
            f"Provider '{provider}' requires: uv pip install initrunner[{extra}]"
        ) from None


# ---------------------------------------------------------------------------
# Domain-specific wrappers
# ---------------------------------------------------------------------------

_INGEST_PACKAGES: dict[str, str] = {
    "pymupdf4llm": "pymupdf4llm",
    "docx": "python-docx",
    "openpyxl": "openpyxl",
}


def require_observability() -> None:
    """Check that opentelemetry-sdk is importable, or raise with install hint."""
    require_extra("opentelemetry.sdk", extra="observability", pip_name="opentelemetry-sdk")


def require_ingest(package: str) -> None:
    """Check that a heavy ingest dependency is importable, or raise with install hint."""
    pip_name = _INGEST_PACKAGES.get(package, package)
    require_extra(package, extra="ingest", pip_name=pip_name)


def require_a2a() -> None:
    """Check that fasta2a is importable, or raise with install hint."""
    require_extra("fasta2a", extra="a2a", pip_name="pydantic-ai-slim[a2a]")


def is_dashboard_available() -> bool:
    """Return True when the dashboard extras (fastapi + uvicorn) are importable."""
    return is_extra_available("fastapi") and is_extra_available("uvicorn")
