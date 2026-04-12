"""MCP hub models."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "McpAgentRefResponse",
    "McpHealthResponse",
    "McpHealthSummaryResponse",
    "McpPlaygroundRequest",
    "McpPlaygroundResponse",
    "McpRegistryEntryResponse",
    "McpServerResponse",
    "McpToolResponse",
]


class McpAgentRefResponse(BaseModel):
    agent_name: str
    agent_id: str
    role_path: str
    tool_filter: list[str] = []
    tool_exclude: list[str] = []
    tool_prefix: str | None = None
    defer: bool = False


class McpServerResponse(BaseModel):
    server_id: str
    display_name: str
    transport: str
    command: str | None = None
    args: list[str] = []
    url: str | None = None
    agent_refs: list[McpAgentRefResponse] = []
    health_status: str | None = None
    health_checked_at: str | None = None
    cache_age_seconds: float | None = None


class McpToolResponse(BaseModel):
    name: str
    description: str
    input_schema: dict = {}


class McpHealthResponse(BaseModel):
    server_id: str
    status: str
    latency_ms: int
    tool_count: int
    error: str | None = None
    checked_at: str


class McpPlaygroundRequest(BaseModel):
    server_id: str
    tool_name: str
    arguments: dict = {}


class McpPlaygroundResponse(BaseModel):
    tool_name: str
    output: str
    duration_ms: int
    success: bool
    error: str | None = None


class McpRegistryEntryResponse(BaseModel):
    name: str
    display_name: str
    description: str
    category: str
    transport: str
    command: str | None = None
    args: list[str] = []
    url: str | None = None
    install_hint: str = ""
    homepage: str = ""
    tags: list[str] = []


class McpHealthSummaryResponse(BaseModel):
    total: int
    healthy: int
    unhealthy: int
