"""Sense-aware routing sink for compose orchestration.

Wraps multiple ``DelegateSink`` instances and selects which one(s) to
forward to based on keyword scoring and optional LLM tiebreak — the same
``sense`` logic used by ``--sense`` in the CLI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from initrunner._log import get_logger
from initrunner.services.role_selector import RoleCandidate, select_candidate_sync
from initrunner.sinks.base import SinkBase, SinkPayload

if TYPE_CHECKING:
    from initrunner.compose.delegate_sink import DelegateSink

logger = get_logger("compose.router")


class RouterSink(SinkBase):
    """Sense-aware routing wrapper around multiple DelegateSinks.

    Instead of fan-out to all targets (``strategy: all``), selects the
    best-matching target using keyword scoring (``keyword``) or keyword +
    LLM tiebreak (``sense``).
    """

    def __init__(
        self,
        delegate_sinks: dict[str, DelegateSink],
        target_candidates: list[RoleCandidate],
        strategy: Literal["keyword", "sense"],
    ) -> None:
        self._delegate_sinks = delegate_sinks
        self._target_candidates = target_candidates
        self._strategy = strategy
        # Build name→candidate lookup for matching selection result back to sink
        self._name_to_sink = delegate_sinks

    def send(self, payload: SinkPayload) -> None:
        """Route payload to the best-matching target sink."""
        try:
            allow_llm = self._strategy == "sense"
            text = payload.output

            result = select_candidate_sync(
                text,
                self._target_candidates,
                allow_llm=allow_llm,
            )

            selected_name = result.candidate.name

            # If output scoring was inconclusive (fallback), try the original prompt
            if result.method == "fallback":
                original_prompt = payload.trigger_metadata.get(
                    "_compose_original_prompt", payload.prompt
                )
                if original_prompt and original_prompt != text:
                    retry = select_candidate_sync(
                        original_prompt,
                        self._target_candidates,
                        allow_llm=allow_llm,
                    )
                    if retry.method != "fallback":
                        result = retry
                        selected_name = result.candidate.name

            sink = self._name_to_sink.get(selected_name)
            if sink is None:
                logger.warning(
                    "Router selected unknown target %r; falling back to first sink",
                    selected_name,
                )
                sink = next(iter(self._delegate_sinks.values()))

            # Stuff routing diagnostics into the reason field for audit
            score_info = f"score={result.top_score:.2f}" if result.top_score else ""
            reason = f"sense:{result.method} selected={selected_name}"
            if score_info:
                reason += f" {score_info}"

            # Inject routing reason into trigger_metadata so DelegateSink can audit it
            payload.trigger_metadata["_compose_route_reason"] = reason

            logger.debug(
                "Routed %s -> %s (%s)",
                payload.agent_name,
                selected_name,
                reason,
            )

            sink.send(payload)

        except Exception as exc:
            logger.error("Router error: %s; falling back to first sink", exc)
            # Fallback: send to first available sink
            first_sink = next(iter(self._delegate_sinks.values()), None)
            if first_sink is not None:
                first_sink.send(payload)

    def close(self) -> None:
        """Close all wrapped delegate sinks."""
        for sink in self._delegate_sinks.values():
            sink.close()
