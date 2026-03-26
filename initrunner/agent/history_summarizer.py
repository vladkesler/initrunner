"""Token-aware context budget guard for message history.

Provides a PydanticAI ``HistoryProcessor`` that prevents context window
overflow by truncating oversized parts and dropping oldest message pairs
when estimated tokens exceed the budget.  The same reducer is used both
as a pre-request history processor (permanent -- PydanticAI writes
processed history back into run state) and by ``reduce_history()``
between autonomous/daemon iterations.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
)

if TYPE_CHECKING:
    from initrunner.agent.schema.base import ModelConfig

logger = logging.getLogger(__name__)

__all__ = [
    "build_history_processor",
    "enforce_token_budget",
    "estimate_tokens",
    "resolve_context_window",
]

_BUDGET_FRACTION = 0.75

_PROVIDER_CONTEXT_WINDOWS: dict[str, int] = {
    "anthropic": 200_000,
    "openai": 128_000,
    "google": 1_000_000,
    "groq": 128_000,
    "bedrock": 200_000,
}

_FALLBACK_CONTEXT_WINDOW = 32_000

# Fixed token estimate for media elements (images, audio, video, documents).
_MEDIA_TOKENS = 1000

# Per-message and per-part framing overhead in estimated tokens.
_MSG_OVERHEAD = 10
_PART_OVERHEAD = 5


# ---------------------------------------------------------------------------
# Context window resolution
# ---------------------------------------------------------------------------


def resolve_context_window(model_config: ModelConfig) -> int:
    """Return the context window size in tokens for *model_config*.

    Priority: explicit ``context_window`` > provider default > conservative
    fallback (32 000) with a warning.
    """
    ctx = getattr(model_config, "context_window", None)
    if isinstance(ctx, int) and ctx > 0:
        return ctx

    provider_raw = getattr(model_config, "provider", "")
    provider = provider_raw.lower() if isinstance(provider_raw, str) else ""
    if provider in _PROVIDER_CONTEXT_WINDOWS:
        return _PROVIDER_CONTEXT_WINDOWS[provider]

    logger.warning(
        "context_window not set and provider '%s' not recognized; "
        "using %d -- set spec.model.context_window explicitly",
        provider_raw,
        _FALLBACK_CONTEXT_WINDOW,
    )
    return _FALLBACK_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def _estimate_part_tokens(part: Any) -> int:
    """Estimate tokens for a single message part."""
    kind = getattr(part, "part_kind", "")

    # Text-bearing request parts
    if kind in ("system-prompt", "retry-prompt"):
        content = getattr(part, "content", "")
        return len(str(content)) // 4 + _PART_OVERHEAD

    if kind == "user-prompt":
        content = part.content
        if isinstance(content, str):
            return len(content) // 4 + _PART_OVERHEAD
        # Multimodal sequence
        return _estimate_multimodal(content) + _PART_OVERHEAD

    # Tool return parts (tool-return, builtin-tool-return)
    if kind in ("tool-return", "builtin-tool-return"):
        content = getattr(part, "content", "")
        return len(str(content)) // 4 + _PART_OVERHEAD

    # Text-bearing response parts
    if kind in ("text", "thinking"):
        content = getattr(part, "content", "")
        return len(content) // 4 + _PART_OVERHEAD

    # Tool call parts
    if kind in ("tool-call", "builtin-tool-call"):
        args = getattr(part, "args", None)
        return (len(str(args)) // 4 if args else 0) + _PART_OVERHEAD

    # File/binary parts
    if kind == "file":
        return _MEDIA_TOKENS + _PART_OVERHEAD

    return _PART_OVERHEAD


def _estimate_multimodal(content: Sequence[Any]) -> int:
    """Estimate tokens for a multimodal UserPromptPart content sequence."""
    total = 0
    for item in content:
        if isinstance(item, str):
            total += len(item) // 4
        elif getattr(item, "kind", None) == "cache-point":
            pass  # CachePoint contributes nothing
        else:
            # ImageUrl, AudioUrl, DocumentUrl, VideoUrl, BinaryContent
            total += _MEDIA_TOKENS
    return total


def estimate_tokens(messages: list[ModelMessage]) -> int:
    """Estimate the total token count of *messages* using a fast heuristic."""
    total = 0
    for msg in messages:
        total += _MSG_OVERHEAD
        parts = getattr(msg, "parts", None)
        if parts is None:
            # Non-ModelMessage object (e.g. dict in tests) -- rough fallback.
            total += len(str(msg)) // 4
            continue
        for part in parts:
            total += _estimate_part_tokens(part)
    return total


# ---------------------------------------------------------------------------
# Token budget enforcement
# ---------------------------------------------------------------------------


def _truncate_part(part: Any, max_chars: int) -> Any:
    """Return a truncated copy of *part* if its text content exceeds *max_chars*.

    Uses ``dataclasses.replace`` to preserve all metadata (run_id, timestamp,
    tool_call_id, etc.).  Returns the original part unchanged when truncation
    is not applicable.
    """
    kind = getattr(part, "part_kind", "")

    if kind in ("tool-return", "builtin-tool-return"):
        content = part.content
        if isinstance(content, str) and len(content) > max_chars:
            return dataclasses.replace(part, content=content[:max_chars] + " [truncated]")
        return part

    if kind == "text":
        if len(part.content) > max_chars:
            return dataclasses.replace(part, content=part.content[:max_chars] + " [truncated]")
        return part

    if kind == "user-prompt":
        if isinstance(part.content, str) and len(part.content) > max_chars:
            return dataclasses.replace(part, content=part.content[:max_chars] + " [truncated]")
        return part

    if kind == "thinking":
        if len(part.content) > max_chars:
            return dataclasses.replace(part, content=part.content[:max_chars] + " [truncated]")
        return part

    return part


def _truncate_message(msg: ModelMessage, max_chars: int) -> ModelMessage:
    """Return a copy of *msg* with oversized parts truncated."""
    parts = getattr(msg, "parts", None)
    if parts is None:
        return msg  # non-ModelMessage object (e.g. dict in tests)
    new_parts = [_truncate_part(p, max_chars) for p in parts]
    if all(new is old for new, old in zip(new_parts, parts, strict=True)):
        return msg  # nothing changed
    return dataclasses.replace(msg, parts=new_parts)


def _build_drop_summary(dropped: list[ModelMessage]) -> str:
    """Build a short summary string for dropped messages."""
    tool_names: list[str] = []
    for msg in dropped:
        for part in getattr(msg, "parts", ()):
            kind = getattr(part, "part_kind", "")
            if kind in ("tool-call", "builtin-tool-call"):
                name = getattr(part, "tool_name", "")
                if name and name not in tool_names:
                    tool_names.append(name)

    summary = f"[{len(dropped)} earlier messages dropped to fit context budget"
    if tool_names:
        summary += f"; tools used: {', '.join(tool_names[:10])}"
    summary += "]"
    return summary


def enforce_token_budget(
    messages: list[ModelMessage],
    budget: int,
    *,
    preserve_first: bool = False,
) -> list[ModelMessage]:
    """Ensure *messages* fit within *budget* estimated tokens.

    Stage 1: truncate any text-bearing part whose content exceeds
    ``budget // 20`` characters.
    Stage 2: if still over budget, drop the oldest request-response pairs
    and insert a synthetic summary message.

    Returns the original list unmodified when already under budget.
    """
    if not messages:
        return messages

    est = estimate_tokens(messages)
    if est <= budget:
        return messages

    # Stage 1: truncate oversized parts
    max_chars = max(budget // 20, 200)  # floor at 200 chars
    truncated = [_truncate_message(m, max_chars) for m in messages]

    est = estimate_tokens(truncated)
    if est <= budget:
        logger.warning(
            "History budget guard: truncated oversized parts "
            "(%d -> %d estimated tokens, budget %d)",
            estimate_tokens(messages),
            est,
            budget,
        )
        return truncated

    # Stage 2: drop oldest message pairs
    # Determine which messages to keep: optionally first + tail
    start_idx = 1 if preserve_first and len(truncated) > 1 else 0
    first = [truncated[0]] if preserve_first and truncated else []
    middle = truncated[start_idx:]

    # Drop pairs from the front of middle until under budget
    dropped: list[ModelMessage] = []
    while len(middle) > 1 and estimate_tokens(first + middle) > budget:
        msg = middle.pop(0)
        dropped.append(msg)
        # If we just dropped a request, also drop the following response to
        # keep request-response pairing intact.
        if isinstance(msg, ModelRequest) and middle and isinstance(middle[0], ModelResponse):
            dropped.append(middle.pop(0))
        # If we dropped a response, also drop a dangling response that follows
        elif isinstance(msg, ModelResponse) and middle and isinstance(middle[0], ModelResponse):
            dropped.append(middle.pop(0))

    # Insert synthetic summary
    if dropped:
        summary_text = _build_drop_summary(dropped)
        summary_msg = ModelRequest(parts=[UserPromptPart(content=summary_text)])
        middle = [summary_msg, *middle]

    result: list[ModelMessage] = first + middle if preserve_first else middle

    # Ensure result starts with ModelRequest (PydanticAI requirement)
    while result and isinstance(result[0], ModelResponse):
        result = result[1:]

    if not result:
        # Absolute last resort: keep only the last request from the original
        for msg in reversed(messages):
            if isinstance(msg, ModelRequest):
                result = [msg]
                break
        if not result:
            return messages  # give up, return original

    original_est = estimate_tokens(messages)
    final_est = estimate_tokens(result)
    logger.warning(
        "History budget guard: dropped %d messages, truncated parts "
        "(%d -> %d estimated tokens, budget %d)",
        len(dropped),
        original_est,
        final_est,
        budget,
    )
    return result


# ---------------------------------------------------------------------------
# History processor factory
# ---------------------------------------------------------------------------


def build_history_processor(
    model_config: ModelConfig,
) -> Callable[[list[ModelMessage]], list[ModelMessage]]:
    """Return a PydanticAI ``HistoryProcessor`` that enforces a token budget.

    The returned closure is registered on the Agent and runs before every
    model API call.  It is fast (no LLM calls) and uses heuristic token
    estimation.
    """
    ctx_window = resolve_context_window(model_config)
    budget = int(ctx_window * _BUDGET_FRACTION)

    def _processor(messages: list[ModelMessage]) -> list[ModelMessage]:
        return enforce_token_budget(messages, budget)

    return _processor
