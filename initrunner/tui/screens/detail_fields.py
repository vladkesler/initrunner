"""Field-spec builders and type conversion for role detail editing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from initrunner.agent.schema import RoleDefinition


class FieldKind(StrEnum):
    STR = "str"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    CSV = "csv"


@dataclass
class FieldSpec:
    label: str
    key: str
    value: str
    kind: FieldKind = FieldKind.STR
    placeholder: str = ""


# ── Field-spec builders ──────────────────────────────────────


def model_fields(role: RoleDefinition) -> list[FieldSpec]:
    m = role.spec.model
    return [
        FieldSpec("Provider", "provider", m.provider),
        FieldSpec("Name", "name", m.name),
        FieldSpec("Temperature", "temperature", str(m.temperature), FieldKind.FLOAT),
        FieldSpec("Max Tokens", "max_tokens", str(m.max_tokens), FieldKind.INT),
        FieldSpec("Base URL", "base_url", m.base_url or "", placeholder="optional"),
    ]


def guardrails_fields(role: RoleDefinition) -> list[FieldSpec]:
    g = role.spec.guardrails
    fields = [
        FieldSpec(
            "Max Tokens Per Run", "max_tokens_per_run", str(g.max_tokens_per_run), FieldKind.INT
        ),
        FieldSpec("Timeout (seconds)", "timeout_seconds", str(g.timeout_seconds), FieldKind.INT),
        FieldSpec("Max Tool Calls", "max_tool_calls", str(g.max_tool_calls), FieldKind.INT),
        FieldSpec(
            "Max Request Limit", "max_request_limit", str(g.max_request_limit), FieldKind.INT
        ),
        FieldSpec(
            "Input Tokens Limit",
            "input_tokens_limit",
            str(g.input_tokens_limit) if g.input_tokens_limit is not None else "unlimited",
            FieldKind.INT,
        ),
        FieldSpec(
            "Total Tokens Limit",
            "total_tokens_limit",
            str(g.total_tokens_limit) if g.total_tokens_limit is not None else "unlimited",
            FieldKind.INT,
        ),
        FieldSpec(
            "Session Token Budget",
            "session_token_budget",
            str(g.session_token_budget) if g.session_token_budget is not None else "unlimited",
            FieldKind.INT,
        ),
        FieldSpec(
            "Daemon Token Budget",
            "daemon_token_budget",
            str(g.daemon_token_budget) if g.daemon_token_budget is not None else "unlimited",
            FieldKind.INT,
        ),
        FieldSpec(
            "Daemon Daily Budget",
            "daemon_daily_token_budget",
            (
                str(g.daemon_daily_token_budget)
                if g.daemon_daily_token_budget is not None
                else "unlimited"
            ),
            FieldKind.INT,
        ),
    ]
    return fields


def tool_fields(tool: Any) -> list[FieldSpec]:
    from initrunner.agent.schema import (
        ApiToolConfig,
        CustomToolConfig,
        DateTimeToolConfig,
        DelegateToolConfig,
        FileSystemToolConfig,
        GitToolConfig,
        HttpToolConfig,
        McpToolConfig,
        PythonToolConfig,
        SqlToolConfig,
        WebReaderToolConfig,
    )

    fields: list[FieldSpec] = []
    if isinstance(tool, FileSystemToolConfig):
        fields.append(FieldSpec("Root Path", "root_path", tool.root_path))
        fields.append(
            FieldSpec(
                "Extensions",
                "allowed_extensions",
                ", ".join(tool.allowed_extensions),
                FieldKind.CSV,
            )
        )
        fields.append(
            FieldSpec("Read Only", "read_only", str(tool.read_only).lower(), FieldKind.BOOL)
        )
    elif isinstance(tool, HttpToolConfig):
        fields.append(FieldSpec("Base URL", "base_url", tool.base_url))
        fields.append(
            FieldSpec("Methods", "allowed_methods", ", ".join(tool.allowed_methods), FieldKind.CSV)
        )
    elif isinstance(tool, McpToolConfig):
        fields.append(FieldSpec("Transport", "transport", tool.transport))
        fields.append(FieldSpec("Command", "command", tool.command or "", placeholder="optional"))
        fields.append(FieldSpec("URL", "url", tool.url or "", placeholder="optional"))
        fields.append(FieldSpec("Args", "args", ", ".join(tool.args), FieldKind.CSV))
        fields.append(
            FieldSpec("Tool Filter", "tool_filter", ", ".join(tool.tool_filter), FieldKind.CSV)
        )
    elif isinstance(tool, CustomToolConfig):
        fields.append(FieldSpec("Module", "module", tool.module))
        fields.append(FieldSpec("Function", "function", tool.function))
    elif isinstance(tool, DelegateToolConfig):
        fields.append(FieldSpec("Mode", "mode", tool.mode))
        fields.append(FieldSpec("Max Depth", "max_depth", str(tool.max_depth), FieldKind.INT))
        fields.append(
            FieldSpec(
                "Timeout (seconds)", "timeout_seconds", str(tool.timeout_seconds), FieldKind.INT
            )
        )
    elif isinstance(tool, WebReaderToolConfig):
        fields.append(
            FieldSpec(
                "Allowed Domains", "allowed_domains", ", ".join(tool.allowed_domains), FieldKind.CSV
            )
        )
        fields.append(
            FieldSpec(
                "Blocked Domains", "blocked_domains", ", ".join(tool.blocked_domains), FieldKind.CSV
            )
        )
        fields.append(
            FieldSpec(
                "Max Content Bytes", "max_content_bytes", str(tool.max_content_bytes), FieldKind.INT
            )
        )
        fields.append(
            FieldSpec(
                "Timeout (seconds)", "timeout_seconds", str(tool.timeout_seconds), FieldKind.INT
            )
        )
        fields.append(FieldSpec("User Agent", "user_agent", tool.user_agent))
    elif isinstance(tool, PythonToolConfig):
        fields.append(
            FieldSpec(
                "Timeout (seconds)", "timeout_seconds", str(tool.timeout_seconds), FieldKind.INT
            )
        )
        fields.append(
            FieldSpec(
                "Max Output Bytes", "max_output_bytes", str(tool.max_output_bytes), FieldKind.INT
            )
        )
        fields.append(
            FieldSpec("Working Dir", "working_dir", tool.working_dir or "", placeholder="optional")
        )
        fields.append(
            FieldSpec(
                "Require Confirmation",
                "require_confirmation",
                str(tool.require_confirmation).lower(),
                FieldKind.BOOL,
            )
        )
    elif isinstance(tool, DateTimeToolConfig):
        fields.append(FieldSpec("Default Timezone", "default_timezone", tool.default_timezone))
    elif isinstance(tool, SqlToolConfig):
        fields.append(FieldSpec("Database", "database", tool.database))
        fields.append(
            FieldSpec("Read Only", "read_only", str(tool.read_only).lower(), FieldKind.BOOL)
        )
        fields.append(FieldSpec("Max Rows", "max_rows", str(tool.max_rows), FieldKind.INT))
        fields.append(
            FieldSpec(
                "Max Result Bytes", "max_result_bytes", str(tool.max_result_bytes), FieldKind.INT
            )
        )
        fields.append(
            FieldSpec(
                "Timeout (seconds)", "timeout_seconds", str(tool.timeout_seconds), FieldKind.INT
            )
        )
    elif isinstance(tool, GitToolConfig):
        fields.append(FieldSpec("Repo Path", "repo_path", tool.repo_path))
        fields.append(
            FieldSpec("Read Only", "read_only", str(tool.read_only).lower(), FieldKind.BOOL)
        )
        fields.append(
            FieldSpec(
                "Timeout (seconds)", "timeout_seconds", str(tool.timeout_seconds), FieldKind.INT
            )
        )
        fields.append(
            FieldSpec(
                "Max Output Bytes", "max_output_bytes", str(tool.max_output_bytes), FieldKind.INT
            )
        )
    elif isinstance(tool, ApiToolConfig):
        fields.append(FieldSpec("Name", "name", tool.name))
        fields.append(FieldSpec("Description", "description", tool.description))
        fields.append(FieldSpec("Base URL", "base_url", tool.base_url))
    return fields


def trigger_fields(trigger: Any) -> list[FieldSpec]:
    from initrunner.agent.schema import (
        CronTriggerConfig,
        FileWatchTriggerConfig,
        WebhookTriggerConfig,
    )

    fields: list[FieldSpec] = []
    if isinstance(trigger, CronTriggerConfig):
        fields.append(FieldSpec("Schedule", "schedule", trigger.schedule))
        fields.append(FieldSpec("Prompt", "prompt", trigger.prompt))
        fields.append(FieldSpec("Timezone", "timezone", trigger.timezone))
    elif isinstance(trigger, FileWatchTriggerConfig):
        fields.append(FieldSpec("Paths", "paths", ", ".join(trigger.paths), FieldKind.CSV))
        fields.append(
            FieldSpec("Extensions", "extensions", ", ".join(trigger.extensions), FieldKind.CSV)
        )
        fields.append(FieldSpec("Prompt Template", "prompt_template", trigger.prompt_template))
        fields.append(
            FieldSpec(
                "Debounce (seconds)",
                "debounce_seconds",
                str(trigger.debounce_seconds),
                FieldKind.FLOAT,
            )
        )
    elif isinstance(trigger, WebhookTriggerConfig):
        fields.append(FieldSpec("Path", "path", trigger.path))
        fields.append(FieldSpec("Port", "port", str(trigger.port), FieldKind.INT))
        fields.append(FieldSpec("Method", "method", trigger.method))
        fields.append(FieldSpec("Secret", "secret", trigger.secret or "", placeholder="optional"))
        fields.append(
            FieldSpec(
                "Rate Limit (rpm)", "rate_limit_rpm", str(trigger.rate_limit_rpm), FieldKind.INT
            )
        )
    return fields


def sink_fields(sink: Any) -> list[FieldSpec]:
    from initrunner.agent.schema import (
        CustomSinkConfig,
        FileSinkConfig,
        WebhookSinkConfig,
    )

    fields: list[FieldSpec] = []
    if isinstance(sink, WebhookSinkConfig):
        fields.append(FieldSpec("URL", "url", sink.url))
        fields.append(FieldSpec("Method", "method", sink.method))
        fields.append(
            FieldSpec(
                "Timeout (seconds)", "timeout_seconds", str(sink.timeout_seconds), FieldKind.INT
            )
        )
        fields.append(FieldSpec("Retry Count", "retry_count", str(sink.retry_count), FieldKind.INT))
    elif isinstance(sink, FileSinkConfig):
        fields.append(FieldSpec("Path", "path", sink.path))
        fields.append(FieldSpec("Format", "format", sink.format))
    elif isinstance(sink, CustomSinkConfig):
        fields.append(FieldSpec("Module", "module", sink.module))
        fields.append(FieldSpec("Function", "function", sink.function))
    return fields


def ingest_fields(role: RoleDefinition) -> list[FieldSpec]:
    ingest = role.spec.ingest
    assert ingest is not None
    ch = ingest.chunking
    return [
        FieldSpec("Sources", "sources", ", ".join(ingest.sources), FieldKind.CSV),
        FieldSpec("Strategy", "chunking.strategy", ch.strategy),
        FieldSpec("Chunk Size", "chunking.chunk_size", str(ch.chunk_size), FieldKind.INT),
        FieldSpec("Chunk Overlap", "chunking.chunk_overlap", str(ch.chunk_overlap), FieldKind.INT),
        FieldSpec("Store Backend", "store_backend", ingest.store_backend.value),
    ]


def memory_fields(role: RoleDefinition) -> list[FieldSpec]:
    mem = role.spec.memory
    assert mem is not None
    return [
        FieldSpec("Max Sessions", "max_sessions", str(mem.max_sessions), FieldKind.INT),
        FieldSpec("Max Memories", "max_memories", str(mem.max_memories), FieldKind.INT),
        FieldSpec(
            "Max Resume Messages",
            "max_resume_messages",
            str(mem.max_resume_messages),
            FieldKind.INT,
        ),
        FieldSpec("Store Backend", "store_backend", mem.store_backend.value),
    ]


# ── Type conversion ──────────────────────────────────────────


def convert_field(value: str, kind: FieldKind) -> object:
    if kind == FieldKind.STR:
        return value
    if kind == FieldKind.INT:
        return int(value)
    if kind == FieldKind.FLOAT:
        return float(value)
    if kind == FieldKind.BOOL:
        return value.lower() in ("true", "1", "yes")
    if kind == FieldKind.CSV:
        return [s.strip() for s in value.split(",") if s.strip()]
    return value


def convert_values(values: dict[str, str], specs: list[FieldSpec]) -> dict[str, object]:
    spec_map = {s.key: s for s in specs}
    result: dict[str, object] = {}
    for key, raw in values.items():
        spec = spec_map.get(key)
        if spec is None:
            result[key] = raw
            continue
        result[key] = convert_field(raw, spec.kind)
    return result
