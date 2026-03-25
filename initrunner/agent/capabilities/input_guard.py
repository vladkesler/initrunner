"""Input validation capability -- blocks agent runs that violate content policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic_ai.capabilities import AbstractCapability  # type: ignore[import-not-found]

from initrunner.agent.capabilities.content_guard import ContentBlockedError

if TYPE_CHECKING:
    from pydantic_ai import RunContext  # type: ignore[import-not-found]

    from initrunner.agent.schema.security import ContentPolicy


@dataclass
class InputGuardCapability(AbstractCapability[Any]):
    """Pre-run input validation.

    Raises :class:`ContentBlockedError` from ``before_run`` to abort the
    agent run when the user prompt violates the content policy.  Works for
    both streaming and non-streaming runs because ``before_run`` fires in
    both code paths (via the shared ``iter()`` implementation).
    """

    policy: ContentPolicy

    async def before_run(self, ctx: RunContext[Any]) -> None:  # type: ignore[override]
        from initrunner.agent.policies import validate_input_async
        from initrunner.agent.prompt import extract_text_from_prompt

        # Skip if caller already validated (API server sets this via metadata)
        if ctx.metadata and ctx.metadata.get("input_validated"):
            return

        if ctx.prompt is None:
            return
        prompt_text = extract_text_from_prompt(ctx.prompt)
        validation = await validate_input_async(prompt_text, self.policy, model_override=ctx.model)
        if not validation.valid:
            raise ContentBlockedError(validation.reason)
