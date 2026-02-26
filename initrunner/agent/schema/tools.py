"""Tool configuration models (discriminated union)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from initrunner.agent.schema.base import _USER_AGENT


class ToolPermissions(BaseModel):
    """Declarative allow/deny permission rules for tool arguments.

    Pattern format: ``arg_name=glob_pattern`` — *arg_name* matches a tool
    function parameter, *glob_pattern* uses :func:`fnmatch.fnmatch` syntax.
    A bare pattern (no ``=``) matches against all string argument values.

    Evaluation order: deny rules first (deny wins) → allow rules → default.
    """

    default: Literal["allow", "deny"] = "allow"
    allow: list[str] = []
    deny: list[str] = []

    @field_validator("allow", "deny")
    @classmethod
    def _validate_patterns(cls, v: list[str]) -> list[str]:
        for pattern in v:
            if "=" in pattern:
                arg_name, _, glob = pattern.partition("=")
                if not arg_name:
                    raise ValueError(f"empty argument name in pattern: {pattern!r}")
                if not glob:
                    raise ValueError(f"empty glob in pattern: {pattern!r}")
        return v


class ToolConfigBase(BaseModel):
    """Base class for all tool configurations."""

    type: str
    permissions: ToolPermissions | None = None

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


class AudioToolConfig(ToolConfigBase):
    type: Literal["audio"] = "audio"
    youtube_languages: list[str] = ["en"]
    include_timestamps: bool = False
    transcription_model: str | None = None
    max_audio_mb: float = 20.0
    max_transcript_chars: int = 50_000

    def summary(self) -> str:
        return "audio"


class CsvAnalysisToolConfig(ToolConfigBase):
    type: Literal["csv_analysis"] = "csv_analysis"
    root_path: str = "."
    max_rows: int = 1000
    max_file_size_mb: float = 10.0
    delimiter: str = ","

    def summary(self) -> str:
        return f"csv_analysis: {self.root_path}"


class PluginToolConfig(ToolConfigBase):
    type: str
    config: dict[str, Any] = {}

    def summary(self) -> str:
        return f"plugin: {self.type}"


ToolConfig = ToolConfigBase
