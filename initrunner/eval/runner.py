"""Eval runner: load test suites and execute them against agents."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError
from pydantic_ai import Agent

from initrunner.agent.executor import RunResult, execute_run
from initrunner.agent.schema.role import RoleDefinition
from initrunner.eval.assertions import AssertionResult, evaluate_assertions
from initrunner.eval.schema import TestCase, TestSuiteDefinition


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


_DEFAULT_DRY_RUN_OUTPUT = "[dry-run] Simulated response."


def run_suite(
    agent: Agent,
    role: RoleDefinition,
    suite: TestSuiteDefinition,
    *,
    dry_run: bool = False,
) -> SuiteResult:
    """Execute all test cases in a suite against the agent."""
    result = SuiteResult(suite_name=suite.metadata.name)

    for case in suite.cases:
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

        assertion_results = evaluate_assertions(case.assertions, run_result.output)
        all_assertions_passed = all(ar.passed for ar in assertion_results)
        case_passed = run_result.success and all_assertions_passed

        result.case_results.append(
            CaseResult(
                case=case,
                run_result=run_result,
                assertion_results=assertion_results,
                passed=case_passed,
                duration_ms=duration_ms,
            )
        )

    return result
