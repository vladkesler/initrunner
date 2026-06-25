"""Tests for spec.execution config and its wiring into Agent()."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from initrunner.agent.loader import RoleLoadError, build_agent, load_role
from initrunner.agent.schema.execution import ConcurrencyConfig, ExecutionConfig
from initrunner.agent.schema.role import AgentSpec


class TestExecutionConfigDefaults:
    def test_defaults_match_pydantic_ai(self):
        ec = ExecutionConfig()
        assert ec.retries == 1
        assert ec.output_retries is None
        assert ec.end_strategy == "graceful"
        assert ec.tool_timeout_seconds is None

    def test_bounds_rejected(self):
        with pytest.raises(ValueError):
            ExecutionConfig(retries=-1)
        with pytest.raises(ValueError):
            ExecutionConfig(retries=11)
        with pytest.raises(ValueError):
            ExecutionConfig(tool_timeout_seconds=0)

    def test_end_strategy_literal(self):
        with pytest.raises(ValueError):
            ExecutionConfig(end_strategy="neither")  # type: ignore[arg-type]

    def test_max_concurrency_defaults_none(self):
        assert ExecutionConfig().max_concurrency is None


class TestConcurrencyConfig:
    def test_max_running_required(self):
        with pytest.raises(ValueError):
            ConcurrencyConfig()  # type: ignore[call-arg]

    def test_max_running_lower_bound(self):
        with pytest.raises(ValueError):
            ConcurrencyConfig(max_running=0)

    def test_max_queued_lower_bound(self):
        with pytest.raises(ValueError):
            ConcurrencyConfig(max_running=1, max_queued=-1)

    def test_round_trip(self):
        cfg = ExecutionConfig.model_validate(
            {"max_concurrency": {"max_running": 2, "max_queued": 4}}
        )
        assert cfg.max_concurrency is not None
        assert cfg.max_concurrency.max_running == 2
        assert cfg.max_concurrency.max_queued == 4


class TestAgentSpecIntegration:
    def test_spec_has_execution_default(self):
        spec = AgentSpec(role="hi")
        assert isinstance(spec.execution, ExecutionConfig)
        assert spec.execution.retries == 1


def _write_role(tmp_path: Path, execution_block: str = "") -> Path:
    content = textwrap.dedent(f"""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: exec-agent
        spec:
          role: hi
          model:
            provider: openai
            name: gpt-5-mini
          {execution_block}
    """)
    p = tmp_path / "role.yaml"
    p.write_text(content)
    return p


class TestExecutionFieldsWiredToAgent:
    def test_defaults_wired(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        role = load_role(_write_role(tmp_path))
        agent = build_agent(role)
        assert agent._max_tool_retries == 1
        assert agent.end_strategy == "graceful"
        assert agent._tool_timeout is None

    def test_overrides_applied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        execution = (
            textwrap.dedent("""\
            execution:
                retries: 3
                output_retries: 2
                end_strategy: exhaustive
                tool_timeout_seconds: 12.5
        """)
            .replace("\n", "\n          ")
            .rstrip()
        )
        role = load_role(_write_role(tmp_path, execution))
        agent = build_agent(role)
        assert agent._max_tool_retries == 3
        assert agent.end_strategy == "exhaustive"
        assert agent._max_output_retries == 2
        assert agent._tool_timeout == 12.5

    def test_max_concurrency_wired(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        execution = (
            textwrap.dedent("""\
            execution:
                max_concurrency:
                  max_running: 2
                  max_queued: 4
        """)
            .replace("\n", "\n          ")
            .rstrip()
        )
        role = load_role(_write_role(tmp_path, execution))
        agent = build_agent(role)
        limiter = agent._concurrency_limiter
        assert limiter is not None
        assert getattr(limiter, "max_running") == 2  # noqa: B009
        assert getattr(limiter, "_max_queued") == 4  # noqa: B009

    def test_max_concurrency_absent_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        role = load_role(_write_role(tmp_path))
        agent = build_agent(role)
        assert agent._concurrency_limiter is None

    def test_yaml_schema_violation_surfaces(self, tmp_path: Path):
        bad = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: bad
            spec:
              role: hi
              model:
                provider: openai
                name: gpt-5-mini
              execution:
                end_strategy: maybe
        """)
        p = tmp_path / "role.yaml"
        p.write_text(bad)
        with pytest.raises(RoleLoadError):
            load_role(p)
