"""LLM-as-judge evaluation for agent outputs."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field

_logger = logging.getLogger(__name__)

_JUDGE_SYSTEM_PROMPT = """\
You are an evaluation judge. Given an agent output and a list of criteria, \
determine whether each criterion is met.
Respond with ONLY a JSON object in this exact format:
{"results": [{"criterion": "...", "passed": true, "reason": "brief explanation"}, ...]}
Do not include any other text. Evaluate each criterion independently."""

_judge_cache: dict[str, object] = {}
_judge_cache_lock = threading.Lock()


@dataclass
class JudgeCriterionResult:
    criterion: str
    passed: bool
    reason: str


@dataclass
class JudgeResult:
    criteria_results: list[JudgeCriterionResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(cr.passed for cr in self.criteria_results)

    @property
    def summary(self) -> str:
        passed = sum(1 for cr in self.criteria_results if cr.passed)
        total = len(self.criteria_results)
        return f"{passed}/{total} criteria passed"


def _get_judge_agent(model: str = "openai:gpt-4o-mini"):
    """Return a cached judge Agent for the given model."""
    from pydantic_ai import Agent
    from pydantic_ai.settings import ModelSettings

    cache_key = str(model)

    with _judge_cache_lock:
        if cache_key in _judge_cache:
            return _judge_cache[cache_key]

    agent = Agent(
        model,
        system_prompt=_JUDGE_SYSTEM_PROMPT,
        model_settings=ModelSettings(temperature=0.0, max_tokens=1000),
    )

    with _judge_cache_lock:
        _judge_cache[cache_key] = agent
    return agent


def _parse_judge_response(response: str, criteria: list[str]) -> JudgeResult:
    """Parse the JSON response from the judge, with defensive fallback."""
    try:
        data = json.loads(response)
        results_data = data.get("results", [])
        criteria_results = []
        for item in results_data:
            criteria_results.append(
                JudgeCriterionResult(
                    criterion=item.get("criterion", ""),
                    passed=bool(item.get("passed", False)),
                    reason=item.get("reason", ""),
                )
            )
        # If we got fewer results than criteria, mark missing ones as failed
        returned_criteria = {cr.criterion for cr in criteria_results}
        for c in criteria:
            if c not in returned_criteria:
                criteria_results.append(
                    JudgeCriterionResult(
                        criterion=c,
                        passed=False,
                        reason="Criterion not evaluated by judge",
                    )
                )
        return JudgeResult(criteria_results=criteria_results)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        _logger.warning("Judge returned unparseable response: %s", response[:200])
        return JudgeResult(
            criteria_results=[
                JudgeCriterionResult(
                    criterion=c,
                    passed=False,
                    reason=f"Judge response parse error: {e}",
                )
                for c in criteria
            ]
        )


def run_judge_sync(
    output: str, criteria: list[str], model: str = "openai:gpt-4o-mini"
) -> JudgeResult:
    """Run LLM judge evaluation synchronously."""
    judge = _get_judge_agent(model)
    prompt = f"Agent output:\n{output}\n\nCriteria to evaluate:\n"
    for i, c in enumerate(criteria, 1):
        prompt += f"{i}. {c}\n"

    result = judge.run_sync(prompt)
    return _parse_judge_response(str(result.output), criteria)
