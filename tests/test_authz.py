"""Unit tests for initrunner.authz -- config, ContextVars, engine loading, and helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from initrunner.authz import (
    AuthzConfig,
    Decision,
    Principal,
    _current_agent_principal,
    _current_engine,
    agent_principal_from_role,
    get_current_agent_principal,
    get_current_engine,
    load_authz_config,
    load_engine,
    set_current_agent_principal,
    set_current_engine,
)

POLICIES_DIR = Path(__file__).resolve().parent.parent / "examples" / "policies" / "agent"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_context():
    """Reset ContextVars before and after each test."""
    set_current_agent_principal(None)
    set_current_engine(None)
    yield
    set_current_agent_principal(None)
    set_current_engine(None)


# ---------------------------------------------------------------------------
# TestAuthzConfig
# ---------------------------------------------------------------------------


class TestAuthzConfig:
    """AuthzConfig Pydantic model defaults and custom values."""

    def test_minimal(self):
        cfg = AuthzConfig(policy_dir="/policies")
        assert cfg.policy_dir == "/policies"
        assert cfg.agent_checks is True

    def test_agent_checks_false(self):
        cfg = AuthzConfig(policy_dir="/policies", agent_checks=False)
        assert cfg.agent_checks is False


# ---------------------------------------------------------------------------
# TestLoadAuthzConfig
# ---------------------------------------------------------------------------


class TestLoadAuthzConfig:
    """Environment variable parsing via load_authz_config()."""

    def test_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("INITRUNNER_POLICY_DIR", raising=False)
        assert load_authz_config() is None

    def test_returns_none_for_empty_string(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_POLICY_DIR", "")
        assert load_authz_config() is None

    def test_returns_none_for_whitespace(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_POLICY_DIR", "  ")
        assert load_authz_config() is None

    def test_returns_config_when_set(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_POLICY_DIR", "/my/policies")
        monkeypatch.delenv("INITRUNNER_AGENT_CHECKS", raising=False)
        cfg = load_authz_config()
        assert cfg is not None
        assert cfg.policy_dir == "/my/policies"
        assert cfg.agent_checks is True  # default

    @pytest.mark.parametrize("val", ["1", "true", "True", "TRUE", "yes", "YES"])
    def test_agent_checks_truthy(self, monkeypatch, val):
        monkeypatch.setenv("INITRUNNER_POLICY_DIR", "/policies")
        monkeypatch.setenv("INITRUNNER_AGENT_CHECKS", val)
        cfg = load_authz_config()
        assert cfg is not None
        assert cfg.agent_checks is True

    @pytest.mark.parametrize("val", ["0", "false", "False", "no", "off", ""])
    def test_agent_checks_falsy(self, monkeypatch, val):
        monkeypatch.setenv("INITRUNNER_POLICY_DIR", "/policies")
        monkeypatch.setenv("INITRUNNER_AGENT_CHECKS", val)
        cfg = load_authz_config()
        assert cfg is not None
        assert cfg.agent_checks is False


# ---------------------------------------------------------------------------
# TestContextVars
# ---------------------------------------------------------------------------


class TestContextVars:
    """ContextVar set/get lifecycle and token reset."""

    def test_engine_default_is_none(self):
        assert get_current_engine() is None

    def test_set_get_engine(self):
        sentinel = MagicMock()
        set_current_engine(sentinel)
        assert get_current_engine() is sentinel

    def test_engine_token_reset(self):
        sentinel = MagicMock()
        token = set_current_engine(sentinel)
        assert get_current_engine() is sentinel
        _current_engine.reset(token)
        assert get_current_engine() is None

    def test_agent_principal_default_is_none(self):
        assert get_current_agent_principal() is None

    def test_set_get_agent_principal(self):
        p = Principal(id="agent:test", roles=["agent"])
        set_current_agent_principal(p)
        assert get_current_agent_principal() is p

    def test_agent_principal_token_reset(self):
        p = Principal(id="agent:test", roles=["agent"])
        token = set_current_agent_principal(p)
        assert get_current_agent_principal() is p
        _current_agent_principal.reset(token)
        assert get_current_agent_principal() is None


# ---------------------------------------------------------------------------
# TestAgentPrincipalFromRole
# ---------------------------------------------------------------------------


class TestAgentPrincipalFromRole:
    """agent_principal_from_role() constructs correct Principal."""

    def test_basic(self):
        meta = MagicMock(name="my-agent", team="", author="", tags=[], version="")
        meta.name = "my-agent"
        p = agent_principal_from_role(meta)
        assert p.id == "agent:my-agent"
        assert p.roles == ["agent"]
        assert p.attrs["team"] == ""

    def test_with_team(self):
        meta = MagicMock()
        meta.name = "reviewer"
        meta.team = "platform"
        meta.author = "alice"
        meta.tags = ["trusted", "code"]
        meta.version = "1.0"
        p = agent_principal_from_role(meta)
        assert p.id == "agent:reviewer"
        assert "team:platform" in p.roles
        assert p.attrs["tags"] == ["trusted", "code"]
        assert p.attrs["author"] == "alice"


# ---------------------------------------------------------------------------
# TestLoadEngine
# ---------------------------------------------------------------------------


class TestLoadEngine:
    """load_engine() with real YAML policy fixtures."""

    def test_loads_example_policies(self):
        config = AuthzConfig(policy_dir=str(POLICIES_DIR))
        engine = load_engine(config)
        info = engine.info()
        assert info.policy_count >= 2
        assert info.rule_count >= 5
        assert "tool" in info.resource_kinds
        assert "agent" in info.resource_kinds
        assert info.has_schema is True

    def test_check_returns_decision(self):
        config = AuthzConfig(policy_dir=str(POLICIES_DIR))
        engine = load_engine(config)

        trusted = Principal(
            id="agent:helper",
            roles=["agent"],
            attrs={"tags": ["trusted"], "team": "ops"},
        )
        decision = engine.check(
            trusted,
            "tool",
            "execute",
            resource_attrs={"tool_type": "shell", "agent": "helper", "callable": "run"},
        )
        assert isinstance(decision, Decision)
        assert decision.allowed is True

    def test_deny_with_advice(self):
        config = AuthzConfig(policy_dir=str(POLICIES_DIR))
        engine = load_engine(config)

        untrusted = Principal(
            id="agent:basic",
            roles=["agent"],
            attrs={"tags": [], "team": ""},
        )
        decision = engine.check(
            untrusted,
            "tool",
            "execute",
            resource_attrs={"tool_type": "shell", "agent": "basic", "callable": "run"},
        )
        assert decision.allowed is False
        assert decision.advice  # should have advice text

    def test_missing_dir_raises(self, tmp_path):
        from initguard import PolicyLoadError  # type: ignore[import-not-found]

        config = AuthzConfig(policy_dir=str(tmp_path / "nonexistent"))
        with pytest.raises(PolicyLoadError):
            load_engine(config)

    def test_bad_yaml_raises(self, tmp_path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("apiVersion: initguard/v1\nkind: ResourcePolicy\n")
        from initguard import PolicyLoadError  # type: ignore[import-not-found]

        with pytest.raises(PolicyLoadError):
            load_engine(AuthzConfig(policy_dir=str(tmp_path)))
