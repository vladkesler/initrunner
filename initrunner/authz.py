"""Cerbos authorization: config, principal, client wrapper, and resource constants.

Provides opt-in ABAC authorization via a Cerbos PDP sidecar.  When the
``authz`` optional extra is not installed or ``INITRUNNER_CERBOS_ENABLED``
is unset, every function degrades gracefully (allow-all).

This module implements **agent-as-principal** policy enforcement: agents get
their own Cerbos identity derived from role metadata, and Cerbos governs
what tools an agent can use and which agents it can delegate to -- across
all execution paths (CLI, compose, daemon, API, pipeline).
"""

from __future__ import annotations

import contextvars
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config (Pydantic -- global, never in role YAML)
# ---------------------------------------------------------------------------


class AuthzConfig(BaseModel):
    """Global Cerbos authorization configuration.

    Loaded from environment variables via :func:`load_authz_config`.
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 3592
    tls: bool = False
    agent_checks: bool = False


# ---------------------------------------------------------------------------
# Principal (dataclass DTO)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Principal:
    """Identity for Cerbos authorization checks.

    For agent principals, ``attrs`` may contain non-string values
    (e.g. ``tags`` as ``list[str]``).  The Cerbos SDK accepts
    ``attr: dict[str, Any]``.
    """

    id: str
    roles: list[str]
    attrs: dict[str, Any] = field(default_factory=dict)


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

_current_authz: contextvars.ContextVar[CerbosAuthz | None] = contextvars.ContextVar(
    "_current_authz",
    default=None,
)

_current_agent_principal: contextvars.ContextVar[Principal | None] = contextvars.ContextVar(
    "_current_agent_principal",
    default=None,
)


def set_current_authz(authz: CerbosAuthz | None) -> contextvars.Token:
    """Set the per-request authz ContextVar."""
    return _current_authz.set(authz)


def get_current_authz() -> CerbosAuthz | None:
    """Read the per-request authz ContextVar."""
    return _current_authz.get()


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
    """Construct a Cerbos :class:`Principal` from role metadata.

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
# Cerbos client wrapper
# ---------------------------------------------------------------------------


class CerbosAuthz:
    """Thin sync + async wrapper around the Cerbos Python SDK (HTTP client).

    Uses the HTTP client (``cerbos.sdk.client``) instead of gRPC to avoid
    protobuf version incompatibilities.  All SDK imports are deferred so
    the module can be imported without the ``cerbos`` package installed.
    """

    def __init__(self, config: AuthzConfig) -> None:
        self._config = config
        scheme = "https" if config.tls else "http"
        self._http_url = f"{scheme}://{config.host}:{config.port}"

    @property
    def agent_checks_enabled(self) -> bool:
        """Whether agent-level Cerbos checks are active."""
        return self._config.agent_checks

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _to_cerbos_principal(principal: Principal) -> Any:
        from cerbos.sdk.model import Principal as CerbosPrincipal  # type: ignore[import-not-found]

        return CerbosPrincipal(
            principal.id,
            roles=set(principal.roles),
            attr=dict(principal.attrs),
        )

    @staticmethod
    def _to_resource_list(
        resource_id: str, resource_kind: str, action: str, resource_attrs: dict[str, Any] | None
    ) -> Any:
        from cerbos.sdk.model import (  # type: ignore[import-not-found]
            Resource,
            ResourceAction,
            ResourceList,
        )

        resource = Resource(resource_id, resource_kind, attr=resource_attrs or {})
        return ResourceList(resources=[ResourceAction(resource, actions={action})])

    @staticmethod
    def _is_allowed(resp: Any, resource_id: str, action: str) -> bool:
        result = resp.get_resource(resource_id)
        if result is not None:
            return result.is_allowed(action)
        return False

    # -- sync ---------------------------------------------------------------

    def check(
        self,
        principal: Principal,
        resource_kind: str,
        action: str,
        resource_id: str = "*",
        resource_attrs: dict[str, Any] | None = None,
    ) -> bool:
        """Return True if *principal* is allowed to perform *action*."""
        from cerbos.sdk.client import CerbosClient  # type: ignore[import-not-found]

        cerbos_principal = self._to_cerbos_principal(principal)
        resource_list = self._to_resource_list(resource_id, resource_kind, action, resource_attrs)

        with CerbosClient(self._http_url, tls_verify=self._config.tls) as client:
            resp = client.check_resources(principal=cerbos_principal, resources=resource_list)
            return self._is_allowed(resp, resource_id, action)

    # -- async --------------------------------------------------------------

    async def check_async(
        self,
        principal: Principal,
        resource_kind: str,
        action: str,
        resource_id: str = "*",
        resource_attrs: dict[str, Any] | None = None,
    ) -> bool:
        """Async variant of :meth:`check`."""
        from cerbos.sdk.client import AsyncCerbosClient  # type: ignore[import-not-found]

        cerbos_principal = self._to_cerbos_principal(principal)
        resource_list = self._to_resource_list(resource_id, resource_kind, action, resource_attrs)

        async with AsyncCerbosClient(self._http_url, tls_verify=self._config.tls) as client:
            resp = await client.check_resources(principal=cerbos_principal, resources=resource_list)
            return self._is_allowed(resp, resource_id, action)

    # -- health -------------------------------------------------------------

    def health_check(self) -> tuple[bool, str]:
        """Verify PDP connectivity.  Returns ``(ok, message)``."""
        try:
            from cerbos.sdk.client import CerbosClient  # type: ignore[import-not-found]

            with CerbosClient(self._http_url, tls_verify=self._config.tls) as client:
                if client.is_healthy():
                    return True, f"Cerbos PDP reachable at {self._http_url}"
                return False, f"Cerbos PDP at {self._http_url} reports unhealthy"
        except Exception as exc:
            return False, (
                f"Cannot reach Cerbos PDP at {self._http_url}: {exc}\n"
                f"  Troubleshooting:\n"
                f"  - Verify Cerbos is running: docker ps | grep cerbos\n"
                f"  - Check the host/port in INITRUNNER_CERBOS_HOST / INITRUNNER_CERBOS_PORT\n"
                f"  - Default HTTP port is 3592"
            )


# ---------------------------------------------------------------------------
# Optional dependency check
# ---------------------------------------------------------------------------


def require_cerbos() -> None:
    """Check that the Cerbos SDK is importable, or raise with install hint."""
    try:
        import cerbos.sdk  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "Cerbos authorization requires: uv pip install initrunner[authz]"
        ) from None


# ---------------------------------------------------------------------------
# Environment-based config loader
# ---------------------------------------------------------------------------


def load_authz_config() -> AuthzConfig | None:
    """Load Cerbos config from environment variables.

    Returns ``None`` when ``INITRUNNER_CERBOS_ENABLED`` is not set to a
    truthy value, signalling that authorization is disabled.
    """
    if os.environ.get("INITRUNNER_CERBOS_ENABLED", "").lower() not in ("1", "true", "yes"):
        return None

    return AuthzConfig(
        enabled=True,
        host=os.environ.get("INITRUNNER_CERBOS_HOST", "127.0.0.1"),
        port=int(os.environ.get("INITRUNNER_CERBOS_PORT", "3592")),
        tls=os.environ.get("INITRUNNER_CERBOS_TLS", "").lower() in ("1", "true"),
        agent_checks=os.environ.get("INITRUNNER_CERBOS_AGENT_CHECKS", "").lower()
        in ("1", "true", "yes"),
    )
