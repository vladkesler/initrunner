"""Skill CRUD models."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "RequirementStatusResponse",
    "SkillAgentRef",
    "SkillContentResponse",
    "SkillContentSaveRequest",
    "SkillContentSaveResponse",
    "SkillCreateRequest",
    "SkillCreateResponse",
    "SkillDeleteBlockedResponse",
    "SkillDetail",
    "SkillSummary",
    "SkillToolSummary",
]


class RequirementStatusResponse(BaseModel):
    name: str
    kind: str  # "env" | "bin"
    met: bool
    detail: str


class SkillToolSummary(BaseModel):
    type: str
    summary: str


class SkillSummary(BaseModel):
    id: str
    name: str
    description: str
    scope: str
    has_tools: bool
    tool_count: int
    is_directory_form: bool
    requirements_met: bool
    requirement_count: int
    path: str
    error: str | None = None


class SkillAgentRef(BaseModel):
    id: str
    name: str


class SkillDetail(BaseModel):
    id: str
    name: str
    description: str
    scope: str
    path: str
    is_directory_form: bool
    has_resources: bool = False
    error: str | None = None
    license: str = ""
    compatibility: str = ""
    metadata: dict[str, str] = {}
    tools: list[SkillToolSummary] = []
    requirements: list[RequirementStatusResponse] = []
    requirements_met: bool = True
    prompt: str = ""
    prompt_preview: str = ""
    used_by_agents: list[SkillAgentRef] = []


class SkillContentResponse(BaseModel):
    content: str
    path: str


class SkillContentSaveRequest(BaseModel):
    content: str


class SkillContentSaveResponse(BaseModel):
    """Validate-before-save: valid=False means content was NOT written."""

    path: str
    valid: bool
    issues: list[str] = Field(default_factory=list)


class SkillCreateRequest(BaseModel):
    name: str
    directory: str
    provider: str = "openai"


class SkillCreateResponse(BaseModel):
    id: str
    path: str
    name: str


class SkillDeleteBlockedResponse(BaseModel):
    """Returned when delete is blocked by resource files."""

    id: str
    path: str
    blocked: bool = True
    resource_files: list[str] = Field(default_factory=list)
    message: str = ""
