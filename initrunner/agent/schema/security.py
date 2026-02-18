"""Security policy and resource configuration."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from initrunner.agent._subprocess import (
    DEFAULT_ENV_ALLOWLIST,
    DEFAULT_SENSITIVE_ENV_PREFIXES,
    DEFAULT_SENSITIVE_ENV_SUFFIXES,
)


class ContentPolicy(BaseModel):
    profanity_filter: bool = False
    blocked_input_patterns: list[str] = []
    blocked_output_patterns: list[str] = []
    output_action: Literal["strip", "block"] = "strip"
    llm_classifier_enabled: bool = False
    allowed_topics_prompt: str = ""
    max_prompt_length: Annotated[int, Field(gt=0)] = 50_000
    max_output_length: Annotated[int, Field(gt=0)] = 100_000
    redact_patterns: list[str] = []
    pii_redaction: bool = False

    @field_validator("blocked_input_patterns", "blocked_output_patterns", "redact_patterns")
    @classmethod
    def _validate_regex_patterns(cls, v: list[str]) -> list[str]:
        import re

        for pattern in v:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e
        return v


class ServerConfig(BaseModel):
    cors_origins: list[str] = []
    require_https: bool = False
    max_request_body_bytes: Annotated[int, Field(gt=0)] = 1_048_576
    max_conversations: int = 1000


class RateLimitConfig(BaseModel):
    requests_per_minute: Annotated[int, Field(gt=0)] = 60
    burst_size: Annotated[int, Field(gt=0)] = 10


class ResourceLimits(BaseModel):
    max_file_size_mb: Annotated[float, Field(gt=0)] = 50.0
    max_total_ingest_mb: Annotated[float, Field(gt=0)] = 500.0


class ToolSandboxConfig(BaseModel):
    allowed_custom_modules: list[str] = []
    blocked_custom_modules: list[str] = [
        "os",
        "subprocess",
        "shutil",
        "sys",
        "importlib",
        "ctypes",
        "socket",
        "http.server",
        "pickle",
        "shelve",
        "marshal",
        "code",
        "codeop",
        "threading",
        "_thread",
    ]
    mcp_command_allowlist: list[str] = []
    sensitive_env_prefixes: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SENSITIVE_ENV_PREFIXES)
    )
    sensitive_env_suffixes: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SENSITIVE_ENV_SUFFIXES)
    )
    env_allowlist: list[str] = Field(default_factory=lambda: list(DEFAULT_ENV_ALLOWLIST))
    restrict_db_paths: bool = True
    # PEP 578 audit hook sandbox (opt-in)
    audit_hooks_enabled: bool = False
    allowed_write_paths: list[str] = []
    allowed_network_hosts: list[str] = []
    block_private_ips: bool = True
    allow_subprocess: bool = False
    allow_eval_exec: bool = False
    sandbox_violation_action: Literal["raise", "log"] = "raise"


class AuditConfig(BaseModel):
    max_records: int = 100_000
    retention_days: int = 90


class ResourceConfig(BaseModel):
    memory: str = "512Mi"
    cpu: float = 0.5


class SecurityPolicy(BaseModel):
    content: ContentPolicy = ContentPolicy()
    server: ServerConfig = ServerConfig()
    rate_limit: RateLimitConfig = RateLimitConfig()
    resources: ResourceLimits = ResourceLimits()
    tools: ToolSandboxConfig = ToolSandboxConfig()
    audit: AuditConfig = AuditConfig()
