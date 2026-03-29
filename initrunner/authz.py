"""Policy authorization: config, principal, engine wrapper, and resource constants.

Provides opt-in ABAC authorization via an embedded initguard policy engine.
When ``INITRUNNER_POLICY_DIR`` is unset, every function degrades gracefully
(allow-all).

This module implements **agent-as-principal** policy enforcement: agents get
their own identity derived from role metadata, and the policy engine governs
what tools an agent can use and which agents it can delegate to -- across
all execution paths (CLI, compose, daemon, API, pipeline).
"""

from __future__ import annotations

import contextvars
import logging
import os

from initguard import (  # type: ignore[import-not-found]
    Decision,
    PolicyEngine,
    Principal,
    load_policies,
)
from pydantic import BaseModel

_logger = logging.getLogger(__name__)

# Re-export for consumers
__all__ = [
    "AuthzConfig",
    "Decision",
    "Principal",
    "agent_principal_from_role",
    "get_current_agent_principal",
    "get_current_engine",
    "load_authz_config",
    "load_engine",
    "set_current_agent_principal",
    "set_current_engine",
]

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class AuthzConfig(BaseModel):
    """Policy authorization configuration.

    Loaded from environment variables via :func:`load_authz_config`.
    """

    policy_dir: str
    agent_checks: bool = True


# ---------------------------------------------------------------------------
# Resource kinds and actions
# ---------------------------------------------------------------------------

AGENT = "agent"
MEMORY = "memory"
AUDIT = "audit"
INGEST = "ingest"
DAEMON = "daemon"
TOOL = "tool"

READ = "read"
WRITE = "write"
DELETE = "delete"
EXECUTE = "execute"
DELEGATE = "delegate"

# ---------------------------------------------------------------------------
# Per-request / per-run ContextVars
# ---------------------------------------------------------------------------

_current_engine: contextvars.ContextVar[PolicyEngine | None] = contextvars.ContextVar(
    "_current_engine",
    default=None,
)

_current_agent_principal: contextvars.ContextVar[Principal | None] = contextvars.ContextVar(
    "_current_agent_principal",
    default=None,
)


def set_current_engine(engine: PolicyEngine | None) -> contextvars.Token:
    """Set the per-process policy engine ContextVar."""
    return _current_engine.set(engine)


def get_current_engine() -> PolicyEngine | None:
    """Read the per-process policy engine ContextVar."""
    return _current_engine.get()


def set_current_agent_principal(principal: Principal | None) -> contextvars.Token:
    """Set the per-run agent principal ContextVar."""
    return _current_agent_principal.set(principal)


def get_current_agent_principal() -> Principal | None:
    """Read the per-run agent principal ContextVar."""
    return _current_agent_principal.get()


# ---------------------------------------------------------------------------
# Agent principal factory
# ---------------------------------------------------------------------------


def agent_principal_from_role(metadata: object) -> Principal:
    """Construct a :class:`Principal` from role metadata.

    Parameters
    ----------
    metadata:
        A :class:`~initrunner.agent.schema.base.Metadata` instance (or any
        object with ``name``, ``team``, ``author``, ``tags``, ``version``
        attributes).

    Returns
    -------
    Principal
        With ``id="agent:<name>"``, roles ``["agent"]`` (plus
        ``"team:<team>"`` when team is set), and attrs containing
        ``team``, ``author``, ``tags`` (as native list), and ``version``.
    """
    name = getattr(metadata, "name", "unknown")
    team = getattr(metadata, "team", "")
    author = getattr(metadata, "author", "")
    tags = getattr(metadata, "tags", [])
    version = getattr(metadata, "version", "")

    roles = ["agent"]
    if team:
        roles.append(f"team:{team}")

    return Principal(
        id=f"agent:{name}",
        roles=roles,
        attrs={
            "team": team,
            "author": author,
            "tags": list(tags),
            "version": version,
        },
    )


# ---------------------------------------------------------------------------
# Engine loader
# ---------------------------------------------------------------------------


def load_engine(config: AuthzConfig) -> PolicyEngine:
    """Load policies from *config.policy_dir* and return a ready engine.

    Raises :class:`initguard.PolicyLoadError` on bad YAML or CEL syntax,
    and :class:`FileNotFoundError` when the directory does not exist.
    """
    policy_set = load_policies(config.policy_dir)
    return PolicyEngine(policy_set)


# ---------------------------------------------------------------------------
# Environment-based config loader
# ---------------------------------------------------------------------------


def load_authz_config() -> AuthzConfig | None:
    """Load policy config from environment variables.

    Returns ``None`` when ``INITRUNNER_POLICY_DIR`` is not set, signalling
    that policy authorization is disabled.
    """
    policy_dir = os.environ.get("INITRUNNER_POLICY_DIR", "").strip()
    if not policy_dir:
        return None

    agent_checks = os.environ.get("INITRUNNER_AGENT_CHECKS", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    return AuthzConfig(policy_dir=policy_dir, agent_checks=agent_checks)
