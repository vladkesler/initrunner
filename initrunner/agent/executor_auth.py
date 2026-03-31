"""Agent principal scoping and authorization policy engine."""

from __future__ import annotations

import contextvars
import logging
from typing import Any

from initrunner.agent.schema.role import RoleDefinition

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mutable globals -- these live here and must be imported from this module.
# ---------------------------------------------------------------------------

_cached_engine: Any = None
_cached_config: Any = None
_authz_resolved = False


def _ensure_authz() -> None:
    """One-time: load config, build policy engine, set ContextVar.

    Fail-fast: when ``INITRUNNER_POLICY_DIR`` is set but policy loading
    fails, the error propagates (operator explicitly opted in).
    """
    global _cached_engine, _cached_config, _authz_resolved
    if _authz_resolved:
        return
    _authz_resolved = True

    from initrunner.authz import load_authz_config, load_engine, set_current_engine

    config = load_authz_config()
    if config is None:
        return

    engine = load_engine(config)
    info = engine.info()
    _cached_engine = engine
    _cached_config = config
    set_current_engine(engine)
    _logger.info(
        "Policy engine enabled: %d policies, %d rules",
        info.policy_count,
        info.rule_count,
    )


def _enter_agent_context(role: RoleDefinition) -> contextvars.Token | None:
    """Set the agent principal ContextVar for the current run."""
    _ensure_authz()
    if _cached_engine is None:
        return None

    from initrunner.authz import agent_principal_from_role, set_current_agent_principal

    principal = agent_principal_from_role(role.metadata)
    return set_current_agent_principal(principal)


def _exit_agent_context(token: contextvars.Token | None) -> None:
    """Reset the agent principal ContextVar."""
    if token is not None:
        from initrunner.authz import _current_agent_principal

        _current_agent_principal.reset(token)
