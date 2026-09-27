"""``approval: judged`` -- Jev decides per call whether to run, deny, or ask a human."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic_ai.exceptions import ApprovalRequired
from pydantic_ai.toolsets import AbstractToolset

from initrunner.agent.permissions import check_tool_permission

if TYPE_CHECKING:
    from pydantic_ai.toolsets.abstract import ToolsetTool

    from initrunner.agent.schema.tools import ToolPermissions


class JudgedApprovalToolset(AbstractToolset[Any]):
    """Asks Jev about each call before it runs.

    Sits where ``ApprovalRequiredToolset`` would (outermost), so a pause is
    raised before any tool status event fires. A call a human already approved
    passes straight through. A call the tool's permission rules would deny also
    passes through without asking Jev: the inner ``PermissionToolset`` returns
    the denial, and nobody is asked about a call that can't run anyway.
    """

    def __init__(
        self,
        inner: AbstractToolset[Any],
        permissions: ToolPermissions | None,
        tool_type: str,
    ) -> None:
        self._inner = inner
        self._permissions = permissions
        self._tool_type = tool_type

    @property
    def id(self) -> str | None:
        return self._inner.id

    async def get_tools(self, ctx: Any) -> dict[str, ToolsetTool[Any]]:
        return await self._inner.get_tools(ctx)

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: Any,
        tool: ToolsetTool[Any],
    ) -> Any:
        if ctx.tool_call_approved:
            return await self._inner.call_tool(name, tool_args, ctx, tool)
        if (
            self._permissions is not None
            and not check_tool_permission(tool_args, self._permissions)[0]
        ):
            return await self._inner.call_tool(name, tool_args, ctx, tool)

        from initrunner.audit.scope import log_security_event
        from initrunner.jev import JevError
        from initrunner.jev.approval import judge_tool_call_async

        call = {"tool": name, "args": _args_preview(tool_args)}
        try:
            verdict = await judge_tool_call_async(user_request(ctx), name, tool_args)
        except JevError as exc:
            reason = f"Jev judgment unavailable: {exc}"
            log_security_event(
                "jev.approval", json.dumps({**call, "decision": "pause", "reason": reason})
            )
            raise ApprovalRequired(metadata={"reason": reason}) from None

        log_security_event("jev.approval", json.dumps({**call, **verdict.to_dict()}))
        if verdict.decision == "approve":
            return await self._inner.call_tool(name, tool_args, ctx, tool)
        if verdict.decision == "deny":
            return f"Permission denied: {name} -- judged: {verdict.reason}"
        raise ApprovalRequired(metadata={"reason": verdict.reason})


# The audit row names the call it judged; long arguments are cut, and the audit
# logger scrubs secrets from the details before writing them.
_AUDIT_ARGS_CHARS = 500


def _args_preview(tool_args: dict[str, Any]) -> str:
    text = json.dumps(tool_args, default=str, ensure_ascii=False)
    return text if len(text) <= _AUDIT_ARGS_CHARS else text[:_AUDIT_ARGS_CHARS] + " [truncated]"


def user_request(ctx: Any) -> str:
    """The user's latest request, which the call should serve.

    ``ctx.prompt`` on a normal run. On a resume after an approval it is None,
    so take the latest user-written prompt from the history, skipping the
    content parts tools return (they sit in requests next to tool returns).
    """
    from pydantic_ai.messages import ModelRequest, ToolReturnPart, UserPromptPart

    from initrunner.agent.prompt import extract_text_from_prompt

    if ctx.prompt is not None:
        return extract_text_from_prompt(ctx.prompt)
    for message in reversed(ctx.messages or []):
        if not isinstance(message, ModelRequest):
            continue
        if any(isinstance(part, ToolReturnPart) for part in message.parts):
            continue
        for part in reversed(message.parts):
            if isinstance(part, UserPromptPart):
                return extract_text_from_prompt(part.content)  # type: ignore[arg-type]
    return ""
