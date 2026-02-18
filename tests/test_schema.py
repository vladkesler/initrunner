"""Tests for the role definition schema."""

import pytest
from pydantic import ValidationError

from initrunner import __version__
from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
from initrunner.agent.schema.guardrails import Guardrails
from initrunner.agent.schema.ingestion import ChunkingConfig, EmbeddingConfig, IngestConfig
from initrunner.agent.schema.output import OutputConfig
from initrunner.agent.schema.role import RoleDefinition, parse_tool_list
from initrunner.agent.schema.sinks import CustomSinkConfig, FileSinkConfig, WebhookSinkConfig
from initrunner.agent.schema.tools import (
    CustomToolConfig,
    DateTimeToolConfig,
    DelegateAgentRef,
    DelegateToolConfig,
    FileSystemToolConfig,
    GitToolConfig,
    HttpToolConfig,
    McpToolConfig,
    PythonToolConfig,
    SqlToolConfig,
    WebReaderToolConfig,
)
from initrunner.agent.schema.triggers import (
    CronTriggerConfig,
    FileWatchTriggerConfig,
    WebhookTriggerConfig,
)


def _minimal_role_data() -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent", "description": "A test agent"},
        "spec": {
            "role": "You are a test agent.",
            "model": {"provider": "anthropic", "name": "claude-sonnet-4-5-20250929"},
        },
    }


class TestRoleDefinition:
    def test_valid_minimal(self):
        role = RoleDefinition.model_validate(_minimal_role_data())
        assert role.apiVersion == ApiVersion.V1
        assert role.kind == Kind.AGENT
        assert role.metadata.name == "test-agent"
        assert role.spec.role == "You are a test agent."

    def test_observability_none_by_default(self):
        role = RoleDefinition.model_validate(_minimal_role_data())
        assert role.spec.observability is None

    def test_observability_parses(self):
        data = _minimal_role_data()
        data["spec"]["observability"] = {
            "backend": "console",
            "service_name": "my-svc",
            "sample_rate": 0.5,
        }
        role = RoleDefinition.model_validate(data)
        assert role.spec.observability is not None
        assert role.spec.observability.backend == "console"
        assert role.spec.observability.service_name == "my-svc"
        assert role.spec.observability.sample_rate == 0.5

    def test_invalid_api_version(self):
        data = _minimal_role_data()
        data["apiVersion"] = "wrong/v99"
        with pytest.raises(ValidationError):
            RoleDefinition.model_validate(data)

    def test_invalid_kind(self):
        data = _minimal_role_data()
        data["kind"] = "Service"
        with pytest.raises(ValidationError):
            RoleDefinition.model_validate(data)


class TestMetadata:
    def test_valid_name(self):
        m = Metadata(name="my-agent", description="test")
        assert m.name == "my-agent"

    def test_name_with_numbers(self):
        m = Metadata(name="agent-v2")
        assert m.name == "agent-v2"

    def test_invalid_name_uppercase(self):
        with pytest.raises(ValidationError):
            Metadata(name="MyAgent")

    def test_invalid_name_starts_with_dash(self):
        with pytest.raises(ValidationError):
            Metadata(name="-agent")

    def test_invalid_name_ends_with_dash(self):
        with pytest.raises(ValidationError):
            Metadata(name="agent-")

    def test_default_tags_empty(self):
        m = Metadata(name="ab")
        assert m.tags == []


class TestModelConfig:
    def test_to_model_string(self):
        mc = ModelConfig(provider="anthropic", name="claude-sonnet-4-5-20250929")
        assert mc.to_model_string() == "anthropic:claude-sonnet-4-5-20250929"

    def test_default_temperature(self):
        mc = ModelConfig(provider="openai", name="gpt-4o")
        assert mc.temperature == 0.1

    def test_default_max_tokens(self):
        mc = ModelConfig(provider="openai", name="gpt-4o")
        assert mc.max_tokens == 4096

    def test_temperature_bounds_low(self):
        with pytest.raises(ValidationError):
            ModelConfig(provider="x", name="y", temperature=-0.1)

    def test_temperature_bounds_high(self):
        with pytest.raises(ValidationError):
            ModelConfig(provider="x", name="y", temperature=2.1)

    def test_max_tokens_too_low(self):
        with pytest.raises(ValidationError):
            ModelConfig(provider="x", name="y", max_tokens=0)

    def test_max_tokens_too_high(self):
        with pytest.raises(ValidationError):
            ModelConfig(provider="x", name="y", max_tokens=200000)

    def test_base_url_default_none(self):
        mc = ModelConfig(provider="openai", name="gpt-4o")
        assert mc.base_url is None

    def test_base_url_explicit(self):
        mc = ModelConfig(provider="openai", name="my-model", base_url="http://my-server:8000/v1")
        assert mc.base_url == "http://my-server:8000/v1"

    def test_needs_custom_provider_ollama(self):
        mc = ModelConfig(provider="ollama", name="llama3.2")
        assert mc.needs_custom_provider() is True

    def test_needs_custom_provider_base_url(self):
        mc = ModelConfig(provider="openai", name="my-model", base_url="http://my-server:8000/v1")
        assert mc.needs_custom_provider() is True

    def test_needs_custom_provider_standard(self):
        mc = ModelConfig(provider="openai", name="gpt-4o")
        assert mc.needs_custom_provider() is False

    def test_needs_custom_provider_anthropic(self):
        mc = ModelConfig(provider="anthropic", name="claude-sonnet-4-5-20250929")
        assert mc.needs_custom_provider() is False

    def test_is_reasoning_model_o3_mini(self):
        mc = ModelConfig(provider="openai", name="o3-mini")
        assert mc.is_reasoning_model() is True

    def test_is_reasoning_model_o1_preview(self):
        mc = ModelConfig(provider="openai", name="o1-preview")
        assert mc.is_reasoning_model() is True

    def test_is_reasoning_model_o4_mini(self):
        mc = ModelConfig(provider="openai", name="o4-mini")
        assert mc.is_reasoning_model() is True

    def test_is_reasoning_model_case_insensitive(self):
        mc = ModelConfig(provider="OpenAI", name="O3-Mini")
        assert mc.is_reasoning_model() is True

    def test_is_reasoning_model_o2(self):
        mc = ModelConfig(provider="openai", name="o2")
        assert mc.is_reasoning_model() is True

    def test_is_reasoning_model_gpt5_is_true(self):
        mc = ModelConfig(provider="openai", name="gpt-5-mini")
        assert mc.is_reasoning_model() is True

    def test_is_reasoning_model_gpt5(self):
        mc = ModelConfig(provider="openai", name="gpt-5")
        assert mc.is_reasoning_model() is True

    def test_is_reasoning_model_gpt5_turbo(self):
        mc = ModelConfig(provider="openai", name="gpt-5-turbo")
        assert mc.is_reasoning_model() is True

    def test_is_reasoning_model_gpt5_chat_is_false(self):
        mc = ModelConfig(provider="openai", name="gpt-5-chat")
        assert mc.is_reasoning_model() is False

    def test_is_reasoning_model_gpt51_is_false(self):
        mc = ModelConfig(provider="openai", name="gpt-5.1")
        assert mc.is_reasoning_model() is False

    def test_is_reasoning_model_gpt52_turbo_is_false(self):
        mc = ModelConfig(provider="openai", name="gpt-5.2-turbo")
        assert mc.is_reasoning_model() is False

    def test_is_reasoning_model_gpt4o_is_false(self):
        mc = ModelConfig(provider="openai", name="gpt-4o")
        assert mc.is_reasoning_model() is False

    def test_is_reasoning_model_non_openai_provider(self):
        mc = ModelConfig(provider="anthropic", name="o3-mini")
        assert mc.is_reasoning_model() is False


class TestGuardrails:
    def test_defaults(self):
        g = Guardrails()
        assert g.max_tokens_per_run == 50000
        assert g.max_tool_calls == 20
        assert g.timeout_seconds == 300
        assert g.max_request_limit == 30
        assert g.input_tokens_limit is None
        assert g.total_tokens_limit is None
        assert g.session_token_budget is None
        assert g.daemon_token_budget is None
        assert g.daemon_daily_token_budget is None

    def test_custom_values(self):
        g = Guardrails(max_tokens_per_run=10000, max_tool_calls=5)
        assert g.max_tokens_per_run == 10000
        assert g.max_tool_calls == 5

    def test_zero_not_allowed(self):
        with pytest.raises(ValidationError):
            Guardrails(max_tokens_per_run=0)

    def test_new_token_limit_fields(self):
        g = Guardrails(
            input_tokens_limit=100000,
            total_tokens_limit=200000,
            session_token_budget=500000,
            daemon_token_budget=2000000,
            daemon_daily_token_budget=200000,
        )
        assert g.input_tokens_limit == 100000
        assert g.total_tokens_limit == 200000
        assert g.session_token_budget == 500000
        assert g.daemon_token_budget == 2000000
        assert g.daemon_daily_token_budget == 200000

    def test_token_limit_zero_rejected(self):
        with pytest.raises(ValidationError):
            Guardrails(input_tokens_limit=0)
        with pytest.raises(ValidationError):
            Guardrails(total_tokens_limit=0)
        with pytest.raises(ValidationError):
            Guardrails(session_token_budget=0)
        with pytest.raises(ValidationError):
            Guardrails(daemon_token_budget=0)
        with pytest.raises(ValidationError):
            Guardrails(daemon_daily_token_budget=0)

    def test_token_limit_negative_rejected(self):
        with pytest.raises(ValidationError):
            Guardrails(input_tokens_limit=-1)
        with pytest.raises(ValidationError):
            Guardrails(session_token_budget=-100)


class TestToolConfig:
    def test_filesystem_tool(self):
        tc = FileSystemToolConfig(root_path="/tmp", read_only=False)
        assert tc.type == "filesystem"
        assert tc.root_path == "/tmp"
        assert tc.read_only is False

    def test_filesystem_defaults(self):
        tc = FileSystemToolConfig()
        assert tc.root_path == "."
        assert tc.read_only is True
        assert tc.allowed_extensions == []

    def test_http_tool(self):
        tc = HttpToolConfig(base_url="https://api.example.com", allowed_methods=["GET", "POST"])
        assert tc.type == "http"
        assert tc.base_url == "https://api.example.com"

    def test_mcp_tool_stdio(self):
        tc = McpToolConfig(command="npx", args=["-y", "@anthropic/mcp-server-filesystem"])
        assert tc.type == "mcp"
        assert tc.transport == "stdio"
        assert tc.command == "npx"

    def test_mcp_tool_sse(self):
        tc = McpToolConfig(transport="sse", url="http://localhost:8080/sse")
        assert tc.transport == "sse"

    def test_custom_tool(self):
        tc = CustomToolConfig(module="mytools", function="my_func")
        assert tc.type == "custom"

    def test_discriminated_union_from_dict(self):
        data = _minimal_role_data()
        data["spec"]["tools"] = [{"type": "filesystem", "root_path": "/src"}]
        role = RoleDefinition.model_validate(data)
        assert isinstance(role.spec.tools[0], FileSystemToolConfig)
        assert role.spec.tools[0].root_path == "/src"

    def test_unknown_tool_type_becomes_plugin(self):
        """Unknown tool types are captured as PluginToolConfig for plugin extensibility."""
        data = _minimal_role_data()
        data["spec"]["tools"] = [{"type": "unknown_tool", "api_key": "test"}]
        role = RoleDefinition.model_validate(data)
        from initrunner.agent.schema.tools import PluginToolConfig

        assert isinstance(role.spec.tools[0], PluginToolConfig)
        assert role.spec.tools[0].type == "unknown_tool"
        assert role.spec.tools[0].config == {"api_key": "test"}


class TestTriggerConfig:
    def test_cron_trigger(self):
        tc = CronTriggerConfig(schedule="0 9 * * 1", prompt="Weekly report")
        assert tc.type == "cron"
        assert tc.timezone == "UTC"

    def test_file_watch_trigger(self):
        tc = FileWatchTriggerConfig(paths=["./docs"])
        assert tc.type == "file_watch"
        assert tc.debounce_seconds == 1.0

    def test_webhook_trigger(self):
        tc = WebhookTriggerConfig()
        assert tc.type == "webhook"
        assert tc.port == 8080
        assert tc.secret is not None  # auto-generated

    def test_discriminated_union_from_dict(self):
        data = _minimal_role_data()
        data["spec"]["triggers"] = [{"type": "cron", "schedule": "daily", "prompt": "run"}]
        role = RoleDefinition.model_validate(data)
        assert isinstance(role.spec.triggers[0], CronTriggerConfig)

    def test_invalid_trigger_type(self):
        data = _minimal_role_data()
        data["spec"]["triggers"] = [{"type": "unknown_trigger"}]
        with pytest.raises(ValidationError):
            RoleDefinition.model_validate(data)


class TestIngestConfig:
    def test_minimal_ingest(self):
        ic = IngestConfig(sources=["./docs/**/*.md"])
        assert ic.sources == ["./docs/**/*.md"]
        assert ic.watch is False
        assert ic.chunking.strategy == "fixed"
        assert ic.chunking.chunk_size == 512

    def test_full_ingest(self):
        ic = IngestConfig(
            sources=["./docs/**/*.md", "./data/*.json"],
            watch=True,
            chunking=ChunkingConfig(strategy="paragraph", chunk_size=1024, chunk_overlap=100),
            embeddings=EmbeddingConfig(provider="openai", model="text-embedding-3-small"),
            store_path="/tmp/test.db",
        )
        assert ic.watch is True
        assert ic.chunking.strategy == "paragraph"
        assert ic.embeddings.model == "text-embedding-3-small"
        assert ic.store_path == "/tmp/test.db"

    def test_embedding_config_base_url_default(self):
        ec = EmbeddingConfig()
        assert ec.base_url == ""

    def test_embedding_config_base_url_explicit(self):
        ec = EmbeddingConfig(
            provider="ollama", model="nomic-embed-text", base_url="http://localhost:11434/v1"
        )
        assert ec.base_url == "http://localhost:11434/v1"

    def test_embedding_config_api_key_env_default(self):
        ec = EmbeddingConfig()
        assert ec.api_key_env == ""

    def test_embedding_config_api_key_env_explicit(self):
        ec = EmbeddingConfig(
            provider="custom",
            model="my-model",
            base_url="http://my-server/v1",
            api_key_env="MY_EMBED_KEY",
        )
        assert ec.api_key_env == "MY_EMBED_KEY"

    def test_ingest_in_role(self):
        data = _minimal_role_data()
        data["spec"]["ingest"] = {"sources": ["./kb/**/*.md"]}
        role = RoleDefinition.model_validate(data)
        assert role.spec.ingest is not None
        assert role.spec.ingest.sources == ["./kb/**/*.md"]

    def test_no_ingest_by_default(self):
        role = RoleDefinition.model_validate(_minimal_role_data())
        assert role.spec.ingest is None


class TestFullRoleDefinition:
    def test_with_all_fields(self):
        data = _minimal_role_data()
        data["metadata"]["tags"] = ["test", "ci"]
        data["spec"]["model"]["temperature"] = 0.5
        data["spec"]["model"]["max_tokens"] = 2048
        data["spec"]["guardrails"] = {
            "max_tokens_per_run": 10000,
            "max_tool_calls": 5,
            "timeout_seconds": 60,
            "max_request_limit": 10,
        }
        data["spec"]["tools"] = [{"type": "filesystem"}]
        data["spec"]["triggers"] = [{"type": "cron", "schedule": "daily", "prompt": "run"}]
        data["spec"]["ingest"] = {"sources": ["./docs/**/*.md"]}

        role = RoleDefinition.model_validate(data)
        assert role.metadata.tags == ["test", "ci"]
        assert role.spec.model.temperature == 0.5
        assert role.spec.guardrails.max_tokens_per_run == 10000
        assert len(role.spec.tools) == 1
        assert len(role.spec.triggers) == 1
        assert role.spec.ingest is not None


class TestSinkConfig:
    def test_webhook_sink(self):
        sc = WebhookSinkConfig(url="https://example.com/hook")
        assert sc.type == "webhook"
        assert sc.method == "POST"
        assert sc.headers == {}
        assert sc.timeout_seconds == 30
        assert sc.retry_count == 0

    def test_webhook_sink_full(self):
        sc = WebhookSinkConfig(
            url="https://example.com/hook",
            method="PUT",
            headers={"Authorization": "Bearer token"},
            timeout_seconds=60,
            retry_count=3,
        )
        assert sc.method == "PUT"
        assert sc.headers["Authorization"] == "Bearer token"
        assert sc.timeout_seconds == 60
        assert sc.retry_count == 3

    def test_file_sink(self):
        sc = FileSinkConfig(path="./results.jsonl")
        assert sc.type == "file"
        assert sc.path == "./results.jsonl"
        assert sc.format == "json"

    def test_file_sink_text_format(self):
        sc = FileSinkConfig(path="./results.txt", format="text")
        assert sc.format == "text"

    def test_file_sink_invalid_format(self):
        with pytest.raises(ValidationError):
            FileSinkConfig(path="./results.txt", format="csv")  # type: ignore[arg-type]

    def test_custom_sink(self):
        sc = CustomSinkConfig(module="my_handlers", function="notify")
        assert sc.type == "custom"
        assert sc.module == "my_handlers"
        assert sc.function == "notify"

    def test_discriminated_union_from_dict(self):
        data = _minimal_role_data()
        data["spec"]["sinks"] = [{"type": "webhook", "url": "https://example.com"}]
        role = RoleDefinition.model_validate(data)
        assert isinstance(role.spec.sinks[0], WebhookSinkConfig)
        assert role.spec.sinks[0].url == "https://example.com"

    def test_multiple_sinks(self):
        data = _minimal_role_data()
        data["spec"]["sinks"] = [
            {"type": "webhook", "url": "https://example.com"},
            {"type": "file", "path": "./out.jsonl"},
            {"type": "custom", "module": "mod", "function": "fn"},
        ]
        role = RoleDefinition.model_validate(data)
        assert len(role.spec.sinks) == 3
        assert isinstance(role.spec.sinks[0], WebhookSinkConfig)
        assert isinstance(role.spec.sinks[1], FileSinkConfig)
        assert isinstance(role.spec.sinks[2], CustomSinkConfig)

    def test_invalid_sink_type(self):
        data = _minimal_role_data()
        data["spec"]["sinks"] = [{"type": "unknown_sink"}]
        with pytest.raises(ValidationError):
            RoleDefinition.model_validate(data)

    def test_no_sinks_by_default(self):
        role = RoleDefinition.model_validate(_minimal_role_data())
        assert role.spec.sinks == []


class TestDelegateToolConfig:
    def test_inline_valid(self):
        cfg = DelegateToolConfig(
            agents=[
                DelegateAgentRef(
                    name="summarizer",
                    role_file="./roles/summarizer.yaml",
                    description="Summarizes text",
                )
            ],
            mode="inline",
        )
        assert cfg.type == "delegate"
        assert cfg.mode == "inline"
        assert cfg.max_depth == 3
        assert cfg.timeout_seconds == 120
        assert len(cfg.agents) == 1

    def test_mcp_valid(self):
        cfg = DelegateToolConfig(
            agents=[
                DelegateAgentRef(
                    name="summarizer",
                    url="http://summarizer:8000",
                    description="Summarizes text",
                )
            ],
            mode="mcp",
        )
        assert cfg.mode == "mcp"
        assert cfg.agents[0].url == "http://summarizer:8000"

    def test_inline_requires_role_file(self):
        with pytest.raises(ValidationError, match="role_file"):
            DelegateToolConfig(
                agents=[DelegateAgentRef(name="agent-a")],
                mode="inline",
            )

    def test_mcp_requires_url(self):
        with pytest.raises(ValidationError, match="url"):
            DelegateToolConfig(
                agents=[DelegateAgentRef(name="agent-a")],
                mode="mcp",
            )

    def test_summary(self):
        cfg = DelegateToolConfig(
            agents=[
                DelegateAgentRef(name="a", role_file="a.yaml"),
                DelegateAgentRef(name="b", role_file="b.yaml"),
            ],
            mode="inline",
        )
        assert "a, b" in cfg.summary()
        assert "inline" in cfg.summary()

    def test_headers_env(self):
        ref = DelegateAgentRef(
            name="agent",
            url="http://agent:8000",
            headers_env={"Authorization": "AUTH_TOKEN"},
        )
        assert ref.headers_env == {"Authorization": "AUTH_TOKEN"}

    def test_discriminated_union_from_dict(self):
        data = _minimal_role_data()
        data["spec"]["tools"] = [
            {
                "type": "delegate",
                "agents": [{"name": "sub", "role_file": "./sub.yaml", "description": "sub agent"}],
                "mode": "inline",
            }
        ]
        role = RoleDefinition.model_validate(data)
        assert isinstance(role.spec.tools[0], DelegateToolConfig)
        assert role.spec.tools[0].agents[0].name == "sub"

    def test_multiple_agents(self):
        cfg = DelegateToolConfig(
            agents=[
                DelegateAgentRef(name="a", role_file="a.yaml"),
                DelegateAgentRef(name="b", role_file="b.yaml"),
                DelegateAgentRef(name="c", role_file="c.yaml"),
            ],
            mode="inline",
        )
        assert len(cfg.agents) == 3


class TestNewToolConfigs:
    """Tests for the 4 new built-in tool configs."""

    def test_web_reader_defaults(self):
        tc = WebReaderToolConfig()
        assert tc.type == "web_reader"
        assert tc.allowed_domains == []
        assert tc.blocked_domains == []
        assert tc.max_content_bytes == 512_000
        assert tc.timeout_seconds == 15
        assert tc.user_agent == f"initrunner/{__version__}"

    def test_web_reader_summary_with_domains(self):
        tc = WebReaderToolConfig(allowed_domains=["a.com", "b.com"])
        assert "a.com" in tc.summary()

    def test_web_reader_from_dict(self):
        data = _minimal_role_data()
        data["spec"]["tools"] = [{"type": "web_reader", "timeout_seconds": 10}]
        role = RoleDefinition.model_validate(data)
        assert isinstance(role.spec.tools[0], WebReaderToolConfig)
        assert role.spec.tools[0].timeout_seconds == 10

    def test_python_defaults(self):
        tc = PythonToolConfig()
        assert tc.type == "python"
        assert tc.timeout_seconds == 30
        assert tc.max_output_bytes == 102_400
        assert tc.working_dir is None
        assert tc.require_confirmation is True

    def test_python_summary(self):
        tc = PythonToolConfig()
        s = tc.summary()
        assert "python" in s
        assert "confirm" in s

    def test_python_from_dict(self):
        data = _minimal_role_data()
        data["spec"]["tools"] = [{"type": "python", "timeout_seconds": 60}]
        role = RoleDefinition.model_validate(data)
        assert isinstance(role.spec.tools[0], PythonToolConfig)
        assert role.spec.tools[0].timeout_seconds == 60

    def test_datetime_defaults(self):
        tc = DateTimeToolConfig()
        assert tc.type == "datetime"
        assert tc.default_timezone == "UTC"

    def test_datetime_summary(self):
        tc = DateTimeToolConfig(default_timezone="US/Eastern")
        assert "US/Eastern" in tc.summary()

    def test_datetime_from_dict(self):
        data = _minimal_role_data()
        data["spec"]["tools"] = [{"type": "datetime", "default_timezone": "US/Pacific"}]
        role = RoleDefinition.model_validate(data)
        assert isinstance(role.spec.tools[0], DateTimeToolConfig)
        assert role.spec.tools[0].default_timezone == "US/Pacific"

    def test_sql_required_database(self):
        with pytest.raises(ValidationError):
            SqlToolConfig()  # type: ignore[missing-argument]  # database is required

    def test_sql_defaults(self):
        tc = SqlToolConfig(database="./data.db")
        assert tc.type == "sql"
        assert tc.read_only is True
        assert tc.max_rows == 100
        assert tc.max_result_bytes == 102_400
        assert tc.timeout_seconds == 10

    def test_sql_summary(self):
        tc = SqlToolConfig(database="./data.db")
        assert "data.db" in tc.summary()
        assert "ro=True" in tc.summary()

    def test_sql_from_dict(self):
        data = _minimal_role_data()
        data["spec"]["tools"] = [{"type": "sql", "database": "./test.db", "read_only": False}]
        role = RoleDefinition.model_validate(data)
        assert isinstance(role.spec.tools[0], SqlToolConfig)
        assert role.spec.tools[0].read_only is False

    def test_git_defaults(self):
        tc = GitToolConfig()
        assert tc.type == "git"
        assert tc.repo_path == "."
        assert tc.read_only is True
        assert tc.timeout_seconds == 30
        assert tc.max_output_bytes == 102_400

    def test_git_summary(self):
        tc = GitToolConfig(repo_path="/my/repo", read_only=False)
        s = tc.summary()
        assert "/my/repo" in s
        assert "ro=False" in s

    def test_git_from_dict(self):
        data = _minimal_role_data()
        data["spec"]["tools"] = [{"type": "git", "repo_path": "/src", "read_only": False}]
        role = RoleDefinition.model_validate(data)
        assert isinstance(role.spec.tools[0], GitToolConfig)
        assert role.spec.tools[0].repo_path == "/src"
        assert role.spec.tools[0].read_only is False

    def test_all_new_types_in_builtin_registry(self):
        from initrunner.agent.tools._registry import get_tool_types

        builtin = get_tool_types()
        assert "web_reader" in builtin
        assert "python" in builtin
        assert "datetime" in builtin
        assert "sql" in builtin
        assert "git" in builtin


class TestParseToolList:
    def test_parses_builtin_type(self):
        result = parse_tool_list([{"type": "datetime"}])
        assert len(result) == 1
        assert isinstance(result[0], DateTimeToolConfig)

    def test_parses_unknown_as_plugin(self):
        from initrunner.agent.schema.tools import PluginToolConfig

        result = parse_tool_list([{"type": "custom_xyz", "key": "val"}])
        assert len(result) == 1
        assert isinstance(result[0], PluginToolConfig)
        assert result[0].config == {"key": "val"}

    def test_non_list_passthrough(self):
        assert parse_tool_list("not a list") == "not a list"

    def test_empty_list(self):
        assert parse_tool_list([]) == []

    def test_already_parsed_items(self):
        dt = DateTimeToolConfig()
        result = parse_tool_list([dt])
        assert result == [dt]


class TestOutputConfig:
    def test_default_is_text(self):
        config = OutputConfig()
        assert config.type == "text"
        assert config.schema_ is None
        assert config.schema_file is None

    def test_explicit_text(self):
        config = OutputConfig(type="text")
        assert config.type == "text"

    def test_json_schema_with_inline_schema(self):
        config = OutputConfig.model_validate(
            {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            }
        )
        assert config.type == "json_schema"
        assert config.schema_ is not None

    def test_json_schema_with_schema_file(self):
        config = OutputConfig(type="json_schema", schema_file="./output.json")
        assert config.type == "json_schema"
        assert config.schema_file == "./output.json"

    def test_json_schema_without_schema_or_file_raises(self):
        with pytest.raises(ValidationError, match="json_schema output requires"):
            OutputConfig(type="json_schema")

    def test_json_schema_both_schema_and_file_raises(self):
        with pytest.raises(ValidationError, match="mutually exclusive"):
            OutputConfig.model_validate(
                {
                    "type": "json_schema",
                    "schema": {"type": "object", "properties": {}},
                    "schema_file": "./output.json",
                }
            )

    def test_text_ignores_schema(self):
        """text type with schema set is allowed (schema is just ignored)."""
        config = OutputConfig.model_validate(
            {
                "type": "text",
                "schema": {"type": "object"},
            }
        )
        assert config.type == "text"
        assert config.schema_ is not None

    def test_role_definition_default_output(self):
        data = _minimal_role_data()
        role = RoleDefinition.model_validate(data)
        assert role.spec.output.type == "text"

    def test_role_definition_with_output(self):
        data = _minimal_role_data()
        data["spec"]["output"] = {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["approved", "rejected"]},
                    "amount": {"type": "number"},
                },
                "required": ["status", "amount"],
            },
        }
        role = RoleDefinition.model_validate(data)
        assert role.spec.output.type == "json_schema"
        assert role.spec.output.schema_ is not None
        assert "status" in role.spec.output.schema_["properties"]

    def test_role_definition_output_schema_file(self):
        data = _minimal_role_data()
        data["spec"]["output"] = {
            "type": "json_schema",
            "schema_file": "./invoice_result.json",
        }
        role = RoleDefinition.model_validate(data)
        assert role.spec.output.type == "json_schema"
        assert role.spec.output.schema_file == "./invoice_result.json"

    def test_alias_schema_works(self):
        """The 'schema' alias maps to schema_ field."""
        config = OutputConfig.model_validate(
            {
                "type": "json_schema",
                "schema": {"type": "object", "properties": {}},
            }
        )
        assert config.schema_ is not None
