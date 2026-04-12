"""Agent memory and session history models."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "MemoryResponse",
    "SessionDetailResponse",
    "SessionMessageResponse",
    "SessionSummaryResponse",
]


class MemoryResponse(BaseModel):
    id: int
    content: str
    category: str
    memory_type: str
    created_at: str
    consolidated_at: str | None = None


class SessionSummaryResponse(BaseModel):
    session_id: str
    agent_name: str
    timestamp: str
    message_count: int
    preview: str


class SessionMessageResponse(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class SessionDetailResponse(BaseModel):
    session_id: str
    messages: list[SessionMessageResponse]
