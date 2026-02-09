"""Role discovery, validation, and detail endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from initrunner.api._helpers import resolve_role_path
from initrunner.api.models import (
    RoleCreateRequest,
    RoleDetail,
    RoleGenerateRequest,
    RoleListResponse,
    RoleYamlUpdateRequest,
    ValidateRequest,
    ValidationResponse,
)
from initrunner.api.state import RoleRegistry, role_path_to_id
from initrunner.services import role_to_detail, role_to_summary

router = APIRouter(prefix="/api/roles", tags=["roles"])


def _validate_search_dirs(raw_dirs: str | None) -> list[Path]:
    """Parse and validate directory list, rejecting path traversal attempts."""
    if not raw_dirs:
        return [Path(".")]
    result: list[Path] = []
    for d in raw_dirs.split(","):
        d = d.strip()
        if not d:
            continue
        p = Path(d)
        # Reject traversal components
        if ".." in p.parts:
            raise HTTPException(
                status_code=400,
                detail=f"Path traversal not allowed: {d}",
            )
        result.append(p)
    return result or [Path(".")]


def _get_registry(request: Request) -> RoleRegistry:
    return request.app.state.role_registry


@router.get("", response_model=RoleListResponse)
async def list_roles(
    request: Request,
    dirs: Annotated[str | None, Query(description="Comma-separated directories to scan")] = None,
):
    """Discover and list all role YAML files."""
    import asyncio

    if dirs:
        from initrunner.services import discover_roles_sync

        search_dirs = _validate_search_dirs(dirs)
        discovered = await asyncio.to_thread(discover_roles_sync, search_dirs)
    else:
        registry = _get_registry(request)
        discovered = await asyncio.to_thread(registry.discover)

    roles = [role_to_summary(d.path, d.role, d.error) for d in discovered]
    return RoleListResponse(roles=roles)


@router.get("/{role_id}", response_model=RoleDetail)
async def get_role(role_id: str, request: Request):
    """Get full detail for a single role."""
    import asyncio

    path = await resolve_role_path(request, role_id)

    from initrunner.agent.loader import RoleLoadError, load_role

    try:
        role = await asyncio.to_thread(load_role, path)
    except RoleLoadError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    return role_to_detail(path, role)


@router.post("/validate", response_model=ValidationResponse)
async def validate_role(req: ValidateRequest, request: Request):
    """Validate a role definition file."""
    import asyncio

    from initrunner.services import validate_role_sync

    path = Path(req.path).resolve()

    # Restrict validation to configured role directories to prevent path traversal
    registry = _get_registry(request)
    allowed_dirs = [d.resolve() for d in registry.role_dirs]
    if not any(str(path).startswith(str(d)) for d in allowed_dirs):
        raise HTTPException(
            status_code=403,
            detail="Path is outside of configured role directories",
        )

    if not path.exists():
        return ValidationResponse(valid=False, error=f"File not found: {req.path}")

    result = await asyncio.to_thread(validate_role_sync, path)
    summary = role_to_summary(result.path, result.role, result.error) if result.role else None
    return ValidationResponse(valid=result.role is not None, error=result.error, role=summary)


@router.post("", status_code=201)
async def create_role(req: RoleCreateRequest, request: Request):
    """Create a new role by saving YAML content to disk."""
    import asyncio
    import re

    import yaml

    from initrunner.services import save_role_yaml_sync

    # Parse YAML to extract name for file path
    try:
        raw = yaml.safe_load(req.yaml_content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}") from None

    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="YAML must be a mapping")

    name = raw.get("metadata", {}).get("name", "")
    if not name or not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", name):
        raise HTTPException(
            status_code=400,
            detail="metadata.name must match ^[a-z0-9][a-z0-9-]*[a-z0-9]$",
        )

    # Write to the first configured role directory
    registry = _get_registry(request)
    if not registry.role_dirs:
        raise HTTPException(status_code=500, detail="No role directories configured")

    target_dir = registry.role_dirs[0]
    target_path = target_dir / f"{name}.yaml"

    if target_path.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Role file already exists: {target_path}",
        )

    try:
        role = await asyncio.to_thread(save_role_yaml_sync, target_path, req.yaml_content)
    except (ValueError, Exception) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    # Invalidate cache so the new role shows up
    registry.invalidate()

    return {
        "id": role_path_to_id(target_path),
        "path": str(target_path),
        "name": role.metadata.name,
    }


@router.post("/generate")
async def generate_role_yaml(req: RoleGenerateRequest, request: Request):
    """Generate role YAML from a natural language description using AI."""
    import asyncio

    from initrunner.services import generate_role_sync

    try:
        yaml_text = await asyncio.to_thread(
            generate_role_sync,
            req.description,
            provider=req.provider,
            name_hint=req.name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from None

    return {"yaml_content": yaml_text}


@router.put("/{role_id}")
async def update_role(role_id: str, req: RoleYamlUpdateRequest, request: Request):
    """Update an existing role's YAML content."""
    import asyncio

    from initrunner.services import save_role_yaml_sync

    registry = _get_registry(request)
    path = await resolve_role_path(request, role_id)

    # Verify path is within allowed directories
    allowed_dirs = [d.resolve() for d in registry.role_dirs]
    resolved = path.resolve()
    if not any(str(resolved).startswith(str(d)) for d in allowed_dirs):
        raise HTTPException(
            status_code=403,
            detail="Role is outside of configured role directories",
        )

    try:
        role = await asyncio.to_thread(save_role_yaml_sync, path, req.yaml_content)
    except (ValueError, Exception) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    registry.invalidate()

    return {
        "id": role_id,
        "path": str(path),
        "name": role.metadata.name,
        "valid": True,
    }
