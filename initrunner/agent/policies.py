"""Content validation, output filtering, and PII redaction."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_ai.models import Model

if TYPE_CHECKING:
    from initrunner.agent.schema import ContentPolicy

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in PII patterns
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # email
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN
    re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),  # phone
    re.compile(r"\b(?:sk-|pk-|api[_-]?key[_\s:=]*)[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),  # API keys
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    valid: bool
    reason: str = ""
    validator: str = ""


# ---------------------------------------------------------------------------
# Input validation pipeline
# ---------------------------------------------------------------------------


def _validate_fast_checks(prompt: str, policy: ContentPolicy) -> ValidationResult | None:
    """Run profanity, pattern, and length checks. Returns None if all pass."""
    # Layer 1a: Profanity filter
    if policy.profanity_filter:
        result = _check_profanity(prompt)
        if not result.valid:
            return result

    # Layer 1b: Blocked input patterns
    for pattern in policy.blocked_input_patterns:
        if re.search(pattern, prompt, re.IGNORECASE):
            return ValidationResult(
                valid=False,
                reason=f"Input matches blocked pattern: {pattern}",
                validator="pattern",
            )

    # Layer 1c: Prompt length
    if len(prompt) > policy.max_prompt_length:
        return ValidationResult(
            valid=False,
            reason=f"Prompt exceeds maximum length of {policy.max_prompt_length} characters",
            validator="length",
        )

    return None


def validate_input(
    prompt: str,
    policy: ContentPolicy,
    *,
    model_override: Model | str | None = None,
) -> ValidationResult:
    """Synchronous input validation pipeline. Fast checks first, LLM classifier last."""
    result = _validate_fast_checks(prompt, policy)
    if result is not None:
        return result

    # Layer 2: LLM classifier
    if policy.llm_classifier_enabled and policy.allowed_topics_prompt:
        result = _run_llm_classifier_sync(prompt, policy.allowed_topics_prompt, model_override)
        if not result.valid:
            return result

    return ValidationResult(valid=True)


async def validate_input_async(
    prompt: str,
    policy: ContentPolicy,
    *,
    model_override: Model | str | None = None,
) -> ValidationResult:
    """Async input validation pipeline for use in async handlers."""
    result = _validate_fast_checks(prompt, policy)
    if result is not None:
        return result

    # Layer 2: LLM classifier
    if policy.llm_classifier_enabled and policy.allowed_topics_prompt:
        result = await _run_llm_classifier_async(
            prompt, policy.allowed_topics_prompt, model_override
        )
        if not result.valid:
            return result

    return ValidationResult(valid=True)


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------


@dataclass
class OutputResult:
    text: str
    blocked: bool = False
    reason: str = ""


def validate_output(output: str, policy: ContentPolicy) -> OutputResult:
    """Validate and filter agent output based on content policy."""
    if policy.output_action == "block":
        for pattern in policy.blocked_output_patterns:
            if re.search(pattern, output, re.IGNORECASE):
                return OutputResult(
                    text="",
                    blocked=True,
                    reason=f"Output matches blocked pattern: {pattern}",
                )

    elif policy.output_action == "strip":
        for pattern in policy.blocked_output_patterns:
            output = re.sub(pattern, "[FILTERED]", output, flags=re.IGNORECASE)

    # Truncate to max length
    if len(output) > policy.max_output_length:
        output = output[: policy.max_output_length]

    return OutputResult(text=output)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def redact_text(text: str, policy: ContentPolicy) -> str:
    """Redact sensitive content from text for audit logging."""
    # Custom redact patterns
    for pattern in policy.redact_patterns:
        text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)

    # Built-in PII patterns
    if policy.pii_redaction:
        for pii_re in _PII_PATTERNS:
            text = pii_re.sub("[REDACTED]", text)

    return text


# ---------------------------------------------------------------------------
# Profanity filter (optional dep)
# ---------------------------------------------------------------------------


def _check_profanity(text: str) -> ValidationResult:
    """Check for profanity using better-profanity library."""
    try:
        from better_profanity import profanity  # type: ignore[import-not-found]
    except ImportError:
        raise RuntimeError(
            "Profanity filter requires 'better-profanity'. "
            "Install with: pip install initrunner[safety]"
        ) from None

    if profanity.contains_profanity(text):
        return ValidationResult(
            valid=False,
            reason="Input contains profanity",
            validator="profanity",
        )
    return ValidationResult(valid=True)


# ---------------------------------------------------------------------------
# LLM classifier
# ---------------------------------------------------------------------------

_CLASSIFIER_SYSTEM_PROMPT = """\
You are a content policy classifier. Given a policy and user input, \
determine if the input is allowed.
Respond with ONLY a JSON object: {{"is_safe": true/false, "reason": "brief explanation"}}
Do not include any other text."""

# Cache classifier agents by model string to avoid recreating per-call
_classifier_cache: dict[str, object] = {}
_classifier_cache_lock = __import__("threading").Lock()


def _get_classifier_agent(model_override: Model | str | None = None):
    """Return a cached classifier Agent for the given model."""
    from pydantic_ai import Agent
    from pydantic_ai.settings import ModelSettings

    model = model_override or "openai:gpt-4o-mini"
    cache_key = str(model)

    with _classifier_cache_lock:
        if cache_key in _classifier_cache:
            return _classifier_cache[cache_key]

    agent = Agent(
        model,
        system_prompt=_CLASSIFIER_SYSTEM_PROMPT,
        model_settings=ModelSettings(temperature=0.0, max_tokens=200),
    )

    with _classifier_cache_lock:
        _classifier_cache[cache_key] = agent
    return agent


def _run_llm_classifier_sync(
    prompt: str, allowed_topics_prompt: str, model_override: Model | str | None = None
) -> ValidationResult:
    """Run LLM classifier synchronously using run_sync."""
    classifier = _get_classifier_agent(model_override)
    classifier_prompt = f"Policy:\n{allowed_topics_prompt}\n\nUser input:\n{prompt}"
    result = classifier.run_sync(classifier_prompt)
    return _parse_classifier_response(str(result.output))


async def _run_llm_classifier_async(
    prompt: str, allowed_topics_prompt: str, model_override: Model | str | None = None
) -> ValidationResult:
    """Run LLM classifier asynchronously."""
    classifier = _get_classifier_agent(model_override)
    classifier_prompt = f"Policy:\n{allowed_topics_prompt}\n\nUser input:\n{prompt}"
    result = await classifier.run(classifier_prompt)
    return _parse_classifier_response(str(result.output))


def _parse_classifier_response(response: str) -> ValidationResult:
    """Parse the JSON response from the classifier."""
    import json

    try:
        data = json.loads(response)
        if not data.get("is_safe", True):
            return ValidationResult(
                valid=False,
                reason=data.get("reason", "Content policy violation"),
                validator="llm_classifier",
            )
    except (json.JSONDecodeError, KeyError):
        _logger.warning("Classifier returned unparseable response: %s", response[:200])
        return ValidationResult(
            valid=False,
            reason="Classifier returned unparseable response — rejecting input",
            validator="llm_classifier",
        )
    return ValidationResult(valid=True, reason="", validator="llm_classifier")
