"""Cerbos authorization: config, principal, client wrapper, and resource constants.

Provides opt-in ABAC authorization via a Cerbos PDP sidecar.  When the
``authz`` optional extra is not installed or ``INITRUNNER_CERBOS_ENABLED``
is unset, every function degrades gracefully (allow-all).
"""

from __future__ import annotations

import contextvars
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

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
    port: int = 3593
    tls: bool = False
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    anonymous_roles: list[str] = Field(default_factory=lambda: ["anonymous"])
    tool_checks: bool = False


# ---------------------------------------------------------------------------
# Principal (dataclass DTO)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Principal:
    """Identity extracted from a JWT or defaulted for anonymous access."""

    id: str
    roles: list[str]
    attrs: dict[str, str] = field(default_factory=dict)


ANONYMOUS = Principal(id="anonymous", roles=["anonymous"])

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

# ---------------------------------------------------------------------------
# Per-request ContextVars (carry identity into tool calls)
# ---------------------------------------------------------------------------

_current_principal: contextvars.ContextVar[Principal | None] = contextvars.ContextVar(
    "_current_principal",
    default=None,
)
_current_authz: contextvars.ContextVar[CerbosAuthz | None] = contextvars.ContextVar(
    "_current_authz",
    default=None,
)


def set_current_principal(principal: Principal | None) -> contextvars.Token:
    """Set the per-request principal ContextVar."""
    return _current_principal.set(principal)


def get_current_principal() -> Principal | None:
    """Read the per-request principal ContextVar."""
    return _current_principal.get()


def set_current_authz(authz: CerbosAuthz | None) -> contextvars.Token:
    """Set the per-request authz ContextVar."""
    return _current_authz.set(authz)


def get_current_authz() -> CerbosAuthz | None:
    """Read the per-request authz ContextVar."""
    return _current_authz.get()


# ---------------------------------------------------------------------------
# PlanResources result
# ---------------------------------------------------------------------------


@dataclass
class PlanResult:
    """Simplified result from a Cerbos ``PlanResources`` call."""

    kind: str  # "ALWAYS_ALLOWED" | "ALWAYS_DENIED" | "CONDITIONAL"
    condition: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Cerbos client wrapper
# ---------------------------------------------------------------------------


class CerbosAuthz:
    """Thin sync + async wrapper around the Cerbos Python SDK.

    All SDK imports are deferred so the module can be imported without the
    ``cerbos`` package installed.
    """

    def __init__(self, config: AuthzConfig) -> None:
        self._config = config
        self._host = f"{config.host}:{config.port}"
        self._tls = config.tls

    @property
    def tool_checks_enabled(self) -> bool:
        """Whether tool-level Cerbos checks are active."""
        return self._config.tool_checks

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
        from cerbos.sdk.grpc.client import CerbosClient  # type: ignore[import-not-found]
        from cerbos.sdk.model import Principal as CerbosPrincipal  # type: ignore[import-not-found]
        from cerbos.sdk.model import (  # type: ignore[import-not-found]
            Resource,
            ResourceAction,
            ResourceList,
        )

        cerbos_principal = CerbosPrincipal(
            principal.id,
            roles=set(principal.roles),
            attr=dict(principal.attrs),
        )
        resource = Resource(resource_id, resource_kind, attr=resource_attrs or {})
        resource_list = ResourceList(
            resources=[ResourceAction(resource, actions={action})],
        )

        with CerbosClient(self._host, tls_verify=self._tls) as client:
            resp = client.check_resources(principal=cerbos_principal, resources=resource_list)
            return resp.is_allowed(resource_id, action)

    def plan(
        self,
        principal: Principal,
        resource_kind: str,
        action: str,
    ) -> PlanResult:
        """Return a query plan for filtering resources."""
        from cerbos.sdk.grpc.client import CerbosClient  # type: ignore[import-not-found]
        from cerbos.sdk.model import (  # type: ignore[import-not-found]
            PlanResourcesResponse,
            ResourceDesc,
        )
        from cerbos.sdk.model import Principal as CerbosPrincipal  # type: ignore[import-not-found]

        cerbos_principal = CerbosPrincipal(
            principal.id,
            roles=set(principal.roles),
            attr=dict(principal.attrs),
        )
        resource_desc = ResourceDesc(resource_kind)

        with CerbosClient(self._host, tls_verify=self._tls) as client:
            resp: PlanResourcesResponse = client.plan_resources(
                action=action,
                principal=cerbos_principal,
                resource=resource_desc,
            )
            return _plan_response_to_result(resp)

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
        from cerbos.sdk.grpc.client import AsyncCerbosClient  # type: ignore[import-not-found]
        from cerbos.sdk.model import Principal as CerbosPrincipal  # type: ignore[import-not-found]
        from cerbos.sdk.model import (  # type: ignore[import-not-found]
            Resource,
            ResourceAction,
            ResourceList,
        )

        cerbos_principal = CerbosPrincipal(
            principal.id,
            roles=set(principal.roles),
            attr=dict(principal.attrs),
        )
        resource = Resource(resource_id, resource_kind, attr=resource_attrs or {})
        resource_list = ResourceList(
            resources=[ResourceAction(resource, actions={action})],
        )

        async with AsyncCerbosClient(self._host, tls_verify=self._tls) as client:
            resp = await client.check_resources(principal=cerbos_principal, resources=resource_list)
            return resp.is_allowed(resource_id, action)

    async def plan_async(
        self,
        principal: Principal,
        resource_kind: str,
        action: str,
    ) -> PlanResult:
        """Async variant of :meth:`plan`."""
        from cerbos.sdk.grpc.client import AsyncCerbosClient  # type: ignore[import-not-found]
        from cerbos.sdk.model import (  # type: ignore[import-not-found]
            PlanResourcesResponse,
            ResourceDesc,
        )
        from cerbos.sdk.model import Principal as CerbosPrincipal  # type: ignore[import-not-found]

        cerbos_principal = CerbosPrincipal(
            principal.id,
            roles=set(principal.roles),
            attr=dict(principal.attrs),
        )
        resource_desc = ResourceDesc(resource_kind)

        async with AsyncCerbosClient(self._host, tls_verify=self._tls) as client:
            resp: PlanResourcesResponse = await client.plan_resources(
                action=action,
                principal=cerbos_principal,
                resource=resource_desc,
            )
            return _plan_response_to_result(resp)

    # -- health -------------------------------------------------------------

    def health_check(self) -> tuple[bool, str]:
        """Verify PDP connectivity.  Returns ``(ok, message)``."""
        try:
            from cerbos.sdk.grpc.client import CerbosClient  # type: ignore[import-not-found]
            from cerbos.sdk.model import (  # type: ignore[import-not-found]
                Principal as CerbosPrincipal,
            )
            from cerbos.sdk.model import (  # type: ignore[import-not-found]
                Resource,
                ResourceAction,
                ResourceList,
            )

            # Minimal check: verify connectivity with a no-op authz call
            p = CerbosPrincipal("_healthcheck", roles={"_healthcheck"})
            r = Resource("_healthcheck", "_healthcheck")
            rl = ResourceList(resources=[ResourceAction(r, actions={"read"})])

            with CerbosClient(self._host, tls_verify=self._tls) as client:
                client.check_resources(principal=p, resources=rl)

            return True, f"Cerbos PDP reachable at {self._host}"
        except Exception as exc:
            return False, (
                f"Cannot reach Cerbos PDP at {self._host}: {exc}\n"
                f"  Troubleshooting:\n"
                f"  - Verify Cerbos is running: docker ps | grep cerbos\n"
                f"  - Check the host/port in INITRUNNER_CERBOS_HOST / INITRUNNER_CERBOS_PORT\n"
                f"  - Default gRPC port is 3593, HTTP port is 3592"
            )


def _plan_response_to_result(resp: Any) -> PlanResult:
    """Convert a Cerbos ``PlanResourcesResponse`` to our ``PlanResult``."""
    kind = str(getattr(resp, "filter", {}).get("kind", "KIND_ALWAYS_ALLOWED"))
    if "ALWAYS_DENIED" in kind:
        return PlanResult(kind="ALWAYS_DENIED")
    if "CONDITIONAL" in kind:
        condition = getattr(resp, "filter", {}).get("condition")
        return PlanResult(kind="CONDITIONAL", condition=condition)
    return PlanResult(kind="ALWAYS_ALLOWED")


# ---------------------------------------------------------------------------
# Optional dependency check
# ---------------------------------------------------------------------------


def require_cerbos() -> None:
    """Check that the Cerbos SDK is importable, or raise with install hint."""
    try:
        import cerbos.sdk  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        raise RuntimeError("Cerbos authorization requires: pip install initrunner[authz]") from None


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

    anonymous_roles_raw = os.environ.get("INITRUNNER_CERBOS_ANONYMOUS_ROLES", "anonymous")
    anonymous_roles = [r.strip() for r in anonymous_roles_raw.split(",") if r.strip()]

    return AuthzConfig(
        enabled=True,
        host=os.environ.get("INITRUNNER_CERBOS_HOST", "127.0.0.1"),
        port=int(os.environ.get("INITRUNNER_CERBOS_PORT", "3593")),
        tls=os.environ.get("INITRUNNER_CERBOS_TLS", "").lower() in ("1", "true"),
        jwt_secret=os.environ.get("INITRUNNER_JWT_SECRET", ""),
        jwt_algorithm=os.environ.get("INITRUNNER_JWT_ALGORITHM", "HS256"),
        anonymous_roles=anonymous_roles,
        tool_checks=os.environ.get("INITRUNNER_CERBOS_TOOL_CHECKS", "").lower()
        in ("1", "true", "yes"),
    )
