"""Convert OpenAI chat messages to PydanticAI message history."""

from __future__ import annotations

import base64

from pydantic_ai.messages import (
    BinaryContent,
    ImageUrl,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserContent,
    UserPromptPart,
)

from initrunner.agent.prompt import UserPrompt
from initrunner.server.models import ChatMessage, ContentPart


def convert_content_parts(parts: list[ContentPart]) -> list[UserContent]:
    """Convert OpenAI-format content parts to PydanticAI UserContent items."""
    result: list[UserContent] = []
    for part in parts:
        if part.type == "text" and part.text is not None:
            result.append(part.text)
        elif part.type == "image_url" and part.image_url is not None:
            url = part.image_url.get("url", "")
            if url.startswith("data:"):
                # data:image/png;base64,iVBOR...
                header, _, b64data = url.partition(",")
                # Extract media type: "data:image/png;base64" → "image/png"
                media_type = header.replace("data:", "").split(";")[0]
                data = base64.b64decode(b64data)
                result.append(BinaryContent(data=data, media_type=media_type))
            else:
                result.append(ImageUrl(url=url))
        elif part.type == "input_audio" and part.input_audio is not None:
            b64data = part.input_audio.get("data", "")
            fmt = part.input_audio.get("format", "mp3")
            data = base64.b64decode(b64data)
            media_type = f"audio/{fmt}"
            result.append(BinaryContent(data=data, media_type=media_type))
    return result


def _extract_text_from_content(
    content: str | list[ContentPart] | None,
) -> str:
    """Extract plain text from message content (str or multimodal parts)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    text_parts: list[str] = []
    for part in content:
        if part.type == "text" and part.text is not None:
            text_parts.append(part.text)
    return "\n".join(text_parts)


def openai_messages_to_pydantic(
    messages: list[ChatMessage],
) -> tuple[UserPrompt, list[ModelMessage] | None]:
    """Convert OpenAI-format messages to a PydanticAI prompt + optional history.

    Scans backwards to find the last user message as the prompt.
    Everything before it becomes message_history. System messages are
    prepended to the next user message's content.

    Returns:
        (prompt, message_history) where message_history may be None if
        there's only the single user message.  The prompt may be a
        ``str`` or ``list[UserContent]`` for multimodal inputs.

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

    last_user_msg = messages[last_user_idx]
    is_multimodal = isinstance(last_user_msg.content, list)

    # Collect system messages that should be prepended
    system_parts: list[str] = []
    for msg in messages[:last_user_idx]:
        if msg.role == "system":
            text = _extract_text_from_content(msg.content)
            if text:
                system_parts.append(text)

    # If there's only the final user message (no prior history besides system),
    # prepend system content directly to prompt
    prior_non_system = [m for m in messages[:last_user_idx] if m.role != "system"]

    if is_multimodal:
        assert isinstance(last_user_msg.content, list)
        multimodal_parts = convert_content_parts(last_user_msg.content)

        # Prepend system text to the first text part if present
        if system_parts and not prior_non_system:
            system_prefix = "\n\n".join(system_parts) + "\n\n"
            multimodal_parts = _prepend_system_to_parts(system_prefix, multimodal_parts)

        if not prior_non_system:
            return multimodal_parts, None

        # Build message history
        history = _build_history(messages[:last_user_idx])

        # Prepend trailing system messages
        if system_parts and prior_non_system:
            # Check for any trailing system messages after the last non-system
            pending = _trailing_system_texts(messages[:last_user_idx])
            if pending:
                system_prefix = "\n\n".join(pending) + "\n\n"
                multimodal_parts = _prepend_system_to_parts(system_prefix, multimodal_parts)

        return multimodal_parts, history if history else None

    # Plain text path (backward compatible)
    prompt_content = _extract_text_from_content(last_user_msg.content)

    if system_parts and not prior_non_system:
        prompt = "\n\n".join(system_parts) + "\n\n" + prompt_content
        return prompt, None

    if not prior_non_system:
        return prompt_content, None

    # Build message history from messages before the last user message
    history = _build_history(messages[:last_user_idx])

    # If there are trailing system messages before the final user, prepend to prompt
    pending = _trailing_system_texts(messages[:last_user_idx])
    if pending:
        prompt_content = "\n\n".join(pending) + "\n\n" + prompt_content

    return prompt_content, history if history else None


def _prepend_system_to_parts(prefix: str, parts: list[UserContent]) -> list[UserContent]:
    """Prepend system text to the first str element in parts, or insert at front."""
    for i, part in enumerate(parts):
        if isinstance(part, str):
            parts[i] = prefix + part
            return parts
    # No text part found — insert at front
    return [prefix, *parts]


def _trailing_system_texts(messages: list[ChatMessage]) -> list[str]:
    """Collect system message texts from the end of a message list."""
    texts: list[str] = []
    for msg in reversed(messages):
        if msg.role == "system":
            text = _extract_text_from_content(msg.content)
            if text:
                texts.insert(0, text)
        else:
            break
    return texts


def _build_history(messages: list[ChatMessage]) -> list[ModelMessage]:
    """Build PydanticAI message history from a list of ChatMessages."""
    history: list[ModelMessage] = []
    pending_system: list[str] = []

    for msg in messages:
        if msg.role == "system":
            text = _extract_text_from_content(msg.content)
            if text:
                pending_system.append(text)
        elif msg.role == "user":
            content = _extract_text_from_content(msg.content)
            if pending_system:
                content = "\n\n".join(pending_system) + "\n\n" + content
                pending_system.clear()
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif msg.role == "assistant":
            text = _extract_text_from_content(msg.content)
            history.append(ModelResponse(parts=[TextPart(content=text)]))
        # Skip 'tool' role messages — internal to PydanticAI

    return history
