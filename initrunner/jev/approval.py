"""Judge one tool call: run it, deny it, or pause for a human.

Jev answers three questions about the call (damage, whether it was asked for,
whether it sends data out). The decision is made here, in code, against the
thresholds in :mod:`initrunner.jev.questions`, so the rule is readable and
tunable. Raises :class:`~initrunner.jev.JevError` when no judgment comes back;
the caller pauses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from initrunner.jev import questions as q

Decision = Literal["approve", "deny", "pause"]


@dataclass(frozen=True)
class ApprovalVerdict:
    decision: Decision
    reason: str
    blast_radius: float
    blast_confidence: float
    requested: float
    exfil: float
    judgment: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "blast_radius": round(self.blast_radius, 4),
            "blast_confidence": round(self.blast_confidence, 4),
            "requested": round(self.requested, 4),
            "exfil": round(self.exfil, 4),
            "judgment": self.judgment,
        }


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " [truncated]"


def _args_text(tool_args: dict[str, Any]) -> Any:
    raw = json.dumps(tool_args, default=str, ensure_ascii=False)
    return tool_args if len(raw) <= q.APPROVAL_ARGS_CHARS else _cap(raw, q.APPROVAL_ARGS_CHARS)


def judge_tool_call(user_request: str, tool: str, tool_args: dict[str, Any]) -> ApprovalVerdict:
    from initrunner import jev

    state = {
        "user_request": _cap(user_request, q.APPROVAL_REQUEST_CHARS),
        "call": {"tool": tool, "args": _args_text(tool_args)},
    }
    judgment = jev.ask(state, q.approval())
    blast = judgment.scores["blast_radius"]
    requested = judgment.nouls["requested"]
    exfil = judgment.nouls["exfil"]

    level = q.BLAST_LEVELS[min(round(blast.score), len(q.BLAST_LEVELS) - 1)]
    facts = f"blast {blast.score:.2f}, requested {requested:.2f}, sends data out {exfil:.2f}"

    decision: Decision
    if requested < q.APPROVAL_DENY_UNREQUESTED and (
        exfil >= q.APPROVAL_DENY_EXFIL or blast.score >= q.APPROVAL_DENY_BLAST
    ):
        decision = "deny"
        why = "sends local data out" if exfil >= q.APPROVAL_DENY_EXFIL else level.rstrip(".")
        reason = f"not requested and {why[0].lower()}{why[1:]} ({facts})"
    elif (
        requested >= q.APPROVAL_AUTO_REQUESTED
        and exfil < q.APPROVAL_AUTO_EXFIL_MAX
        and blast.score <= q.APPROVAL_AUTO_BLAST_MAX
        and blast.confidence >= q.APPROVAL_AUTO_BLAST_CONFIDENCE
    ):
        decision = "approve"
        reason = f"requested and low risk ({facts})"
    else:
        decision = "pause"
        concerns = []
        if requested < q.APPROVAL_AUTO_REQUESTED:
            concerns.append(f"may not be what was asked ({requested:.2f})")
        if exfil >= q.APPROVAL_AUTO_EXFIL_MAX:
            concerns.append(f"may send data out ({exfil:.2f})")
        if blast.score > q.APPROVAL_AUTO_BLAST_MAX:
            concerns.append(f"{level[0].lower()}{level[1:].rstrip('.')} ({blast.score:.2f})")
        elif blast.confidence < q.APPROVAL_AUTO_BLAST_CONFIDENCE:
            concerns.append(f"damage unclear (confidence {blast.confidence:.2f})")
        reason = "Jev: " + "; ".join(concerns) if concerns else f"Jev: needs a look ({facts})"

    return ApprovalVerdict(
        decision=decision,
        reason=reason,
        blast_radius=blast.score,
        blast_confidence=blast.confidence,
        requested=requested,
        exfil=exfil,
        judgment=judgment.to_dict(),
    )


async def judge_tool_call_async(
    user_request: str, tool: str, tool_args: dict[str, Any]
) -> ApprovalVerdict:
    import anyio

    return await anyio.to_thread.run_sync(judge_tool_call, user_request, tool, tool_args)  # type: ignore[unresolved-attribute]
