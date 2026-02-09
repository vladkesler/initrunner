"""Convert OpenAI chat messages to PydanticAI message history."""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from initrunner.server.models import ChatMessage


def openai_messages_to_pydantic(
    messages: list[ChatMessage],
) -> tuple[str, list[ModelMessage] | None]:
    """Convert OpenAI-format messages to a PydanticAI prompt + optional history.

    Scans backwards to find the last user message as the prompt.
    Everything before it becomes message_history. System messages are
    prepended to the next user message's content.

    Returns:
        (prompt, message_history) where message_history may be None if
        there's only the single user message.

    Raises:
        ValueError: If no user message is found or messages is empty.
    """
    if not messages:
        raise ValueError("messages list is empty")

    # Find the last user message (scanning backwards)
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            last_user_idx = i
            break

    if last_user_idx == -1:
        raise ValueError("no user message found in messages")

    # Build the prompt from the last user message, prepending any
    # immediately preceding system message content
    prompt_parts: list[str] = []
    prompt_content = messages[last_user_idx].content or ""

    # Collect system messages that should be prepended
    for msg in messages[:last_user_idx]:
        if msg.role == "system":
            if msg.content:
                prompt_parts.append(msg.content)

    # If there's only the final user message (no prior history besides system),
    # prepend system content directly to prompt
    prior_non_system = [m for m in messages[:last_user_idx] if m.role != "system"]

    if prompt_parts and not prior_non_system:
        # No real history, just system + user
        prompt = "\n\n".join(prompt_parts) + "\n\n" + prompt_content
        return prompt, None

    if not prior_non_system:
        return prompt_content, None

    # Build message history from messages before the last user message
    history: list[ModelMessage] = []
    pending_system: list[str] = []

    for msg in messages[:last_user_idx]:
        if msg.role == "system":
            if msg.content:
                pending_system.append(msg.content)
        elif msg.role == "user":
            content = msg.content or ""
            if pending_system:
                content = "\n\n".join(pending_system) + "\n\n" + content
                pending_system.clear()
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif msg.role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=msg.content or "")]))
        # Skip 'tool' role messages — internal to PydanticAI

    # If there are trailing system messages before the final user, prepend to prompt
    if pending_system:
        prompt_content = "\n\n".join(pending_system) + "\n\n" + prompt_content

    return prompt_content, history if history else None
