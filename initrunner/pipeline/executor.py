"""DAG execution engine for pipelines."""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from initrunner.pipeline.schema import PipelineDefinition, PipelineStep

if TYPE_CHECKING:
    from initrunner.audit.logger import AuditLogger

logger = logging.getLogger(__name__)

_TRUTHY = {"true", "1", "yes"}
_FALSY = {"false", "0", "no", ""}


@dataclass
class StepResult:
    name: str
    output: str = ""
    parsed_output: dict | str | None = None
    success: bool = True
    error: str | None = None
    duration_ms: int = 0
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class PipelineResult:
    pipeline_id: str
    pipeline_name: str
    step_results: list[StepResult] = field(default_factory=list)
    duration_ms: int = 0
    success: bool = True


def _topological_sort(steps: list[PipelineStep]) -> list[list[PipelineStep]]:
    """Return tiers of parallelizable steps via shared Kahn's algorithm."""
    from initrunner._graph import topological_tiers

    step_map = {s.name: s for s in steps}
    edges = {s.name: list(s.depends_on) for s in steps}
    name_tiers = topological_tiers(set(step_map), edges)
    return [[step_map[name] for name in tier] for tier in name_tiers]


def _interpolate(
    template: str,
    variables: dict[str, str],
    step_outputs: dict[str, StepResult],
) -> str:
    """Replace {{var}}, {{steps.NAME.output}}, and {{steps.NAME.output.key}}."""

    def replacer(match: re.Match) -> str:
        expr = match.group(1).strip()

        # {{steps.NAME.output.key}} or {{steps.NAME.output}}
        step_match = re.match(r"steps\.(\w+)\.output(?:\.(\w+))?$", expr)
        if step_match:
            step_name = step_match.group(1)
            json_key = step_match.group(2)
            sr = step_outputs.get(step_name)
            if sr is None:
                return match.group(0)  # leave unreplaced
            if json_key is not None:
                if isinstance(sr.parsed_output, dict):
                    return str(sr.parsed_output.get(json_key, match.group(0)))
                return match.group(0)
            return sr.output

        # Simple variable
        if expr in variables:
            return variables[expr]

        return match.group(0)  # leave unreplaced

    return re.sub(r"\{\{(.+?)\}\}", replacer, template)


def _eval_condition(
    condition_str: str,
    variables: dict[str, str],
    step_outputs: dict[str, StepResult],
) -> bool:
    """Resolve variables in condition, then check truthiness."""
    resolved = _interpolate(condition_str, variables, step_outputs).strip().lower()
    if resolved in _FALSY:
        return False
    if resolved in _TRUTHY:
        return True
    # Non-empty string is truthy
    return bool(resolved)


def _execute_step(
    step: PipelineStep,
    variables: dict[str, str],
    step_outputs: dict[str, StepResult],
    audit_logger: AuditLogger | None,
    base_dir: Path,
) -> StepResult:
    """Execute a single pipeline step."""
    start = time.monotonic()
    result = StepResult(name=step.name)

    # Evaluate condition
    if step.condition is not None:
        if not _eval_condition(step.condition, variables, step_outputs):
            result.skipped = True
            result.skip_reason = f"Condition not met: {step.condition}"
            result.duration_ms = int((time.monotonic() - start) * 1000)
            return result

    # Interpolate prompt
    prompt = _interpolate(step.prompt, variables, step_outputs)

    try:
        if step.mode == "mcp":
            from initrunner.agent.delegation import McpInvoker

            invoker = McpInvoker(
                base_url=step.url,  # type: ignore[arg-type]
                agent_name=step.name,
                timeout=step.timeout_seconds,
                headers_env=step.headers_env,
            )
            output = invoker.invoke(prompt)
        else:
            from initrunner.agent.executor import execute_run
            from initrunner.agent.loader import build_agent, load_role

            role_path = Path(step.role_file)  # type: ignore[arg-type]
            if not role_path.is_absolute():
                role_path = base_dir / role_path
            role_path = role_path.resolve()

            role = load_role(role_path)
            output_type = dict if step.output_format == "json" else str
            agent = build_agent(role, role_dir=role_path.parent, output_type=output_type)
            run_result, _ = execute_run(
                agent,
                role,
                prompt,
                audit_logger=audit_logger,
                trigger_type="pipeline",
            )

            if not run_result.success:
                result.success = False
                result.error = run_result.error
                result.duration_ms = int((time.monotonic() - start) * 1000)
                return result

            output = run_result.output

        result.output = output

        # Parse JSON output if requested
        if step.output_format == "json":
            try:
                result.parsed_output = json.loads(output)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Step '%s' output_format=json but output is not valid JSON, using raw string",
                    step.name,
                )
                result.parsed_output = output
        else:
            result.parsed_output = output

    except Exception as e:
        result.success = False
        result.error = str(e)

    result.duration_ms = int((time.monotonic() - start) * 1000)
    return result


def run_pipeline(
    pipeline: PipelineDefinition,
    variables: dict[str, str] | None = None,
    audit_logger: AuditLogger | None = None,
    base_dir: Path | None = None,
) -> PipelineResult:
    """Execute a pipeline DAG, returning results for all steps."""
    variables = variables or {}
    base_dir = base_dir or Path.cwd()

    from initrunner._ids import generate_id

    pipeline_id = generate_id()
    pipeline_result = PipelineResult(
        pipeline_id=pipeline_id,
        pipeline_name=pipeline.metadata.name,
    )

    tiers = _topological_sort(pipeline.spec.steps)
    step_outputs: dict[str, StepResult] = {}
    start = time.monotonic()
    failed = False

    for tier in tiers:
        if failed and pipeline.spec.error_strategy == "fail-fast":
            # Skip remaining tiers
            for step in tier:
                sr = StepResult(
                    name=step.name,
                    skipped=True,
                    skip_reason="Skipped due to fail-fast after prior failure",
                )
                pipeline_result.step_results.append(sr)
                step_outputs[step.name] = sr
            continue

        if len(tier) == 1:
            # Single step, no need for thread pool
            sr = _execute_step(tier[0], variables, step_outputs, audit_logger, base_dir)
            pipeline_result.step_results.append(sr)
            step_outputs[sr.name] = sr
            if not sr.success and not sr.skipped:
                failed = True
        else:
            # Parallel execution
            max_workers = min(len(tier), pipeline.spec.max_parallel)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        _execute_step,
                        step,
                        variables,
                        step_outputs,
                        audit_logger,
                        base_dir,
                    ): step.name
                    for step in tier
                }
                for future in as_completed(futures):
                    sr = future.result()
                    pipeline_result.step_results.append(sr)
                    step_outputs[sr.name] = sr
                    if not sr.success and not sr.skipped:
                        failed = True

    pipeline_result.duration_ms = int((time.monotonic() - start) * 1000)
    pipeline_result.success = not failed
    return pipeline_result
