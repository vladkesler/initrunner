"""FastAPI route-level authorization via ``Depends(requires(...))``.

When Cerbos is disabled (``app.state.authz is None``), every dependency is
a pure no-op that returns an :class:`AuthzGuard` with the current principal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request

from initrunner.authz import ANONYMOUS, Principal

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from initrunner.authz import CerbosAuthz

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AuthzGuard -- returned by every ``requires()`` dependency
# ---------------------------------------------------------------------------


@dataclass
class AuthzGuard:
    """Result of a successful authorization check.

    Routes use ``guard.principal`` to access the authenticated identity.
    """

    principal: Principal


# ---------------------------------------------------------------------------
# requires() dependency factory
# ---------------------------------------------------------------------------


def requires(
    resource_kind: str,
    action: str,
    *,
    resource_id_param: str | None = None,
) -> Callable[..., Coroutine[Any, Any, AuthzGuard]]:
    """FastAPI dependency factory for Cerbos authorization.

    Usage::

        @router.get("/api/roles")
        async def list_roles(
            request: Request,
            guard: AuthzGuard = Depends(requires(AGENT, READ)),
        ):
            ...

        @router.put("/api/roles/{role_id}")
        async def update_role(
            role_id: str,
            request: Request,
            guard: AuthzGuard = Depends(requires(AGENT, WRITE, resource_id_param="role_id")),
        ):
            ...
    """

    async def _dependency(request: Request) -> AuthzGuard:
        authz: CerbosAuthz | None = getattr(request.app.state, "authz", None)
        principal: Principal = getattr(request.state, "principal", ANONYMOUS)

        if authz is None:
            return AuthzGuard(principal=principal)

        resource_id = "*"
        if resource_id_param is not None:
            resource_id = request.path_params.get(resource_id_param, "*")

        resource_attrs: dict[str, Any] | None = None
        resolvers = getattr(request.app.state, "resource_resolvers", {})
        resolver = resolvers.get(resource_kind)
        if resolver is not None and resource_id != "*":
            resource_attrs = await resolver(request, resource_id)

        allowed = await authz.check_async(
            principal,
            resource_kind,
            action,
            resource_id=resource_id,
            resource_attrs=resource_attrs,
        )
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied: {action} on {resource_kind}/{resource_id}",
            )

        return AuthzGuard(principal=principal)

    return _dependency


# ---------------------------------------------------------------------------
# PlanResources-based filtering for list endpoints
# ---------------------------------------------------------------------------


@dataclass
class ResourceFilter:
    """Result of a Cerbos ``PlanResources`` call for list filtering."""

    allow_all: bool = False
    deny_all: bool = False
    condition: dict[str, Any] | None = None

    def should_include(self, resource_attrs: dict[str, str]) -> bool:
        """Evaluate this filter against a single resource's attributes."""
        if self.allow_all:
            return True
        if self.deny_all:
            return False
        if self.condition is None:
            return True  # fail-open if we can't evaluate
        return _evaluate_condition(self.condition, resource_attrs)


async def get_resource_filter(
    request: Request,
    resource_kind: str,
    action: str,
) -> ResourceFilter:
    """Get a PlanResources-based filter for list endpoints.

    Returns ``ResourceFilter(allow_all=True)`` when Cerbos is disabled.
    """
    authz: CerbosAuthz | None = getattr(request.app.state, "authz", None)
    if authz is None:
        return ResourceFilter(allow_all=True)

    principal: Principal = getattr(request.state, "principal", ANONYMOUS)
    plan = await authz.plan_async(principal, resource_kind, action)

    if plan.kind == "ALWAYS_ALLOWED":
        return ResourceFilter(allow_all=True)
    if plan.kind == "ALWAYS_DENIED":
        return ResourceFilter(deny_all=True)
    return ResourceFilter(condition=plan.condition)


# ---------------------------------------------------------------------------
# Starlette helper (for the OpenAI-compatible server, which lacks Depends)
# ---------------------------------------------------------------------------


async def check_starlette_request(
    request: Request,
    resource_kind: str,
    action: str,
    resource_id: str = "*",
) -> Principal:
    """Check authorization for a Starlette (non-FastAPI) handler.

    Returns the authenticated :class:`Principal`, or raises
    ``HTTPException(403)`` on deny.  When Cerbos is disabled, returns the
    principal unconditionally.
    """
    authz: CerbosAuthz | None = getattr(request.app.state, "authz", None)
    principal: Principal = getattr(request.state, "principal", ANONYMOUS)

    if authz is None:
        return principal

    allowed = await authz.check_async(principal, resource_kind, action, resource_id)
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")

    return principal


# ---------------------------------------------------------------------------
# Condition AST evaluator for PlanResources
# ---------------------------------------------------------------------------


def _resolve_field(operand: Any, attrs: dict[str, str]) -> str:
    """Resolve a field reference in a condition operand to its value."""
    if isinstance(operand, dict):
        # Cerbos field reference like {"name": "request.resource.attr.name"}
        name = operand.get("name", "")
        # Strip the "request.resource.attr." prefix
        prefix = "request.resource.attr."
        if name.startswith(prefix):
            attr_key = name[len(prefix) :]
            return attrs.get(attr_key, "")
    return str(operand)


def _resolve_value(operand: Any) -> str:
    """Resolve a literal value operand."""
    if isinstance(operand, dict):
        return str(operand.get("value", ""))
    return str(operand)


def _resolve_values(operand: Any) -> set[str]:
    """Resolve a list-of-values operand (for ``in`` operator)."""
    if isinstance(operand, dict):
        vals = operand.get("values", [])
        return {str(v) for v in vals}
    if isinstance(operand, list):
        return {str(v) for v in operand}
    return {str(operand)}


def _evaluate_condition(node: dict[str, Any], attrs: dict[str, str]) -> bool:
    """Evaluate a Cerbos PlanResources condition AST against resource attributes."""
    op = node.get("operator", "")
    operands = node.get("operands", [])

    if op == "eq":
        if len(operands) < 2:
            return True
        return _resolve_field(operands[0], attrs) == _resolve_value(operands[1])
    if op == "ne":
        if len(operands) < 2:
            return True
        return _resolve_field(operands[0], attrs) != _resolve_value(operands[1])
    if op == "in":
        if len(operands) < 2:
            return True
        return _resolve_field(operands[0], attrs) in _resolve_values(operands[1])
    if op == "and":
        return all(_evaluate_condition(c, attrs) for c in operands)
    if op == "or":
        return any(_evaluate_condition(c, attrs) for c in operands)
    if op == "not":
        if operands:
            return not _evaluate_condition(operands[0], attrs)
        return True

    # Unknown operator -- fail-open with a warning
    _logger.warning("Unknown PlanResources condition operator: %s, allowing access", op)
    return True


# ---------------------------------------------------------------------------
# Resource attribute resolver for agent-based resources
# ---------------------------------------------------------------------------


async def agent_attrs_resolver(request: Request, resource_id: str) -> dict[str, Any]:
    """Resolve agent metadata for Cerbos resource attributes.

    Caches the loaded role on ``request.state`` so route handlers
    can reuse it via ``getattr(request.state, '_role_cache', {}).get(resource_id)``.
    """
    cache: dict[str, Any] | None = getattr(request.state, "_role_cache", None)
    if cache is not None and resource_id in cache:
        role = cache[resource_id]
    else:
        try:
            from initrunner.api._helpers import load_role_async, resolve_role_path

            path = await resolve_role_path(request, resource_id)
            role = await load_role_async(path)
        except Exception:
            return {}
        if cache is None:
            cache = {}
            request.state._role_cache = cache
        cache[resource_id] = role

    return {
        "author": role.metadata.author,
        "team": role.metadata.team,
        "tags": role.metadata.tags,
    }
