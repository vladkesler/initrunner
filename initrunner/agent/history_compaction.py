"""LLM-driven conversation history compaction.

Summarises old messages instead of silently dropping them, preserving
important context for long-running autonomous loops.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

if TYPE_CHECKING:
    from initrunner.agent.schema.autonomy import AutonomyConfig
    from initrunner.agent.schema.role import RoleDefinition

_logger = logging.getLogger(__name__)

_COMPACTION_PROMPT = """\
You are a conversation summariser. Below is a section of an agent conversation.
Produce a concise summary that captures:
- Key decisions and conclusions
- Important tool results and data
- Remaining open tasks or blockers

Be factual, do not add opinions. Output ONLY the summary text.

CONVERSATION:
{conversation}
"""

_MAX_SERIALIZE_CHARS = 200


def maybe_compact_message_history(
    messages: list[ModelMessage],
    autonomy_config: AutonomyConfig,
    role: RoleDefinition,
    *,
    preserve_first: bool = False,
) -> list[ModelMessage]:
    """Compact old messages via LLM summarisation. Never raises."""
    try:
        return _compact_inner(messages, autonomy_config, role, preserve_first=preserve_first)
    except Exception:
        _logger.warning("History compaction failed", exc_info=True)
        return messages


def _compact_inner(
    messages: list[ModelMessage],
    autonomy_config: AutonomyConfig,
    role: RoleDefinition,
    *,
    preserve_first: bool = False,
) -> list[ModelMessage]:
    config = autonomy_config.compaction
    if not config.enabled:
        return messages
    if len(messages) < config.threshold:
        return messages

    tail_count = config.tail_messages

    # Split: [first?] + [compact_window] + [tail]
    if preserve_first and messages:
        first = messages[0]
        rest = messages[1:]
    else:
        first = None
        rest = messages

    if len(rest) <= tail_count:
        return messages

    tail = rest[-tail_count:]
    compact_window = rest[: len(rest) - tail_count]

    # If tail starts with ModelResponse, absorb leading responses into compact window
    while tail and isinstance(tail[0], ModelResponse):
        compact_window.append(tail[0])
        tail = tail[1:]

    if not compact_window:
        return messages

    # Serialize and summarise
    text = _serialize_messages_for_summary(compact_window)
    model_str = config.model_override or role.spec.model.to_model_string()
    summary = _run_compaction_llm(text, model_str)

    # Build summary message
    summary_msg = ModelRequest(parts=[UserPromptPart(content=config.summary_prefix + summary)])

    # Reconstruct
    result: list[ModelMessage] = []
    if first is not None:
        result.append(first)
    result.append(summary_msg)
    result.extend(tail)
    return result


def _serialize_messages_for_summary(messages: list[ModelMessage]) -> str:
    """Render messages into a human-readable transcript for the LLM."""
    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    content = str(part.content)
                    lines.append(f"User: {_truncate(content)}")
                elif isinstance(part, ToolReturnPart):
                    if part.tool_name == "activate_skill":
                        lines.append(
                            f"Tool ({part.tool_name}): [skill instructions preserved in context]"
                        )
                    else:
                        content = str(part.content)
                        lines.append(f"Tool ({part.tool_name}): {_truncate(content)}")
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, TextPart):
                    lines.append(f"Assistant: {_truncate(part.content)}")
                elif isinstance(part, ToolCallPart):
                    lines.append(f"Assistant [tool_call]: {part.tool_name}(...)")
    return "\n".join(lines)


def _truncate(text: str) -> str:
    if len(text) <= _MAX_SERIALIZE_CHARS:
        return text
    return text[:_MAX_SERIALIZE_CHARS] + " [truncated]"


def _run_compaction_llm(conversation_text: str, model_str: str) -> str:
    from pydantic_ai import Agent

    prompt = _COMPACTION_PROMPT.format(conversation=conversation_text)
    agent = Agent(model_str)
    result = agent.run_sync(prompt)
    return result.output if hasattr(result, "output") else str(result.data)
