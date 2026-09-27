"""Tool-result screening -- withholds results that carry instructions aimed at the model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic_ai.capabilities import AbstractCapability  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from pydantic_ai import RunContext  # type: ignore[import-not-found]
    from pydantic_ai.messages import ToolCallPart  # type: ignore[import-not-found]
    from pydantic_ai.tools import ToolDefinition  # type: ignore[import-not-found]

# InitRunner's own denial text from the permission, policy and approval layers.
_OWN_DENIAL = "Permission denied:"


@dataclass
class ToolResultScreenCapability(AbstractCapability[Any]):
    """Screen every tool result with Jev before the model reads it.

    ``after_tool_execute`` sees every tool call in the run, whichever toolset
    or capability provided the tool, including run-scoped tools such as
    ``spawn``. A result that addresses the model (a page telling "AI
    assistants" to run something, a README claiming the user pre-approved an
    action) is replaced with a short notice. When Jev cannot answer, the result
    is withheld too: an unscreened result is not let through.

    Tools a model provider runs on its own servers never execute locally, so
    no local hook sees their output.
    """

    async def after_tool_execute(  # type: ignore[override]
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: Any,
        result: Any,
    ) -> Any:
        text = _as_text(result)
        if not text.strip() or text.startswith(_OWN_DENIAL):
            return result

        from initrunner.audit.scope import log_security_event
        from initrunner.jev import JevError
        from initrunner.jev.screening import screen_result_async

        tool = call.tool_name
        try:
            verdict = await screen_result_async(tool, text)
        except JevError as exc:
            log_security_event(
                "jev.tool_result",
                json.dumps({"tool": tool, "decision": "unavailable", "error": str(exc)}),
            )
            return f"Error: result of {tool} withheld because content screening is unavailable"

        if verdict.withheld or verdict.uncertain:
            decision = "withheld" if verdict.withheld else "passed_uncertain"
            log_security_event(
                "jev.tool_result",
                json.dumps(
                    {
                        "tool": tool,
                        "decision": decision,
                        "addresses_ai": round(verdict.addresses_ai, 4),
                        "judgments": verdict.judgments,
                    }
                ),
            )
        if verdict.withheld:
            return (
                f"Error: result of {tool} withheld by content screening "
                f"(instructions aimed at an AI assistant, {verdict.addresses_ai:.2f})"
            )
        return result


def _as_text(result: Any) -> str:
    """The text Jev should read for *result*; binary content is not screened."""
    if isinstance(result, str):
        return result
    if isinstance(result, bytes | bytearray):
        return ""
    from pydantic_ai.messages import BinaryContent, ToolReturn  # type: ignore[import-not-found]

    if isinstance(result, BinaryContent):
        return ""
    if isinstance(result, ToolReturn):
        parts = [_as_text(result.return_value)]
        content = result.content
        if content is not None:
            items = content if isinstance(content, list) else [content]
            parts.extend(_as_text(item) for item in items)
        return "\n".join(p for p in parts if p)
    try:
        return json.dumps(result, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(result)
