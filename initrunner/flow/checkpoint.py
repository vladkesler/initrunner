"""Audit-backed checkpoint journal for durable, resumable flows.

The journal is the append-only audit store itself: each completed sub-agent
delegation is serialized and written through ``AuditLogger.append_checkpoint``,
keyed by ``(flow_run_id, service_name)`` and signed into a tamper-evident HMAC
chain. On resume, a checkpointed service is replayed from the journal instead
of being re-run, so an interrupted multi-agent flow can continue from where it
stopped.

This is the local-first, audit-native durability path. It needs no external
infrastructure (no Temporal/DBOS worker, no broker); the same signed ledger
that records agent runs doubles as the durable execution log.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from initrunner._log import get_logger
from initrunner.agent.executor_models import (
    ErrorCategory,
    PendingApproval,
    RunResult,
)
from initrunner.flow.graph import DelegationEnvelope

if TYPE_CHECKING:
    from initrunner.audit.logger import AuditLogger

logger = get_logger("flow.checkpoint")


def _serialize_messages(messages: list) -> str:
    """Serialize a PydanticAI message history to a JSON string.

    Uses ``ModelMessagesTypeAdapter`` so the message objects (TextPart,
    ToolCallPart, ToolReturnPart, etc.) round-trip cleanly, matching how the
    rest of the codebase persists history (see ``services/execution.py``).
    """
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    return ModelMessagesTypeAdapter.dump_json(messages).decode("utf-8")


def _deserialize_messages(raw: str) -> list:
    """Reconstruct a PydanticAI message history from its JSON string."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    return list(ModelMessagesTypeAdapter.validate_json(raw))


# ---------------------------------------------------------------------------
# Serialization helpers (envelope + result <-> JSON)
# ---------------------------------------------------------------------------


def _envelope_to_dict(envelope: DelegationEnvelope) -> dict:
    """Serialize a DelegationEnvelope to a plain dict.

    ``message_history`` is intentionally dropped here: it is serialized
    separately via ``serialize_message_history`` so the PydanticAI message
    objects round-trip cleanly.
    """
    return {
        "prompt": envelope.prompt,
        "trace": list(envelope.trace),
        "original_prompt": envelope.original_prompt,
        "source_service": envelope.source_service,
        "one_shot": envelope.one_shot,
        "topology_index": envelope.topology_index,
    }


def _envelope_from_dict(data: dict) -> DelegationEnvelope:
    """Reconstruct a DelegationEnvelope from a serialized dict."""
    return DelegationEnvelope(
        prompt=data.get("prompt", ""),
        trace=tuple(data.get("trace", [])),
        original_prompt=data.get("original_prompt", ""),
        source_service=data.get("source_service"),
        message_history=None,
        one_shot=data.get("one_shot", True),
        topology_index=data.get("topology_index", 0),
    )


def _result_to_dict(result: RunResult) -> dict:
    """Serialize a RunResult to a JSON-safe dict.

    ``event_timeline`` and ``judge_verdicts`` are dropped: they are large,
    audit-only telemetry that the replay path does not need.
    """
    return {
        "run_id": result.run_id,
        "output": result.output,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "total_tokens": result.total_tokens,
        "thinking_tokens": result.thinking_tokens,
        "reasoning_tokens": result.reasoning_tokens,
        "tool_calls": result.tool_calls,
        "duration_ms": result.duration_ms,
        "success": result.success,
        "error": result.error,
        "error_category": result.error_category.value if result.error_category else None,
        "tool_call_names": list(result.tool_call_names),
        "status": result.status,
        "pending_approvals": [
            {
                "tool_call_id": pa.tool_call_id,
                "tool_name": pa.tool_name,
                "arguments": pa.arguments,
            }
            for pa in result.pending_approvals
        ],
    }


def _result_from_dict(data: dict) -> RunResult:
    """Reconstruct a RunResult from a serialized dict."""
    category_raw = data.get("error_category")
    category = ErrorCategory(category_raw) if category_raw else None
    approvals = [
        PendingApproval(
            tool_call_id=pa["tool_call_id"],
            tool_name=pa["tool_name"],
            arguments=pa.get("arguments", {}),
        )
        for pa in data.get("pending_approvals", [])
    ]
    return RunResult(
        run_id=data.get("run_id", ""),
        output=data.get("output", ""),
        tokens_in=data.get("tokens_in", 0),
        tokens_out=data.get("tokens_out", 0),
        total_tokens=data.get("total_tokens", 0),
        thinking_tokens=data.get("thinking_tokens", 0),
        reasoning_tokens=data.get("reasoning_tokens", 0),
        tool_calls=data.get("tool_calls", 0),
        duration_ms=data.get("duration_ms", 0),
        success=data.get("success", True),
        error=data.get("error"),
        error_category=category,
        tool_call_names=list(data.get("tool_call_names", [])),
        status=data.get("status", "done"),
        pending_approvals=approvals,
    )


@dataclass(frozen=True)
class ReplayedCheckpoint:
    """A completed delegation recovered from the journal for replay."""

    envelope: DelegationEnvelope
    result: RunResult
    messages: list | None


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------


class CheckpointJournal:
    """Wraps an AuditLogger to record and replay flow checkpoints.

    A checkpoint is considered *replayable* (skip re-execution) only when the
    recorded run succeeded and was not paused for approval. Failed or paused
    services are always re-run on resume so the flow can make progress.
    """

    def __init__(self, audit_logger: AuditLogger) -> None:
        self._audit = audit_logger

    def record_completion(
        self,
        flow_run_id: str,
        service_name: str,
        sequence_number: int,
        envelope: DelegationEnvelope,
        result: RunResult,
        messages: list | None,
    ) -> None:
        """Serialize and persist one completed delegation. Never raises."""
        try:
            envelope_json = json.dumps(_envelope_to_dict(envelope))
            result_json = json.dumps(_result_to_dict(result))
            messages_json = _serialize_messages(messages) if messages else None
        except Exception as e:
            logger.error(
                "Failed to serialize checkpoint %s/%s: %s",
                flow_run_id,
                service_name,
                e,
            )
            return
        self._audit.append_checkpoint(
            flow_run_id=flow_run_id,
            service_name=service_name,
            sequence_number=sequence_number,
            envelope_json=envelope_json,
            result_json=result_json,
            message_history_json=messages_json,
        )

    def get_replay(self, flow_run_id: str, service_name: str) -> ReplayedCheckpoint | None:
        """Return a replayable checkpoint, or None to re-run the service.

        Returns None when no checkpoint exists, when deserialization fails, or
        when the recorded run was unsuccessful or paused (so it should re-run).
        """
        record = self._audit.get_checkpoint(flow_run_id, service_name)
        if record is None:
            return None
        try:
            envelope = _envelope_from_dict(json.loads(record.envelope_json))
            result = _result_from_dict(json.loads(record.result_json))
        except Exception as e:
            logger.error(
                "Failed to deserialize checkpoint %s/%s: %s",
                flow_run_id,
                service_name,
                e,
            )
            return None

        if not result.success or result.status == "paused":
            logger.debug(
                "Checkpoint %s/%s not replayable (success=%s status=%s); re-running",
                flow_run_id,
                service_name,
                result.success,
                result.status,
            )
            return None

        messages: list | None = None
        if record.message_history_json:
            messages = _deserialize_messages(record.message_history_json)

        return ReplayedCheckpoint(envelope=envelope, result=result, messages=messages)

    def completed_services(self, flow_run_id: str) -> list[str]:
        """Return service names with a recorded checkpoint, in order."""
        return self._audit.list_completed_services(flow_run_id)

    def prune(self, flow_run_id: str) -> None:
        """Delete all checkpoints for a completed flow run. Never raises."""
        self._audit.prune_flow_checkpoints(flow_run_id)
