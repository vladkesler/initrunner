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
    port: int = 3592
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
    def tool_checks_enabled(self) -> bool:
        """Whether tool-level Cerbos checks are active."""
        return self._config.tool_checks

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

    def plan(
        self,
        principal: Principal,
        resource_kind: str,
        action: str,
    ) -> PlanResult:
        """Return a query plan for filtering resources."""
        from cerbos.sdk.client import CerbosClient  # type: ignore[import-not-found]
        from cerbos.sdk.model import ResourceDesc  # type: ignore[import-not-found]

        cerbos_principal = self._to_cerbos_principal(principal)
        resource_desc = ResourceDesc(resource_kind)

        with CerbosClient(self._http_url, tls_verify=self._config.tls) as client:
            resp = client.plan_resources(
                actions=action,
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
        from cerbos.sdk.client import AsyncCerbosClient  # type: ignore[import-not-found]

        cerbos_principal = self._to_cerbos_principal(principal)
        resource_list = self._to_resource_list(resource_id, resource_kind, action, resource_attrs)

        async with AsyncCerbosClient(self._http_url, tls_verify=self._config.tls) as client:
            resp = await client.check_resources(principal=cerbos_principal, resources=resource_list)
            return self._is_allowed(resp, resource_id, action)

    async def plan_async(
        self,
        principal: Principal,
        resource_kind: str,
        action: str,
    ) -> PlanResult:
        """Async variant of :meth:`plan`."""
        from cerbos.sdk.client import AsyncCerbosClient  # type: ignore[import-not-found]
        from cerbos.sdk.model import ResourceDesc  # type: ignore[import-not-found]

        cerbos_principal = self._to_cerbos_principal(principal)
        resource_desc = ResourceDesc(resource_kind)

        async with AsyncCerbosClient(self._http_url, tls_verify=self._config.tls) as client:
            resp = await client.plan_resources(
                actions=action,
                principal=cerbos_principal,
                resource=resource_desc,
            )
            return _plan_response_to_result(resp)

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


def _plan_response_to_result(resp: Any) -> PlanResult:
    """Convert a Cerbos ``PlanResourcesResponse`` to our ``PlanResult``."""
    plan_filter = getattr(resp, "filter", None)
    if plan_filter is None:
        return PlanResult(kind="ALWAYS_ALLOWED")

    kind = str(getattr(plan_filter, "kind", "KIND_ALWAYS_ALLOWED"))
    if "ALWAYS_DENIED" in kind:
        return PlanResult(kind="ALWAYS_DENIED")
    if "CONDITIONAL" in kind:
        condition = getattr(plan_filter, "condition", None)
        # Convert SDK condition objects to dicts for our evaluator
        if condition is not None and hasattr(condition, "to_dict"):
            condition = condition.to_dict()
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
        port=int(os.environ.get("INITRUNNER_CERBOS_PORT", "3592")),
        tls=os.environ.get("INITRUNNER_CERBOS_TLS", "").lower() in ("1", "true"),
        jwt_secret=os.environ.get("INITRUNNER_JWT_SECRET", ""),
        jwt_algorithm=os.environ.get("INITRUNNER_JWT_ALGORITHM", "HS256"),
        anonymous_roles=anonymous_roles,
        tool_checks=os.environ.get("INITRUNNER_CERBOS_TOOL_CHECKS", "").lower()
        in ("1", "true", "yes"),
    )
