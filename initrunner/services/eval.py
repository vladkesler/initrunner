"""Eval services layer — thin wrappers for CLI, API, and TUI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.eval.runner import SuiteResult
    from initrunner.eval.schema import TestSuiteDefinition


def run_suite_sync(
    agent: Agent,
    role: RoleDefinition,
    suite: TestSuiteDefinition,
    *,
    dry_run: bool = False,
    concurrency: int = 1,
    tag_filter: list[str] | None = None,
    role_file: Path | None = None,
    pydantic_evals: bool = False,
) -> SuiteResult:
    """Run an eval suite, building per-worker agents when concurrent.

    With ``pydantic_evals=True`` the suite runs through the pydantic-evals
    engine, capturing OTel spans per case so span-based assertions can read a
    real span tree. The returned ``SuiteResult`` is identical in shape to the
    bespoke path, so callers and JSON export are unaffected. Requires the
    ``observability`` extra.
    """
    if pydantic_evals:
        from initrunner.eval.runner import run_suite_pydantic_evals

        return run_suite_pydantic_evals(
            agent,
            role,
            suite,
            dry_run=dry_run,
            concurrency=concurrency,
            tag_filter=tag_filter,
        ).suite_result

    from initrunner.eval.runner import run_suite

    agent_factory = None
    if concurrency > 1 and role_file is not None:
        from initrunner.agent.loader import load_and_build

        def agent_factory():
            return load_and_build(role_file)

    if concurrency > 1 and agent_factory is not None:
        return run_suite(
            suite=suite,
            dry_run=dry_run,
            concurrency=concurrency,
            tag_filter=tag_filter,
            agent_factory=agent_factory,
        )

    return run_suite(
        agent=agent,
        role=role,
        suite=suite,
        dry_run=dry_run,
        concurrency=1,
        tag_filter=tag_filter,
    )


def save_result(result: SuiteResult, path: Path) -> None:
    """Write suite result as JSON."""
    path.write_text(json.dumps(result.to_dict(), indent=2) + "\n")
