"""API response model builders and report export."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.executor import AutonomousResult, RunResult
    from initrunner.agent.schema.role import RoleDefinition


def role_to_summary(path: Path, role: RoleDefinition | None = None, error: str | None = None):
    """Build a RoleSummary API model from a role path and optional loaded role."""
    from initrunner.api.models import RoleSummary
    from initrunner.api.state import role_path_to_id

    features: list[str] = []
    if role is not None:
        if role.spec.tools:
            features.append("tools")
        if role.spec.triggers:
            features.append("triggers")
        if role.spec.ingest:
            features.append("ingest")
        if role.spec.memory:
            features.append("memory")
        if role.spec.sinks:
            features.append("sinks")
        if role.spec.skills:
            features.append("skills")

    return RoleSummary(
        id=role_path_to_id(path),
        path=str(path),
        name=role.metadata.name if role else path.stem,
        description=role.metadata.description if role else "",
        model=role.spec.model.to_model_string() if role else "",
        features=features,
        valid=role is not None,
        error=error,
    )


def role_to_detail(path: Path, role: RoleDefinition):
    """Build a RoleDetail API model from a role path and loaded role."""
    from initrunner.api.models import (
        GuardrailsDetail,
        IngestDetail,
        MemoryDetail,
        ModelDetail,
        RoleDetail,
        SinkSummary,
        ToolSummary,
        TriggerSummary,
    )

    summary = role_to_summary(path, role)
    yaml_content = path.read_text()

    ingest = None
    if role.spec.ingest:
        ingest = IngestDetail(
            sources=role.spec.ingest.sources,
            chunking_strategy=role.spec.ingest.chunking.strategy,
            chunk_size=role.spec.ingest.chunking.chunk_size,
            chunk_overlap=role.spec.ingest.chunking.chunk_overlap,
            store_backend=role.spec.ingest.store_backend.value,
        )

    memory = None
    if role.spec.memory:
        memory = MemoryDetail(
            store_backend=role.spec.memory.store_backend.value,
            max_sessions=role.spec.memory.max_sessions,
            max_memories=role.spec.memory.max_memories,
            max_resume_messages=role.spec.memory.max_resume_messages,
            episodic_enabled=role.spec.memory.episodic.enabled,
            episodic_max=role.spec.memory.episodic.max_episodes,
            semantic_enabled=role.spec.memory.semantic.enabled,
            semantic_max=role.spec.memory.semantic.max_memories,
            procedural_enabled=role.spec.memory.procedural.enabled,
            procedural_max=role.spec.memory.procedural.max_procedures,
            consolidation_enabled=role.spec.memory.consolidation.enabled,
        )

    return RoleDetail(
        **summary.model_dump(),
        system_prompt=role.spec.role,
        model_config_detail=ModelDetail(
            provider=role.spec.model.provider,
            name=role.spec.model.name,
            base_url=role.spec.model.base_url,
            temperature=role.spec.model.temperature,
            max_tokens=role.spec.model.max_tokens,
        ),
        guardrails=GuardrailsDetail(
            max_tokens_per_run=role.spec.guardrails.max_tokens_per_run,
            timeout_seconds=role.spec.guardrails.timeout_seconds,
            max_tool_calls=role.spec.guardrails.max_tool_calls,
            max_request_limit=role.spec.guardrails.max_request_limit,
            input_tokens_limit=role.spec.guardrails.input_tokens_limit,
            total_tokens_limit=role.spec.guardrails.total_tokens_limit,
            session_token_budget=role.spec.guardrails.session_token_budget,
            daemon_token_budget=role.spec.guardrails.daemon_token_budget,
            daemon_daily_token_budget=role.spec.guardrails.daemon_daily_token_budget,
        ),
        tools=[ToolSummary(type=t.type, summary=t.summary()) for t in role.spec.tools],
        triggers=[TriggerSummary(type=t.type, summary=t.summary()) for t in role.spec.triggers],
        sinks=[SinkSummary(type=s.type, summary=s.summary()) for s in role.spec.sinks],
        ingest=ingest,
        memory=memory,
        yaml_content=yaml_content,
    )


def export_run_report_sync(
    role: RoleDefinition,
    result: RunResult | AutonomousResult,
    prompt: str,
    output_path: Path,
    *,
    template_name: str = "default",
    dry_run: bool = False,
) -> Path:
    """Export a markdown report from a run result (sync)."""
    from initrunner.report import export_report

    return export_report(
        role, result, prompt, output_path, template_name=template_name, dry_run=dry_run
    )
