"""Tests for PydanticAI capabilities integration."""

import logging
import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic_ai._spec import NamedSpec  # type: ignore[import-not-found]

from initrunner.agent.loader import RoleLoadError, build_agent, load_role

fastapi = pytest.importorskip("fastapi", reason="dashboard extras not installed")
from initrunner.dashboard.routers.agents import _capability_summaries  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_role(tmp_path: Path, extra_spec: str = "") -> Path:
    base = textwrap.dedent("""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: cap-test
          description: test
        spec:
          role: You are helpful.
          model:
            provider: anthropic
            name: claude-sonnet-4-5-20250929
    """)
    content = base + extra_spec
    p = tmp_path / "role.yaml"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Schema-level tests
# ---------------------------------------------------------------------------


class TestAgentSpecCapabilities:
    def test_default_empty(self, tmp_path: Path):
        role = load_role(_write_role(tmp_path))
        assert role.spec.capabilities == []

    def test_bare_string(self, tmp_path: Path):
        p = _write_role(tmp_path, "  capabilities:\n    - WebSearch\n")
        role = load_role(p)
        assert len(role.spec.capabilities) == 1
        ns = role.spec.capabilities[0]
        assert ns.name == "WebSearch"
        assert ns.arguments is None

    def test_single_value(self, tmp_path: Path):
        p = _write_role(tmp_path, "  capabilities:\n    - Thinking: high\n")
        role = load_role(p)
        assert len(role.spec.capabilities) == 1
        ns = role.spec.capabilities[0]
        assert ns.name == "Thinking"
        assert ns.arguments == ("high",)

    def test_kwargs_dict(self, tmp_path: Path):
        p = _write_role(
            tmp_path,
            "  capabilities:\n    - MCP:\n        url: https://mcp.example.com\n",
        )
        role = load_role(p)
        assert len(role.spec.capabilities) == 1
        ns = role.spec.capabilities[0]
        assert ns.name == "MCP"
        assert ns.arguments == {"url": "https://mcp.example.com"}

    def test_mixed_forms(self, tmp_path: Path):
        p = _write_role(
            tmp_path,
            "  capabilities:\n"
            "    - WebSearch\n"
            "    - Thinking: high\n"
            "    - MCP:\n"
            "        url: https://mcp.example.com\n",
        )
        role = load_role(p)
        assert len(role.spec.capabilities) == 3
        assert role.spec.capabilities[0].name == "WebSearch"
        assert role.spec.capabilities[1].name == "Thinking"
        assert role.spec.capabilities[2].name == "MCP"

    def test_features_includes_capabilities(self, tmp_path: Path):
        p = _write_role(tmp_path, "  capabilities:\n    - Thinking: high\n")
        role = load_role(p)
        assert "capabilities" in role.spec.features

    def test_features_excludes_when_empty(self, tmp_path: Path):
        role = load_role(_write_role(tmp_path))
        assert "capabilities" not in role.spec.features

    def test_invalid_item_rejected(self):
        """Non-string, non-dict items should be rejected by NamedSpec validation."""
        with pytest.raises(ValueError):
            NamedSpec.model_validate(42)


# ---------------------------------------------------------------------------
# Loader-level tests
# ---------------------------------------------------------------------------


class TestBuildAgentCapabilities:
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_passes_capabilities(self, mock_require, mock_agent_cls, tmp_path: Path):
        """Capabilities are instantiated and passed to Agent()."""
        p = _write_role(tmp_path, "  capabilities:\n    - Thinking: high\n")
        role = load_role(p)

        with patch(
            "pydantic_ai.agent.spec.load_capability_from_nested_spec",
            return_value="mock_capability",
        ):
            build_agent(role)

        call_kwargs = mock_agent_cls.call_args.kwargs
        assert "capabilities" in call_kwargs
        assert call_kwargs["capabilities"] == ["mock_capability"]

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_no_capabilities_by_default(self, mock_require, mock_agent_cls, tmp_path: Path):
        role = load_role(_write_role(tmp_path))
        build_agent(role)
        call_kwargs = mock_agent_cls.call_args.kwargs
        assert "capabilities" not in call_kwargs

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_warning_thinking_plus_reasoning(
        self, mock_require, mock_agent_cls, tmp_path: Path, caplog, monkeypatch
    ):
        monkeypatch.setattr(logging.getLogger("initrunner"), "propagate", True)
        p = _write_role(
            tmp_path,
            "  reasoning:\n"
            "    pattern: reflexion\n"
            "    reflection_rounds: 1\n"
            "  capabilities:\n"
            "    - Thinking: high\n"
            "  tools:\n"
            "    - type: think\n",
        )
        role = load_role(p)

        with (
            patch(
                "pydantic_ai.agent.spec.load_capability_from_nested_spec",
                return_value="mock_cap",
            ),
            caplog.at_level(logging.WARNING),
        ):
            build_agent(role)

        assert any("Thinking capability" in r.message for r in caplog.records)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("initrunner.agent.loader.Agent")
    @patch("initrunner.agent.loader.require_provider")
    def test_warning_mcp_capability_plus_mcp_tool(
        self, mock_require, mock_agent_cls, tmp_path: Path, caplog, monkeypatch
    ):
        monkeypatch.setattr(logging.getLogger("initrunner"), "propagate", True)
        p = _write_role(
            tmp_path,
            "  tools:\n"
            "    - type: mcp\n"
            "      command: npx\n"
            '      args: ["-y", "some-server"]\n'
            "  capabilities:\n"
            "    - MCP:\n"
            "        url: https://mcp.example.com\n",
        )
        role = load_role(p)

        with (
            patch(
                "pydantic_ai.agent.spec.load_capability_from_nested_spec",
                return_value="mock_cap",
            ),
            caplog.at_level(logging.WARNING),
        ):
            build_agent(role)

        assert any("MCP capability" in r.message for r in caplog.records)

    def test_error_websearch_capability_plus_search_tool(self, tmp_path: Path):
        p = _write_role(
            tmp_path,
            "  tools:\n    - type: search\n  capabilities:\n    - WebSearch\n",
        )
        with pytest.raises(RoleLoadError, match=r"WebSearch.*search"):
            load_role(p)

    def test_error_webfetch_capability_plus_web_reader_tool(self, tmp_path: Path):
        p = _write_role(
            tmp_path,
            "  tools:\n    - type: web_reader\n  capabilities:\n    - WebFetch\n",
        )
        with pytest.raises(RoleLoadError, match=r"WebFetch.*web_reader"):
            load_role(p)

    def test_error_imagegen_capability_plus_image_gen_tool(self, tmp_path: Path):
        p = _write_role(
            tmp_path,
            "  tools:\n    - type: image_gen\n  capabilities:\n    - ImageGeneration\n",
        )
        with pytest.raises(RoleLoadError, match=r"ImageGeneration.*image_gen"):
            load_role(p)


# ---------------------------------------------------------------------------
# Dashboard summary tests
# ---------------------------------------------------------------------------


class TestCapabilitySummaries:
    def test_bare(self):
        specs = [NamedSpec.model_validate("WebSearch")]
        result = _capability_summaries(specs)
        assert len(result) == 1
        assert result[0].type == "WebSearch"
        assert result[0].summary == "WebSearch"
        assert result[0].config == {}

    def test_single_value(self):
        specs = [NamedSpec.model_validate({"Thinking": "high"})]
        result = _capability_summaries(specs)
        assert len(result) == 1
        assert result[0].type == "Thinking"
        assert result[0].summary == "Thinking: high"
        assert result[0].config == {"value": "high"}

    def test_kwargs(self):
        specs = [NamedSpec.model_validate({"MCP": {"url": "https://example.com"}})]
        result = _capability_summaries(specs)
        assert len(result) == 1
        assert result[0].type == "MCP"
        assert "url=https://example.com" in result[0].summary
        assert result[0].config == {"url": "https://example.com"}

    def test_empty(self):
        assert _capability_summaries([]) == []
