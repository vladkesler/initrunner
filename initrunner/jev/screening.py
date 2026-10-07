"""Screen text entering an agent's context: user prompts and tool results.

Long text is split into overlapping windows. Input windows travel in separate
requests so their topic scores cannot bleed into one another; tool results
remain batched. The worst window decides each check.

Both functions raise :class:`~initrunner.jev.JevError` when a judgment cannot
be obtained. The callers fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from initrunner.jev import questions as q


@dataclass(frozen=True)
class InputVerdict:
    blocked: bool
    reason: str
    # Highest probability per check. on_topic is the complement of off_topic,
    # retained for audit consumers; it no longer measures reference relevance.
    scores: dict[str, float] = field(default_factory=dict)
    judgments: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ResultVerdict:
    withheld: bool
    uncertain: bool
    addresses_ai: float
    judgments: list[dict[str, Any]] = field(default_factory=list)


def windows(text: str) -> list[str]:
    """Split *text* into overlapping windows of at most ``SCREEN_WINDOW_CHARS``."""
    size, overlap = q.SCREEN_WINDOW_CHARS, q.SCREEN_WINDOW_OVERLAP
    if len(text) <= size:
        return [text]
    step = size - overlap
    return [text[start : start + size] for start in range(0, len(text) - overlap, step)]


def batches(parts: list[str]) -> list[list[int]]:
    """Group window indices so each batch holds at most ``SCREEN_BATCH_CHARS``."""
    groups: list[list[int]] = [[]]
    used = 0
    for i, part in enumerate(parts):
        if groups[-1] and used + len(part) > q.SCREEN_BATCH_CHARS:
            groups.append([])
            used = 0
        groups[-1].append(i)
        used += len(part)
    return groups


def _state_windows(parts: list[str], indices: list[int]) -> str | list[str]:
    # One window keeps the plain string the questions were calibrated on;
    # several are sent as a list the questions index into. Windows outside the
    # batch are sent empty so the indices keep lining up.
    if len(parts) == 1:
        return parts[0]
    keep = set(indices)
    return [part if i in keep else "" for i, part in enumerate(parts)]


def screen_input(prompt: str, allowed_topics_prompt: str = "") -> InputVerdict:
    """Judge a user prompt for injection, secret extraction and (optionally) topic."""
    from initrunner import jev

    parts = windows(prompt)
    with_topic = bool(allowed_topics_prompt.strip())
    worst: dict[str, float] = {"injection": 0.0, "extraction": 0.0}
    if with_topic:
        worst["off_topic"] = 0.0
    judgments: list[dict[str, Any]] = []

    for i, part in enumerate(parts):
        # Key order matters to Jev: with the policy first, a legitimate question
        # scored 0.87 to 0.89 on-topic; with the input first, 0.52 to 0.59.
        state: dict[str, Any] = {"policy": allowed_topics_prompt} if with_topic else {}
        state["input"] = part
        # Each request uses the plain input field. Global window indices belong
        # in the audit metadata, not in an array containing neighboring text.
        questions = q.screen_input([0], 1, with_topic=with_topic)
        judgment = jev.ask(state, questions)
        judgments.append({**judgment.to_dict(), "window_index": i})
        for key in questions:
            check = key.split("::", 1)[0]
            probability = judgment.nouls.get(key)
            if probability is None or not 0.0 <= probability <= 1.0:
                raise jev.JevError(f"Input screening received no valid answer for {key}")
            worst[check] = max(worst[check], probability)

    if with_topic:
        worst["on_topic"] = 1.0 - worst["off_topic"]

    reasons = []
    if worst["injection"] >= q.SCREEN_INJECTION_BLOCK:
        reasons.append(f"tries to override the assistant's instructions ({worst['injection']:.2f})")
    if worst["extraction"] >= q.SCREEN_EXTRACTION_BLOCK:
        reasons.append(f"asks for secrets or the system prompt ({worst['extraction']:.2f})")
    if with_topic and worst["off_topic"] >= q.SCREEN_OFF_TOPIC_BLOCK:
        reasons.append(f"is outside the allowed topics (off-topic {worst['off_topic']:.2f})")

    reason = "Blocked by input screening: the prompt " + "; ".join(reasons) if reasons else ""
    return InputVerdict(blocked=bool(reasons), reason=reason, scores=worst, judgments=judgments)


def screen_result(tool_name: str, text: str) -> ResultVerdict:
    """Judge a tool result for instructions aimed at the model."""
    from initrunner import jev

    parts = windows(text)
    worst = 0.0
    judgments: list[dict[str, Any]] = []
    for indices in batches(parts):
        state = {"tool": tool_name, "result": _state_windows(parts, indices)}
        judgment = jev.ask(state, q.screen_result(indices, len(parts)))
        judgments.append(judgment.to_dict())
        worst = max([worst, *judgment.nouls.values()])

    return ResultVerdict(
        withheld=worst >= q.SCREEN_RESULT_WITHHOLD,
        uncertain=q.SCREEN_UNCERTAIN <= worst < q.SCREEN_RESULT_WITHHOLD,
        addresses_ai=worst,
        judgments=judgments,
    )


async def screen_input_async(prompt: str, allowed_topics_prompt: str = "") -> InputVerdict:
    import anyio

    return await anyio.to_thread.run_sync(screen_input, prompt, allowed_topics_prompt)  # type: ignore[unresolved-attribute]


async def screen_result_async(tool_name: str, text: str) -> ResultVerdict:
    import anyio

    return await anyio.to_thread.run_sync(screen_result, tool_name, text)  # type: ignore[unresolved-attribute]
