"""Execution infrastructure helpers for team mode."""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from initrunner.team.schema import TeamDefinition


@contextmanager
def persona_env(env: dict[str, str]) -> Generator[None, None, None]:
    """Temporarily set environment variables for a persona run."""
    old: dict[str, str | None] = {}
    for k, v in env.items():
        old[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        yield
    finally:
        for k, prev in old.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


def setup_team_tracing(team: TeamDefinition) -> Any:
    """Initialize tracing for a team run if observability is configured.

    Returns the provider (for shutdown) or None.
    """
    if team.spec.observability is None:
        return None
    from initrunner.observability import setup_tracing

    return setup_tracing(team.spec.observability, team.metadata.name)


def resolve_team_model(team: TeamDefinition) -> None:
    """Resolve the team's model in-place if it's unresolved or None."""
    from initrunner.agent.loader import _auto_detect_model
    from initrunner.agent.schema.base import ModelConfig, PartialModelConfig

    model = team.spec.model
    if model is not None and model.is_resolved():
        # Convert to concrete ModelConfig if needed
        if not isinstance(model, ModelConfig):
            team.spec.model = ModelConfig(**model.model_dump())
        return

    prov, name, base_url, api_key_env = _auto_detect_model()
    base = model or PartialModelConfig()
    team.spec.model = ModelConfig(
        provider=prov,
        name=name,
        base_url=base_url or base.base_url,
        api_key_env=api_key_env or base.api_key_env,
        temperature=base.temperature,
        max_tokens=base.max_tokens,
        context_window=base.context_window,
    )
