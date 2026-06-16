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
    """One-time: load config and build the policy engine, cached at module level.

    Fail-fast: when ``INITRUNNER_POLICY_DIR`` is set but policy loading
    fails, the error propagates (operator explicitly opted in).

    The built engine is cached in ``_cached_engine`` (a plain module global that
    persists across runs). It is established on the per-run ``_current_engine``
    ContextVar by :func:`_enter_agent_context`, **not here**: every
    ``execute_run`` spins up a fresh event loop / fresh ``contextvars`` context,
    so a ContextVar set during the first run's build would be invisible to every
    later run -- silently disabling tool authorization after the first run.
    """
    global _cached_engine, _cached_config, _authz_resolved
    if _authz_resolved:
        return
    _authz_resolved = True

    from initrunner.authz import load_authz_config, load_engine

    config = load_authz_config()
    if config is None:
        return

    engine = load_engine(config)
    info = engine.info()
    _cached_engine = engine
    _cached_config = config
    _logger.info(
        "Policy engine enabled: %d policies, %d rules",
        info.policy_count,
        info.rule_count,
    )


def _enter_agent_context(
    role: RoleDefinition,
) -> tuple[contextvars.Token, contextvars.Token] | None:
    """Establish the policy engine + agent principal ContextVars for this run.

    Both are set **per run** (and reset by :func:`_exit_agent_context`). The
    engine is re-established every run from the persistent module cache because
    each ``execute_run`` runs in its own event loop / ``contextvars`` context;
    relying on a process-once ContextVar set would make tool authorization
    no-op on every run after the first.
    """
    _ensure_authz()
    if _cached_engine is None:
        return None

    from initrunner.authz import (
        agent_principal_from_role,
        set_current_agent_principal,
        set_current_engine,
    )

    engine_token = set_current_engine(_cached_engine)
    principal = agent_principal_from_role(role.metadata)
    principal_token = set_current_agent_principal(principal)
    return engine_token, principal_token


def _exit_agent_context(tokens: tuple[contextvars.Token, contextvars.Token] | None) -> None:
    """Reset the policy engine + agent principal ContextVars."""
    if tokens is None:
        return

    from initrunner.authz import _current_agent_principal, _current_engine

    engine_token, principal_token = tokens
    _current_agent_principal.reset(principal_token)
    _current_engine.reset(engine_token)
