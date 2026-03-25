"""Unit tests for initrunner.authz -- config, ContextVars, CerbosAuthz, and helpers."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from initrunner.authz import (
    AuthzConfig,
    CerbosAuthz,
    Principal,
    _current_agent_principal,
    _current_authz,
    get_current_agent_principal,
    get_current_authz,
    load_authz_config,
    require_cerbos,
    set_current_agent_principal,
    set_current_authz,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_context():
    """Reset ContextVars before and after each test."""
    set_current_agent_principal(None)
    set_current_authz(None)
    yield
    set_current_agent_principal(None)
    set_current_authz(None)


@pytest.fixture()
def mock_cerbos_sdk():
    """Patch the full cerbos SDK module hierarchy into sys.modules.

    Python's import machinery resolves parent packages first, so we must
    patch ``cerbos``, ``cerbos.sdk``, ``cerbos.sdk.client``, and
    ``cerbos.sdk.model`` together.
    """
    mock_cerbos = MagicMock()
    with patch.dict(
        "sys.modules",
        {
            "cerbos": mock_cerbos,
            "cerbos.sdk": mock_cerbos.sdk,
            "cerbos.sdk.client": mock_cerbos.sdk.client,
            "cerbos.sdk.model": mock_cerbos.sdk.model,
        },
    ):
        yield mock_cerbos


# ---------------------------------------------------------------------------
# TestAuthzConfig
# ---------------------------------------------------------------------------


class TestAuthzConfig:
    """AuthzConfig Pydantic model defaults and custom values."""

    def test_defaults(self):
        cfg = AuthzConfig()
        assert cfg.enabled is False
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 3592
        assert cfg.tls is False
        assert cfg.agent_checks is False

    def test_custom_values(self):
        cfg = AuthzConfig(
            enabled=True,
            host="cerbos.example.com",
            port=9999,
            tls=True,
            agent_checks=True,
        )
        assert cfg.enabled is True
        assert cfg.host == "cerbos.example.com"
        assert cfg.port == 9999
        assert cfg.tls is True
        assert cfg.agent_checks is True

    def test_partial_override(self):
        cfg = AuthzConfig(enabled=True, port=8080)
        assert cfg.enabled is True
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8080
        assert cfg.tls is False
        assert cfg.agent_checks is False


# ---------------------------------------------------------------------------
# TestLoadAuthzConfig
# ---------------------------------------------------------------------------


class TestLoadAuthzConfig:
    """Environment variable parsing via load_authz_config()."""

    def test_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("INITRUNNER_CERBOS_ENABLED", raising=False)
        assert load_authz_config() is None

    def test_returns_none_for_empty_string(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_CERBOS_ENABLED", "")
        assert load_authz_config() is None

    @pytest.mark.parametrize("val", ["no", "0", "false", "False", "nope", "off"])
    def test_returns_none_for_falsy(self, monkeypatch, val):
        monkeypatch.setenv("INITRUNNER_CERBOS_ENABLED", val)
        assert load_authz_config() is None

    @pytest.mark.parametrize("val", ["1", "true", "True", "TRUE", "yes", "YES"])
    def test_returns_config_for_truthy(self, monkeypatch, val):
        monkeypatch.setenv("INITRUNNER_CERBOS_ENABLED", val)
        monkeypatch.delenv("INITRUNNER_CERBOS_HOST", raising=False)
        monkeypatch.delenv("INITRUNNER_CERBOS_PORT", raising=False)
        monkeypatch.delenv("INITRUNNER_CERBOS_TLS", raising=False)
        monkeypatch.delenv("INITRUNNER_CERBOS_AGENT_CHECKS", raising=False)
        cfg = load_authz_config()
        assert cfg is not None
        assert cfg.enabled is True

    def test_custom_host_and_port(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_CERBOS_ENABLED", "true")
        monkeypatch.setenv("INITRUNNER_CERBOS_HOST", "10.0.0.5")
        monkeypatch.setenv("INITRUNNER_CERBOS_PORT", "4000")
        monkeypatch.delenv("INITRUNNER_CERBOS_TLS", raising=False)
        monkeypatch.delenv("INITRUNNER_CERBOS_AGENT_CHECKS", raising=False)
        cfg = load_authz_config()
        assert cfg is not None
        assert cfg.host == "10.0.0.5"
        assert cfg.port == 4000

    def test_tls_truthy(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_CERBOS_ENABLED", "1")
        monkeypatch.setenv("INITRUNNER_CERBOS_TLS", "true")
        monkeypatch.delenv("INITRUNNER_CERBOS_HOST", raising=False)
        monkeypatch.delenv("INITRUNNER_CERBOS_PORT", raising=False)
        monkeypatch.delenv("INITRUNNER_CERBOS_AGENT_CHECKS", raising=False)
        cfg = load_authz_config()
        assert cfg is not None
        assert cfg.tls is True

    def test_tls_falsy(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_CERBOS_ENABLED", "1")
        monkeypatch.setenv("INITRUNNER_CERBOS_TLS", "no")
        monkeypatch.delenv("INITRUNNER_CERBOS_HOST", raising=False)
        monkeypatch.delenv("INITRUNNER_CERBOS_PORT", raising=False)
        monkeypatch.delenv("INITRUNNER_CERBOS_AGENT_CHECKS", raising=False)
        cfg = load_authz_config()
        assert cfg is not None
        assert cfg.tls is False

    def test_agent_checks_truthy(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_CERBOS_ENABLED", "yes")
        monkeypatch.setenv("INITRUNNER_CERBOS_AGENT_CHECKS", "YES")
        monkeypatch.delenv("INITRUNNER_CERBOS_HOST", raising=False)
        monkeypatch.delenv("INITRUNNER_CERBOS_PORT", raising=False)
        monkeypatch.delenv("INITRUNNER_CERBOS_TLS", raising=False)
        cfg = load_authz_config()
        assert cfg is not None
        assert cfg.agent_checks is True

    def test_agent_checks_falsy(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_CERBOS_ENABLED", "1")
        monkeypatch.setenv("INITRUNNER_CERBOS_AGENT_CHECKS", "0")
        monkeypatch.delenv("INITRUNNER_CERBOS_HOST", raising=False)
        monkeypatch.delenv("INITRUNNER_CERBOS_PORT", raising=False)
        monkeypatch.delenv("INITRUNNER_CERBOS_TLS", raising=False)
        cfg = load_authz_config()
        assert cfg is not None
        assert cfg.agent_checks is False


# ---------------------------------------------------------------------------
# TestContextVars
# ---------------------------------------------------------------------------


class TestContextVars:
    """ContextVar set/get lifecycle and token reset."""

    def test_authz_default_is_none(self):
        assert get_current_authz() is None

    def test_set_get_authz(self):
        sentinel = MagicMock(spec=CerbosAuthz)
        set_current_authz(sentinel)
        assert get_current_authz() is sentinel

    def test_authz_token_reset(self):
        sentinel = MagicMock(spec=CerbosAuthz)
        token = set_current_authz(sentinel)
        assert get_current_authz() is sentinel
        _current_authz.reset(token)
        assert get_current_authz() is None

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
# TestCerbosAuthzInit
# ---------------------------------------------------------------------------


class TestCerbosAuthzInit:
    """URL construction and property access."""

    def test_http_url_no_tls(self):
        cfg = AuthzConfig(enabled=True, host="localhost", port=3592, tls=False)
        authz = CerbosAuthz(cfg)
        assert authz._http_url == "http://localhost:3592"

    def test_https_url_with_tls(self):
        cfg = AuthzConfig(enabled=True, host="cerbos.prod", port=443, tls=True)
        authz = CerbosAuthz(cfg)
        assert authz._http_url == "https://cerbos.prod:443"

    def test_agent_checks_enabled_true(self):
        cfg = AuthzConfig(enabled=True, agent_checks=True)
        authz = CerbosAuthz(cfg)
        assert authz.agent_checks_enabled is True

    def test_agent_checks_enabled_false(self):
        cfg = AuthzConfig(enabled=True, agent_checks=False)
        authz = CerbosAuthz(cfg)
        assert authz.agent_checks_enabled is False


# ---------------------------------------------------------------------------
# TestCerbosAuthzHelpers
# ---------------------------------------------------------------------------


class TestCerbosAuthzHelpers:
    """Static helper methods: _to_cerbos_principal, _to_resource_list, _is_allowed."""

    def test_to_cerbos_principal(self, mock_cerbos_sdk):
        p = Principal(id="agent:a", roles=["agent", "team:ops"], attrs={"team": "ops"})
        result = CerbosAuthz._to_cerbos_principal(p)

        CerbosPrincipal = mock_cerbos_sdk.sdk.model.Principal
        CerbosPrincipal.assert_called_once_with(
            "agent:a",
            roles={"agent", "team:ops"},
            attr={"team": "ops"},
        )
        assert result is CerbosPrincipal.return_value

    def test_to_resource_list_with_attrs(self, mock_cerbos_sdk):
        model = mock_cerbos_sdk.sdk.model
        CerbosAuthz._to_resource_list("res-1", "tool", "execute", {"tool_name": "shell"})

        model.Resource.assert_called_once_with("res-1", "tool", attr={"tool_name": "shell"})
        model.ResourceAction.assert_called_once_with(
            model.Resource.return_value, actions={"execute"}
        )
        model.ResourceList.assert_called_once_with(resources=[model.ResourceAction.return_value])

    def test_to_resource_list_none_attrs(self, mock_cerbos_sdk):
        model = mock_cerbos_sdk.sdk.model
        CerbosAuthz._to_resource_list("*", "agent", "delegate", None)

        model.Resource.assert_called_once_with("*", "agent", attr={})

    def test_is_allowed_returns_true_when_allowed(self):
        resp = MagicMock()
        resource_result = MagicMock()
        resource_result.is_allowed.return_value = True
        resp.get_resource.return_value = resource_result

        assert CerbosAuthz._is_allowed(resp, "res-1", "execute") is True
        resp.get_resource.assert_called_once_with("res-1")
        resource_result.is_allowed.assert_called_once_with("execute")

    def test_is_allowed_returns_false_when_denied(self):
        resp = MagicMock()
        resource_result = MagicMock()
        resource_result.is_allowed.return_value = False
        resp.get_resource.return_value = resource_result

        assert CerbosAuthz._is_allowed(resp, "res-1", "execute") is False

    def test_is_allowed_returns_false_when_resource_is_none(self):
        resp = MagicMock()
        resp.get_resource.return_value = None

        assert CerbosAuthz._is_allowed(resp, "missing", "read") is False


# ---------------------------------------------------------------------------
# TestCerbosAuthzCheck
# ---------------------------------------------------------------------------


class TestCerbosAuthzCheck:
    """Synchronous check() with mocked SDK."""

    def test_check_allowed(self, mock_cerbos_sdk):
        client_mock = MagicMock()
        resp_mock = MagicMock()
        resource_result = MagicMock()
        resource_result.is_allowed.return_value = True
        resp_mock.get_resource.return_value = resource_result
        client_mock.check_resources.return_value = resp_mock
        client_mock.__enter__ = MagicMock(return_value=client_mock)
        client_mock.__exit__ = MagicMock(return_value=False)

        mock_cerbos_sdk.sdk.client.CerbosClient.return_value = client_mock

        cfg = AuthzConfig(enabled=True, tls=False)
        authz = CerbosAuthz(cfg)
        p = Principal(id="agent:test", roles=["agent"])

        result = authz.check(p, "tool", "execute", resource_id="shell")

        assert result is True
        mock_cerbos_sdk.sdk.client.CerbosClient.assert_called_once_with(
            "http://127.0.0.1:3592", tls_verify=False
        )
        client_mock.check_resources.assert_called_once()

    def test_check_denied(self, mock_cerbos_sdk):
        client_mock = MagicMock()
        resp_mock = MagicMock()
        resource_result = MagicMock()
        resource_result.is_allowed.return_value = False
        resp_mock.get_resource.return_value = resource_result
        client_mock.check_resources.return_value = resp_mock
        client_mock.__enter__ = MagicMock(return_value=client_mock)
        client_mock.__exit__ = MagicMock(return_value=False)

        mock_cerbos_sdk.sdk.client.CerbosClient.return_value = client_mock

        cfg = AuthzConfig(enabled=True)
        authz = CerbosAuthz(cfg)
        p = Principal(id="agent:test", roles=["agent"])

        result = authz.check(p, "tool", "execute", resource_id="shell")

        assert result is False


# ---------------------------------------------------------------------------
# TestCerbosAuthzCheckAsync
# ---------------------------------------------------------------------------


class TestCerbosAuthzCheckAsync:
    """Async check_async() with mocked SDK."""

    @pytest.mark.asyncio
    async def test_check_async_allowed(self, mock_cerbos_sdk):
        client_mock = MagicMock()
        resp_mock = MagicMock()
        resource_result = MagicMock()
        resource_result.is_allowed.return_value = True
        resp_mock.get_resource.return_value = resource_result
        client_mock.check_resources = AsyncMock(return_value=resp_mock)
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        mock_cerbos_sdk.sdk.client.AsyncCerbosClient.return_value = client_mock

        cfg = AuthzConfig(enabled=True, tls=True, host="pdp.internal", port=8443)
        authz = CerbosAuthz(cfg)
        p = Principal(id="agent:analyzer", roles=["agent", "team:security"])

        result = await authz.check_async(p, "tool", "execute", resource_id="http")

        assert result is True
        mock_cerbos_sdk.sdk.client.AsyncCerbosClient.assert_called_once_with(
            "https://pdp.internal:8443", tls_verify=True
        )

    @pytest.mark.asyncio
    async def test_check_async_denied(self, mock_cerbos_sdk):
        client_mock = MagicMock()
        resp_mock = MagicMock()
        resp_mock.get_resource.return_value = None
        client_mock.check_resources = AsyncMock(return_value=resp_mock)
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        mock_cerbos_sdk.sdk.client.AsyncCerbosClient.return_value = client_mock

        cfg = AuthzConfig(enabled=True)
        authz = CerbosAuthz(cfg)
        p = Principal(id="agent:bot", roles=["agent"])

        result = await authz.check_async(p, "agent", "delegate", resource_id="other-agent")

        assert result is False


# ---------------------------------------------------------------------------
# TestCerbosAuthzHealthCheck
# ---------------------------------------------------------------------------


class TestCerbosAuthzHealthCheck:
    """health_check() -- healthy, unhealthy, and connection error paths."""

    def test_healthy(self, mock_cerbos_sdk):
        client_mock = MagicMock()
        client_mock.is_healthy.return_value = True
        client_mock.__enter__ = MagicMock(return_value=client_mock)
        client_mock.__exit__ = MagicMock(return_value=False)
        mock_cerbos_sdk.sdk.client.CerbosClient.return_value = client_mock

        cfg = AuthzConfig(enabled=True, host="10.0.0.1", port=3592)
        authz = CerbosAuthz(cfg)
        ok, msg = authz.health_check()

        assert ok is True
        assert "reachable" in msg
        assert "http://10.0.0.1:3592" in msg

    def test_unhealthy(self, mock_cerbos_sdk):
        client_mock = MagicMock()
        client_mock.is_healthy.return_value = False
        client_mock.__enter__ = MagicMock(return_value=client_mock)
        client_mock.__exit__ = MagicMock(return_value=False)
        mock_cerbos_sdk.sdk.client.CerbosClient.return_value = client_mock

        cfg = AuthzConfig(enabled=True)
        authz = CerbosAuthz(cfg)
        ok, msg = authz.health_check()

        assert ok is False
        assert "unhealthy" in msg

    def test_connection_error(self, mock_cerbos_sdk):
        mock_cerbos_sdk.sdk.client.CerbosClient.side_effect = ConnectionError("Connection refused")

        cfg = AuthzConfig(enabled=True, host="bad-host", port=1234)
        authz = CerbosAuthz(cfg)
        ok, msg = authz.health_check()

        assert ok is False
        assert "Cannot reach" in msg
        assert "Connection refused" in msg
        assert "Troubleshooting" in msg
        assert "http://bad-host:1234" in msg


# ---------------------------------------------------------------------------
# TestRequireCerbos
# ---------------------------------------------------------------------------


class TestRequireCerbos:
    """require_cerbos() import check."""

    def test_raises_when_sdk_missing(self):
        # Temporarily ensure cerbos.sdk is NOT importable by removing it
        # from sys.modules and making the import fail.
        saved = {}
        for key in list(sys.modules):
            if key == "cerbos" or key.startswith("cerbos."):
                saved[key] = sys.modules.pop(key)
        try:
            with patch.dict("sys.modules", {"cerbos": None, "cerbos.sdk": None}):
                with pytest.raises(RuntimeError, match="uv pip install initrunner"):
                    require_cerbos()
        finally:
            sys.modules.update(saved)

    def test_passes_when_sdk_present(self, mock_cerbos_sdk):
        # Should not raise when the mock SDK hierarchy is in sys.modules
        require_cerbos()
