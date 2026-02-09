"""Base types for the sink system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


@dataclass
class SinkPayload:
    agent_name: str
    run_id: str
    prompt: str
    output: str
    success: bool
    error: str | None
    tokens_in: int
    tokens_out: int
    duration_ms: int
    model: str
    provider: str
    trigger_type: str | None = None
    trigger_metadata: dict[str, str] = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_run(
        cls,
        result: object,
        *,
        agent_name: str,
        model: str,
        provider: str,
        prompt: str,
        trigger_type: str | None = None,
        trigger_metadata: dict[str, str] | None = None,
        timestamp: str = "",
    ) -> SinkPayload:
        """Build a payload from a RunResult-like object.

        Avoids importing RunResult here by reading attributes dynamically.
        """
        from datetime import UTC, datetime

        return cls(
            agent_name=agent_name,
            run_id=getattr(result, "run_id", ""),
            prompt=prompt,
            output=getattr(result, "output", ""),
            success=getattr(result, "success", True),
            error=getattr(result, "error", None),
            tokens_in=getattr(result, "tokens_in", 0),
            tokens_out=getattr(result, "tokens_out", 0),
            duration_ms=getattr(result, "duration_ms", 0),
            model=model,
            provider=provider,
            trigger_type=trigger_type,
            trigger_metadata=trigger_metadata or {},
            timestamp=timestamp or datetime.now(UTC).isoformat(),
        )


class SinkBase(ABC):
    """Abstract base for all sinks. Must never raise from send()."""

    @abstractmethod
    def send(self, payload: SinkPayload) -> None: ...
