"""Security policy and resource configuration."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from initrunner.agent._subprocess import (
    DEFAULT_ENV_ALLOWLIST,
    DEFAULT_SENSITIVE_ENV_PREFIXES,
    DEFAULT_SENSITIVE_ENV_SUFFIXES,
)


def _regex_probe_worker(pats: list[str], conn: object) -> None:
    """Subprocess target: match each pattern against a probe string and signal completion."""
    import re as _re

    probe = "a" * 100 + "!"
    for pat in pats:
        _re.search(_re.compile(pat), probe)
        conn.send(True)  # type: ignore[union-attr]
    conn.close()  # type: ignore[union-attr]


def _probe_regexes_safe(patterns: list[str], timeout: float = 5.0) -> str | None:
    """Test *patterns* for catastrophic backtracking in a single subprocess.

    Returns ``None`` if every pattern is safe, or the first pattern that
    timed out.  Uses ``spawn`` context and a :class:`~multiprocessing.Pipe`
    so the subprocess signals after each pattern completes -- letting us
    identify the exact offender without paying spawn overhead per pattern.
    """
    if not patterns:
        return None

    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_regex_probe_worker, args=(patterns, child_conn))
    proc.start()
    child_conn.close()

    completed = 0
    while completed < len(patterns):
        # First poll covers process startup; subsequent ones are just regex time.
        t = timeout if completed == 0 else 2.0
        if parent_conn.poll(t):
            parent_conn.recv()
            completed += 1
        else:
            break

    proc.join(timeout=1)
    if proc.is_alive():
        proc.kill()
        proc.join()
    parent_conn.close()

    if completed < len(patterns):
        return patterns[completed]
    if proc.exitcode != 0:
        return patterns[-1]
    return None


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

        # Probe for catastrophic backtracking in a single subprocess
        # (threads don't work because re holds the GIL)
        failed = _probe_regexes_safe(v)
        if failed is not None:
            raise ValueError(
                f"Regex pattern '{failed}' is too complex (timed out on probe input)"
            )
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


_DOCKER_BLOCKED_ARGS = frozenset(
    {
        "--privileged",
        "--cap-add",
        "--security-opt",
        "--pid=host",
        "--userns=host",
        "--network=host",
        "--ipc=host",
    }
)


class BindMount(BaseModel):
    source: str
    target: str
    read_only: bool = True

    @field_validator("target")
    @classmethod
    def _absolute_target(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(f"bind mount target must be absolute, got '{v}'")
        return v


class DockerSandboxConfig(BaseModel):
    enabled: bool = False
    image: str = "python:3.12-slim"
    network: Literal["none", "bridge", "host"] = "none"
    memory_limit: str = "256m"
    cpu_limit: Annotated[float, Field(gt=0)] = 1.0
    read_only_rootfs: bool = True
    bind_mounts: list[BindMount] = Field(default_factory=list)
    env_passthrough: list[str] = Field(default_factory=list)
    extra_args: list[str] = Field(default_factory=list)

    @field_validator("image")
    @classmethod
    def _non_empty_image(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Docker image must not be empty")
        return v

    @field_validator("memory_limit")
    @classmethod
    def _valid_memory_format(cls, v: str) -> str:
        import re

        if not re.match(r"^\d+[bkmgBKMG]?$", v):
            raise ValueError(f"Invalid memory_limit '{v}' — use Docker format like '256m', '1g'")
        return v

    @field_validator("extra_args")
    @classmethod
    def _reject_dangerous_args(cls, v: list[str]) -> list[str]:
        for arg in v:
            normalized = arg.split("=")[0] if "=" in arg else arg
            if arg in _DOCKER_BLOCKED_ARGS or normalized in _DOCKER_BLOCKED_ARGS:
                raise ValueError(f"Docker extra_arg '{arg}' is blocked for security reasons")
        return v

    @model_validator(mode="after")
    def _no_conflicting_work_mount(self) -> DockerSandboxConfig:
        targets = [m.target for m in self.bind_mounts]
        if "/work" in targets:
            raise ValueError(
                "bind_mount target '/work' conflicts with automatic working directory mount"
            )
        if len(targets) != len(set(targets)):
            raise ValueError("duplicate bind_mount targets")
        return self


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
    docker: DockerSandboxConfig = DockerSandboxConfig()
    audit: AuditConfig = AuditConfig()
