"""Pydantic models representing the role.yaml format."""

from __future__ import annotations

import secrets
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from initrunner import __version__
from initrunner.agent._subprocess import (
    DEFAULT_ENV_ALLOWLIST,
    DEFAULT_SENSITIVE_ENV_PREFIXES,
    DEFAULT_SENSITIVE_ENV_SUFFIXES,
)
from initrunner.stores.base import StoreBackend

_USER_AGENT = f"initrunner/{__version__}"


class ApiVersion(StrEnum):
    V1 = "initrunner/v1"


class Kind(StrEnum):
    AGENT = "Agent"


class Metadata(BaseModel):
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")]
    description: str = ""
    tags: list[str] = []
    author: str = ""
    version: str = ""
    dependencies: list[str] = []


class ModelConfig(BaseModel):
    provider: str
    name: str
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.1
    max_tokens: Annotated[int, Field(ge=1, le=128000)] = 4096

    def to_model_string(self) -> str:
        return f"{self.provider}:{self.name}"

    def needs_custom_provider(self) -> bool:
        return self.provider == "ollama" or self.base_url is not None


class Guardrails(BaseModel):
    max_tokens_per_run: Annotated[int, Field(gt=0)] = 50000
    max_tool_calls: Annotated[int, Field(ge=0)] = 20
    timeout_seconds: Annotated[int, Field(gt=0)] = 300
    max_request_limit: Annotated[int, Field(gt=0)] | None = None

    # Per-run limits (mapped to PydanticAI UsageLimits)
    input_tokens_limit: Annotated[int, Field(gt=0)] | None = None
    total_tokens_limit: Annotated[int, Field(gt=0)] | None = None

    # Cumulative budgets
    session_token_budget: Annotated[int, Field(gt=0)] | None = None
    daemon_token_budget: Annotated[int, Field(gt=0)] | None = None
    daemon_daily_token_budget: Annotated[int, Field(gt=0)] | None = None

    # Autonomous mode limits
    max_iterations: Annotated[int, Field(gt=0)] = 10
    autonomous_token_budget: Annotated[int, Field(gt=0)] | None = None
    autonomous_timeout_seconds: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def _derive_request_limit(self) -> Guardrails:
        if self.max_request_limit is None:
            self.max_request_limit = max(self.max_tool_calls + 10, 30)
        return self


# --- Tool configs (discriminated union) ---


class ToolConfigBase(BaseModel):
    """Base class for all tool configurations."""

    type: str

    def summary(self) -> str:
        return self.type


class FileSystemToolConfig(ToolConfigBase):
    type: Literal["filesystem"] = "filesystem"
    root_path: str = "."
    allowed_extensions: list[str] = []
    read_only: bool = True

    def summary(self) -> str:
        return f"filesystem: {self.root_path} (ro={self.read_only})"


class HttpToolConfig(ToolConfigBase):
    type: Literal["http"] = "http"
    base_url: str
    allowed_methods: list[str] = ["GET"]
    headers: dict[str, str] = {}

    def summary(self) -> str:
        return f"http: {self.base_url}"


class McpToolConfig(ToolConfigBase):
    type: Literal["mcp"] = "mcp"
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    command: str | None = None
    args: list[str] = []
    url: str | None = None
    tool_filter: list[str] = []
    tool_exclude: list[str] = []
    headers: dict[str, str] = {}
    env: dict[str, str] = {}
    cwd: str | None = None
    tool_prefix: str | None = None
    max_retries: int = 1
    timeout: int | None = None

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> McpToolConfig:
        if self.transport == "stdio" and not self.command:
            raise ValueError("MCP stdio transport requires 'command'")
        if self.transport in ("sse", "streamable-http") and not self.url:
            raise ValueError(f"MCP {self.transport} transport requires 'url'")
        if self.tool_filter and self.tool_exclude:
            raise ValueError("'tool_filter' and 'tool_exclude' are mutually exclusive")
        return self

    def summary(self) -> str:
        return f"mcp: {self.transport} {self.command or self.url or ''}"


class CustomToolConfig(ToolConfigBase):
    type: Literal["custom"] = "custom"
    module: str
    function: str | None = None  # None → auto-discover all public callables
    config: dict[str, Any] = {}  # injected into functions that accept tool_config param

    def summary(self) -> str:
        if self.function:
            return f"custom: {self.module}.{self.function}"
        return f"custom: {self.module} (toolset)"


class DelegateAgentRef(BaseModel):
    name: str
    role_file: str | None = None
    url: str | None = None
    description: str = ""
    headers_env: dict[str, str] = {}


class DelegateSharedMemory(BaseModel):
    """Shared memory config for delegate sub-agents."""

    store_path: str
    max_memories: int = 1000


class DelegateToolConfig(ToolConfigBase):
    type: Literal["delegate"] = "delegate"
    agents: list[DelegateAgentRef]
    mode: Literal["inline", "mcp"] = "inline"
    max_depth: int = 3
    timeout_seconds: int = 120
    shared_memory: DelegateSharedMemory | None = None

    @model_validator(mode="after")
    def _validate_agents(self) -> DelegateToolConfig:
        for agent in self.agents:
            if self.mode == "inline" and not agent.role_file:
                raise ValueError(f"Inline mode requires 'role_file' on agent '{agent.name}'")
            if self.mode == "mcp" and not agent.url:
                raise ValueError(f"MCP mode requires 'url' on agent '{agent.name}'")
        return self

    def summary(self) -> str:
        names = ", ".join(a.name for a in self.agents)
        return f"delegate ({self.mode}): {names}"


class ApiParameter(BaseModel):
    name: str  # must be valid Python identifier
    type: Literal["string", "integer", "number", "boolean"]  # JSON Schema types
    required: bool = False
    default: Any = None
    description: str = ""

    @field_validator("name")
    @classmethod
    def _valid_identifier(cls, v: str) -> str:
        if not v.isidentifier():
            raise ValueError(f"'{v}' is not a valid Python identifier")
        return v


class ApiEndpoint(BaseModel):
    name: str  # becomes the tool function name
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    path: str  # supports {param} placeholders
    description: str = ""
    parameters: list[ApiParameter] = []
    headers: dict[str, str] = {}
    body_template: dict[str, Any] | None = None
    query_params: dict[str, str] = {}
    response_extract: str | None = None  # "$.data.id" or None for full text
    timeout: int = 30


class ApiToolConfig(ToolConfigBase):
    type: Literal["api"] = "api"
    name: str
    description: str = ""
    base_url: str
    headers: dict[str, str] = {}
    auth: dict[str, str] = {}
    endpoints: list[ApiEndpoint]

    def summary(self) -> str:
        return f"api: {self.name} ({len(self.endpoints)} endpoints)"


class WebReaderToolConfig(ToolConfigBase):
    type: Literal["web_reader"] = "web_reader"
    allowed_domains: list[str] = []
    blocked_domains: list[str] = []
    max_content_bytes: int = 512_000
    timeout_seconds: int = 15
    user_agent: str = _USER_AGENT

    def summary(self) -> str:
        if self.allowed_domains:
            return f"web_reader: {', '.join(self.allowed_domains[:3])}"
        return "web_reader"


class PythonToolConfig(ToolConfigBase):
    type: Literal["python"] = "python"
    timeout_seconds: int = 30
    max_output_bytes: int = 102_400
    working_dir: str | None = None
    require_confirmation: bool = True
    network_disabled: bool = True

    def summary(self) -> str:
        confirm = ", confirm" if self.require_confirmation else ""
        net = ", no-network" if self.network_disabled else ""
        return f"python: timeout={self.timeout_seconds}s{confirm}{net}"


class DateTimeToolConfig(ToolConfigBase):
    type: Literal["datetime"] = "datetime"
    default_timezone: str = "UTC"

    def summary(self) -> str:
        return f"datetime: {self.default_timezone}"


class SqlToolConfig(ToolConfigBase):
    type: Literal["sql"] = "sql"
    database: str
    read_only: bool = True
    max_rows: int = 100
    max_result_bytes: int = 102_400
    timeout_seconds: int = 10

    def summary(self) -> str:
        return f"sql: {self.database} (ro={self.read_only})"


class GitToolConfig(ToolConfigBase):
    type: Literal["git"] = "git"
    repo_path: str = "."
    read_only: bool = True
    timeout_seconds: int = 30
    max_output_bytes: int = 102_400

    def summary(self) -> str:
        return f"git: {self.repo_path} (ro={self.read_only})"


class ShellToolConfig(ToolConfigBase):
    type: Literal["shell"] = "shell"
    allowed_commands: list[str] = []
    blocked_commands: list[str] = Field(
        default_factory=lambda: [
            "rm",
            "mkfs",
            "dd",
            "fdisk",
            "parted",
            "mount",
            "umount",
            "shutdown",
            "reboot",
            "halt",
            "poweroff",
            "chmod",
            "chown",
            "passwd",
            "useradd",
            "userdel",
            "sudo",
            "su",
        ]
    )
    working_dir: str | None = None
    timeout_seconds: int = 30
    max_output_bytes: int = 102_400
    require_confirmation: bool = True

    def summary(self) -> str:
        confirm = ", confirm" if self.require_confirmation else ""
        return f"shell: timeout={self.timeout_seconds}s{confirm}"


class SlackToolConfig(ToolConfigBase):
    type: Literal["slack"] = "slack"
    webhook_url: str
    default_channel: str | None = None
    username: str | None = None
    icon_emoji: str | None = None
    timeout_seconds: int = 30
    max_response_bytes: int = 1024

    def summary(self) -> str:
        return "slack: webhook"


class EmailToolConfig(ToolConfigBase):
    type: Literal["email"] = "email"
    imap_host: str
    smtp_host: str = ""
    imap_port: int = 993
    smtp_port: int = 587
    username: str
    password: str
    use_ssl: bool = True
    default_folder: str = "INBOX"
    read_only: bool = True
    max_results: int = 20
    max_body_chars: int = 50_000
    timeout_seconds: int = 30

    @model_validator(mode="after")
    def _validate_smtp_for_write(self) -> EmailToolConfig:
        if not self.read_only and not self.smtp_host:
            raise ValueError("smtp_host is required when read_only is false")
        return self

    def summary(self) -> str:
        return f"email: {self.imap_host} (ro={self.read_only})"


class WebScraperToolConfig(ToolConfigBase):
    type: Literal["web_scraper"] = "web_scraper"
    allowed_domains: list[str] = []
    blocked_domains: list[str] = []
    max_content_bytes: int = 512_000
    timeout_seconds: int = 15
    user_agent: str = _USER_AGENT

    def summary(self) -> str:
        if self.allowed_domains:
            return f"web_scraper: {', '.join(self.allowed_domains[:3])}"
        return "web_scraper"


class SearchToolConfig(ToolConfigBase):
    type: Literal["search"] = "search"
    provider: Literal["duckduckgo", "serpapi", "brave", "tavily"] = "duckduckgo"
    api_key: str = ""
    max_results: int = 10
    safe_search: bool = True
    timeout_seconds: int = 15

    @model_validator(mode="after")
    def _validate_api_key_for_paid(self) -> SearchToolConfig:
        if self.provider != "duckduckgo" and not self.api_key:
            raise ValueError(f"provider '{self.provider}' requires 'api_key'")
        return self

    def summary(self) -> str:
        return f"search: {self.provider}"


class PluginToolConfig(ToolConfigBase):
    type: str
    config: dict[str, Any] = {}

    def summary(self) -> str:
        return f"plugin: {self.type}"


ToolConfig = ToolConfigBase

# --- Trigger configs (discriminated union) ---


class CronTriggerConfig(BaseModel):
    type: Literal["cron"] = "cron"
    schedule: str
    prompt: str
    timezone: str = "UTC"
    autonomous: bool = False

    def summary(self) -> str:
        return f"cron: {self.schedule}"


class FileWatchTriggerConfig(BaseModel):
    type: Literal["file_watch"] = "file_watch"
    paths: list[str]
    extensions: list[str] = []
    prompt_template: str = "File changed: {path}"
    debounce_seconds: float = 1.0
    process_existing: bool = False
    autonomous: bool = False

    def summary(self) -> str:
        return f"file_watch: {', '.join(self.paths)}"


class WebhookTriggerConfig(BaseModel):
    type: Literal["webhook"] = "webhook"
    path: str = "/webhook"
    port: int = 8080
    method: str = "POST"
    secret: str | None = None
    rate_limit_rpm: int = 60
    autonomous: bool = False

    @model_validator(mode="after")
    def _auto_generate_secret(self) -> WebhookTriggerConfig:
        if self.secret is None:
            self.secret = secrets.token_urlsafe(32)
        return self

    def summary(self) -> str:
        return f"webhook: :{self.port}{self.path}"


TriggerConfig = Annotated[
    CronTriggerConfig | FileWatchTriggerConfig | WebhookTriggerConfig,
    Field(discriminator="type"),
]

# --- Sink configs (discriminated union) ---


class WebhookSinkConfig(BaseModel):
    type: Literal["webhook"] = "webhook"
    url: str
    method: str = "POST"
    headers: dict[str, str] = {}
    timeout_seconds: int = 30
    retry_count: int = 0

    def summary(self) -> str:
        return f"webhook: {self.url}"


class FileSinkConfig(BaseModel):
    type: Literal["file"] = "file"
    path: str
    format: Literal["json", "text"] = "json"

    def summary(self) -> str:
        return f"file: {self.path} ({self.format})"


class CustomSinkConfig(BaseModel):
    type: Literal["custom"] = "custom"
    module: str
    function: str

    def summary(self) -> str:
        return f"custom: {self.module}.{self.function}"


SinkConfig = Annotated[
    WebhookSinkConfig | FileSinkConfig | CustomSinkConfig,
    Field(discriminator="type"),
]

# --- Ingestion config ---


class ChunkingConfig(BaseModel):
    strategy: Literal["fixed", "paragraph"] = "fixed"
    chunk_size: int = 512
    chunk_overlap: int = 50

    @model_validator(mode="after")
    def _validate_overlap(self) -> ChunkingConfig:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be less than "
                f"chunk_size ({self.chunk_size})"
            )
        return self


class EmbeddingConfig(BaseModel):
    provider: str = ""  # empty = derive from spec.model.provider
    model: str = ""  # empty = provider default (e.g. text-embedding-3-small)
    base_url: str = ""  # empty = provider default; set for custom endpoints
    api_key_env: str = ""  # env var name for API key; empty = provider default


class IngestConfig(BaseModel):
    sources: list[str]
    watch: bool = False
    chunking: ChunkingConfig = ChunkingConfig()
    embeddings: EmbeddingConfig = EmbeddingConfig()
    store_backend: StoreBackend = StoreBackend.SQLITE_VEC
    store_path: str | None = None  # default: ~/.initrunner/stores/{agent-name}.db


# --- Memory config ---


class MemoryConfig(BaseModel):
    store_path: str | None = None  # default: ~/.initrunner/memory/{agent-name}.db
    store_backend: StoreBackend = StoreBackend.SQLITE_VEC
    max_sessions: int = 10
    max_memories: int = 1000
    max_resume_messages: int = 20  # limit history loaded on --resume
    embeddings: EmbeddingConfig = EmbeddingConfig()


# --- Resource config ---


class ResourceConfig(BaseModel):
    memory: str = "512Mi"
    cpu: float = 0.5


# --- Security policy ---


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


class SecurityPolicy(BaseModel):
    content: ContentPolicy = ContentPolicy()
    server: ServerConfig = ServerConfig()
    rate_limit: RateLimitConfig = RateLimitConfig()
    resources: ResourceLimits = ResourceLimits()
    tools: ToolSandboxConfig = ToolSandboxConfig()
    audit: AuditConfig = AuditConfig()


# --- Autonomy config ---


class AutonomyConfig(BaseModel):
    """Configuration for autonomous agent execution."""

    continuation_prompt: str = (
        "Continue working on the task. Review your progress so far and "
        "decide your next step. If you have completed the task, call the "
        "finish_task tool with a summary."
    )
    max_history_messages: int = 40
    max_plan_steps: int = 20
    iteration_delay_seconds: float = 0
    max_scheduled_per_run: int = 3
    max_scheduled_total: int = 50
    max_schedule_delay_seconds: int = 86400  # 24h


# --- Agent spec & role definition ---


def parse_tool_list(v: Any) -> list:
    """Parse a list of tool config dicts into typed ToolConfig instances.

    Shared by AgentSpec and SkillFrontmatter validators.
    """
    if not isinstance(v, list):
        return v

    # Lazy import inside function body to avoid circular import with _registry
    from initrunner.agent.tools._registry import get_tool_types

    builtin_types = get_tool_types()
    result = []
    for item in v:
        if not isinstance(item, dict):
            result.append(item)
            continue
        tool_type = item.get("type")
        if tool_type in builtin_types:
            try:
                result.append(builtin_types[tool_type].model_validate(item))
            except ValidationError as exc:
                raise ValueError(f"Invalid config for tool '{tool_type}': {exc}") from exc
        else:
            config = {k: val for k, val in item.items() if k != "type"}
            result.append(PluginToolConfig(type=tool_type, config=config))
    return result


class AgentSpec(BaseModel):
    role: str
    model: ModelConfig
    tools: list[ToolConfig] = []
    skills: list[str] = []
    triggers: list[TriggerConfig] = []
    sinks: list[SinkConfig] = []
    ingest: IngestConfig | None = None
    memory: MemoryConfig | None = None
    autonomy: AutonomyConfig | None = None
    guardrails: Guardrails = Guardrails()
    resources: ResourceConfig = ResourceConfig()
    security: SecurityPolicy = SecurityPolicy()

    @field_validator("tools", mode="before")
    @classmethod
    def _parse_tools(cls, v: Any) -> list:
        return parse_tool_list(v)


class RequiresConfig(BaseModel):
    """External dependencies a skill needs (validated at load time)."""

    env: list[str] = []
    bins: list[str] = []


class SkillFrontmatter(BaseModel):
    """Parsed from YAML frontmatter in SKILL.md files.

    Standard agentskills.io fields: name, description, license, compatibility,
    metadata, allowed_tools. InitRunner extensions: tools, requires.
    """

    # agentskills.io standard fields
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")]
    description: str
    license: str = ""
    compatibility: str = ""
    metadata: dict[str, str] = {}
    allowed_tools: str = ""

    # InitRunner extensions
    tools: list[ToolConfig] = []
    requires: RequiresConfig = RequiresConfig()

    model_config = ConfigDict(extra="ignore")

    @field_validator("tools", mode="before")
    @classmethod
    def _parse_tools(cls, v: Any) -> list:
        return parse_tool_list(v)


class SkillDefinition(BaseModel):
    """Internal representation of a loaded skill (frontmatter + body)."""

    frontmatter: SkillFrontmatter
    prompt: str


class RoleDefinition(BaseModel):
    apiVersion: ApiVersion
    kind: Kind
    metadata: Metadata
    spec: AgentSpec
