"""Judge an agent's output against a list of criteria (the ``jev_judge`` assertion).

One request, one yes/no question per criterion. Raises
:class:`~initrunner.jev.JevError` when no judgment comes back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from initrunner.jev import questions as q

Status = Literal["pass", "uncertain", "fail"]


@dataclass(frozen=True)
class CriterionResult:
    criterion: str
    probability: float
    status: Status


@dataclass(frozen=True)
class CriteriaVerdict:
    results: list[CriterionResult]
    judgment: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(r.status == "pass" for r in self.results)

    @property
    def summary(self) -> str:
        met = sum(r.status == "pass" for r in self.results)
        parts = [f"{r.status} {r.probability:.2f}: {r.criterion}" for r in self.results]
        return f"{met}/{len(self.results)} criteria met ({'; '.join(parts)})"


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " [truncated]"


def judge_criteria(
    prompt: str, output: str, criteria: list[str], *, threshold: float = q.EVAL_THRESHOLD
) -> CriteriaVerdict:
    from initrunner import jev

    state = {
        "prompt": _cap(prompt, q.EVAL_PROMPT_CHARS),
        "output": _cap(output, q.EVAL_OUTPUT_CHARS),
    }
    judgment = jev.ask(state, q.eval_criteria(criteria))
    results = []
    for i, criterion in enumerate(criteria):
        p = judgment.nouls[f"criterion::{i}"]
        status: Status = (
            "pass" if p >= threshold else "uncertain" if p > q.EVAL_UNCERTAIN else "fail"
        )
        results.append(CriterionResult(criterion=criterion, probability=p, status=status))
    return CriteriaVerdict(results=results, judgment=judgment.to_dict())
