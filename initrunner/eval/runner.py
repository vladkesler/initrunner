"""Eval runner: load test suites and execute them against agents."""

from __future__ import annotations

import datetime
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from pydantic_ai import Agent

from initrunner.agent.executor import RunResult, execute_run
from initrunner.agent.schema.role import RoleDefinition
from initrunner.eval.assertions import AssertionResult, EvalContext, evaluate_assertions
from initrunner.eval.schema import SpanAssertion, TestCase, TestSuiteDefinition


class SuiteLoadError(Exception):
    """Raised when a test suite definition cannot be loaded or validated."""


def load_suite(path: Path) -> TestSuiteDefinition:
    """Read a YAML file and validate it as a TestSuiteDefinition."""
    try:
        raw = path.read_text()
    except OSError as e:
        raise SuiteLoadError(f"Cannot read {path}: {e}") from e

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise SuiteLoadError(f"Invalid YAML in {path}: {e}") from e

    if not isinstance(data, dict):
        raise SuiteLoadError(f"Expected a YAML mapping in {path}, got {type(data).__name__}")

    try:
        return TestSuiteDefinition.model_validate(data)
    except ValidationError as e:
        raise SuiteLoadError(f"Validation failed for {path}:\n{e}") from e


@dataclass
class CaseResult:
    case: TestCase
    run_result: RunResult
    assertion_results: list[AssertionResult]
    passed: bool
    duration_ms: int = 0


@dataclass
class SuiteResult:
    suite_name: str
    case_results: list[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.case_results)

    @property
    def passed(self) -> int:
        return sum(1 for cr in self.case_results if cr.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def all_passed(self) -> bool:
        return all(cr.passed for cr in self.case_results)

    @property
    def total_tokens(self) -> int:
        return sum(cr.run_result.total_tokens for cr in self.case_results)

    @property
    def total_duration_ms(self) -> int:
        return sum(cr.duration_ms for cr in self.case_results)

    @property
    def avg_duration_ms(self) -> int:
        if not self.case_results:
            return 0
        return self.total_duration_ms // len(self.case_results)

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict with a stable, flat schema."""
        return {
            "suite_name": self.suite_name,
            "timestamp": datetime.datetime.now(tz=datetime.UTC).isoformat(),
            "summary": {
                "total": self.total,
                "passed": self.passed,
                "failed": self.failed,
                "total_tokens": self.total_tokens,
                "total_duration_ms": self.total_duration_ms,
            },
            "cases": [
                {
                    "name": cr.case.name,
                    "passed": cr.passed,
                    "duration_ms": cr.duration_ms,
                    "tokens": {
                        "input": cr.run_result.tokens_in,
                        "output": cr.run_result.tokens_out,
                        "total": cr.run_result.total_tokens,
                    },
                    "tool_calls": cr.run_result.tool_call_names,
                    "assertions": [
                        {
                            "type": ar.assertion.type,
                            "passed": ar.passed,
                            "message": ar.message,
                        }
                        for ar in cr.assertion_results
                    ],
                    "output_preview": cr.run_result.output[:200],
                    "error": cr.run_result.error,
                }
                for cr in self.case_results
            ],
        }


_DEFAULT_DRY_RUN_OUTPUT = "[dry-run] Simulated response."


def _run_single_case(
    agent: Agent,
    role: RoleDefinition,
    case: TestCase,
    *,
    dry_run: bool = False,
) -> CaseResult:
    """Execute a single test case and evaluate its assertions."""
    model_override = None
    if dry_run:
        from pydantic_ai.models.test import TestModel

        output_text = case.expected_output or _DEFAULT_DRY_RUN_OUTPUT
        model_override = TestModel(custom_output_text=output_text, call_tools=[])

    start = time.monotonic()
    run_result, _ = execute_run(
        agent, role, case.prompt, audit_logger=None, model_override=model_override
    )
    duration_ms = int((time.monotonic() - start) * 1000)

    ctx = EvalContext(
        output=run_result.output,
        tool_call_names=run_result.tool_call_names,
        total_tokens=run_result.total_tokens,
        duration_ms=duration_ms,
        reasoning_tokens=run_result.reasoning_tokens,
        event_timeline=run_result.event_timeline,
    )
    assertion_results = evaluate_assertions(case.assertions, ctx, dry_run=dry_run)
    all_assertions_passed = all(ar.passed for ar in assertion_results)
    case_passed = run_result.success and all_assertions_passed

    return CaseResult(
        case=case,
        run_result=run_result,
        assertion_results=assertion_results,
        passed=case_passed,
        duration_ms=duration_ms,
    )


def _filter_cases(suite: TestSuiteDefinition, tag_filter: list[str] | None) -> list[TestCase]:
    """Return the suite cases narrowed by an optional tag filter."""
    cases = suite.cases
    if tag_filter:
        tag_set = set(tag_filter)
        cases = [c for c in cases if tag_set.intersection(c.tags)]
    return cases


def run_suite(
    agent: Agent | None = None,
    role: RoleDefinition | None = None,
    suite: TestSuiteDefinition | None = None,
    *,
    dry_run: bool = False,
    concurrency: int = 1,
    tag_filter: list[str] | None = None,
    agent_factory: Callable[[], tuple[Agent, RoleDefinition]] | None = None,
) -> SuiteResult:
    """Execute all test cases in a suite against the agent.

    When ``concurrency > 1``, requires ``agent_factory`` to build a fresh
    agent per worker thread.
    """
    if suite is None:
        raise ValueError("suite must not be None")
    result = SuiteResult(suite_name=suite.metadata.name)

    cases = _filter_cases(suite, tag_filter)
    if not cases:
        return result

    if concurrency > 1 and agent_factory is not None:
        result.case_results = _run_concurrent(
            cases, agent_factory, dry_run=dry_run, concurrency=concurrency
        )
    else:
        if agent is None or role is None:
            raise ValueError("agent and role must not be None for sequential execution")
        for case in cases:
            cr = _run_single_case(agent, role, case, dry_run=dry_run)
            result.case_results.append(cr)

    return result


def _run_concurrent(
    cases: list[TestCase],
    agent_factory: Callable[[], tuple[Agent, RoleDefinition]],
    *,
    dry_run: bool,
    concurrency: int,
) -> list[CaseResult]:
    """Run cases concurrently using ThreadPoolExecutor."""
    import threading

    local = threading.local()

    def _worker(case: TestCase) -> CaseResult:
        if not hasattr(local, "agent"):
            local.agent, local.role = agent_factory()
        return _run_single_case(local.agent, local.role, case, dry_run=dry_run)

    indexed_futures = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for idx, case in enumerate(cases):
            future = pool.submit(_worker, case)
            indexed_futures[future] = idx

        indexed_results: list[tuple[int, CaseResult]] = []
        for future in as_completed(indexed_futures):
            indexed_results.append((indexed_futures[future], future.result()))

    indexed_results.sort(key=lambda x: x[0])
    return [cr for _, cr in indexed_results]


@dataclass
class PydanticEvalsResult:
    """Outcome of the pydantic-evals run-suite path.

    ``suite_result`` mirrors the bespoke ``SuiteResult`` so existing CLI output
    and ``to_dict()`` exports keep working unchanged. ``report`` is the native
    ``pydantic_evals.reporting.EvaluationReport`` for callers that want span
    analysis, per-evaluator scores, or aggregate metrics.
    """

    suite_result: SuiteResult
    report: Any


def run_suite_pydantic_evals(
    agent: Agent,
    role: RoleDefinition,
    suite: TestSuiteDefinition,
    *,
    dry_run: bool = False,
    concurrency: int = 1,
    tag_filter: list[str] | None = None,
) -> PydanticEvalsResult:
    """Run a suite through pydantic-evals, capturing OTel spans per case.

    Each case becomes a ``pydantic_evals.Case`` whose evaluators are translated
    from the case assertions. The task executes the agent inside a span-capture
    block so span-based assertions can read a real ``SpanTree`` when an OTel
    provider is configured, and the run-event timeline otherwise. Returns both a
    backward-compatible ``SuiteResult`` and the native ``EvaluationReport``.

    Requires the ``observability`` extra (``pydantic-evals``). Raises
    ``MissingExtraError`` with an install hint when it is not installed.
    """
    from pydantic_evals import Case, Dataset  # type: ignore[import-not-found]

    from initrunner.eval.evaluators import RunRecord, build_evaluators
    from initrunner.observability import capture_span_tree

    cases = _filter_cases(suite, tag_filter)
    suite_result = SuiteResult(suite_name=suite.metadata.name)
    if not cases:
        empty_dataset = Dataset(cases=[], evaluators=[], name=suite.metadata.name)
        empty_report = empty_dataset.evaluate_sync(
            lambda _inputs: RunRecord(), name=suite.metadata.name, progress=False
        )
        return PydanticEvalsResult(suite_result=suite_result, report=empty_report)

    cases_by_name: dict[str, TestCase] = {c.name: c for c in cases}

    def task(inputs: dict[str, Any]) -> RunRecord:
        case = cases_by_name[inputs["name"]]
        model_override = None
        if dry_run:
            from pydantic_ai.models.test import TestModel

            output_text = case.expected_output or _DEFAULT_DRY_RUN_OUTPUT
            model_override = TestModel(custom_output_text=output_text, call_tools=[])

        start = time.monotonic()
        with capture_span_tree():
            run_result, _ = execute_run(
                agent, role, case.prompt, audit_logger=None, model_override=model_override
            )
        duration_ms = int((time.monotonic() - start) * 1000)
        return RunRecord(
            output=run_result.output,
            tool_call_names=run_result.tool_call_names,
            total_tokens=run_result.total_tokens,
            reasoning_tokens=run_result.reasoning_tokens,
            duration_ms=duration_ms,
            event_timeline=run_result.event_timeline,
        )

    # ``expected_output`` is intentionally omitted: every check runs through an
    # explicit assertion evaluator, so a separate expected-output comparison
    # would be redundant and would force a mismatched output generic.
    pe_cases: list[Case[dict[str, Any], RunRecord, Any]] = [
        Case(
            name=case.name,
            inputs={"name": case.name, "prompt": case.prompt},
            evaluators=tuple(build_evaluators(case.assertions)),
        )
        for case in cases
    ]
    dataset: Dataset[dict[str, Any], RunRecord, Any] = Dataset(
        cases=pe_cases, evaluators=[], name=suite.metadata.name
    )
    report = dataset.evaluate_sync(
        task,
        name=suite.metadata.name,
        max_concurrency=concurrency if concurrency > 1 else None,
        progress=False,
    )

    suite_result.case_results = _report_to_case_results(report, cases_by_name)
    return PydanticEvalsResult(suite_result=suite_result, report=report)


def _report_to_case_results(report: Any, cases_by_name: dict[str, TestCase]) -> list[CaseResult]:
    """Convert a pydantic-evals ``EvaluationReport`` into ``CaseResult`` objects.

    Preserves the original suite case order and rebuilds a ``RunResult`` plus
    ``AssertionResult`` list from the report so ``SuiteResult.to_dict()`` keeps
    its stable schema.
    """
    from initrunner.eval.assertions import AssertionResult

    by_name = {rc.name: rc for rc in report.cases}
    case_results: list[CaseResult] = []
    for name, case in cases_by_name.items():
        report_case = by_name.get(name)
        if report_case is None:
            continue
        output = report_case.output
        run_result = RunResult(
            run_id=name,
            output=output.output,
            total_tokens=output.total_tokens,
            reasoning_tokens=output.reasoning_tokens,
            tool_call_names=list(output.tool_call_names),
            event_timeline=list(output.event_timeline),
        )
        assertion_results: list[AssertionResult] = []
        report_assertions = report_case.assertions
        # pydantic-evals disambiguates colliding evaluation names by suffixing
        # ``_2``, ``_3`` and so on, so reconstruct the key per assertion type
        # occurrence to preserve a one-to-one mapping back to suite assertions.
        seen_by_key: dict[str, int] = {}
        for assertion in case.assertions:
            base_key = "span" if isinstance(assertion, SpanAssertion) else assertion.type
            occurrence = seen_by_key.get(base_key, 0)
            seen_by_key[base_key] = occurrence + 1
            lookup_key = base_key if occurrence == 0 else f"{base_key}_{occurrence + 1}"
            result = report_assertions.get(lookup_key)
            passed = bool(result.value) if result is not None else False
            message = (result.reason if result is not None else "Evaluator did not run") or ""
            assertion_results.append(
                AssertionResult(assertion=assertion, passed=passed, message=message)
            )
        all_passed = all(ar.passed for ar in assertion_results)
        case_results.append(
            CaseResult(
                case=case,
                run_result=run_result,
                assertion_results=assertion_results,
                passed=all_passed,
                duration_ms=int(report_case.task_duration * 1000),
            )
        )
    return case_results
