"""Roles that turn on Jev-backed security checks: wiring and build-time requirements."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from initrunner._compat import MissingExtraError
from initrunner.agent.capabilities import InputGuardCapability, ToolResultScreenCapability
from initrunner.agent.loader import (
    MissingApiKeyError,
    RoleLoadError,
    _build_capabilities,
    _require_role_extras,
    build_agent,
)
from initrunner.agent.schema.security import ContentPolicy, ScreeningConfig, SecurityPolicy
from tests.conftest import make_role


def _role(**screening: bool):
    return make_role(
        security=SecurityPolicy(content=ContentPolicy(screening=ScreeningConfig(**screening)))
    )


class TestCapabilities:
    def test_input_screening_attaches_the_input_guard(self):
        caps = _build_capabilities(_role(input=True)) or []
        assert any(isinstance(c, InputGuardCapability) for c in caps)

    def test_tool_result_screening_attaches_its_capability(self):
        caps = _build_capabilities(_role(tool_results=True)) or []
        assert any(isinstance(c, ToolResultScreenCapability) for c in caps)

    def test_nothing_attached_by_default(self):
        caps = _build_capabilities(make_role()) or []
        assert not any(
            isinstance(c, InputGuardCapability | ToolResultScreenCapability) for c in caps
        )


class TestBuildRequirements:
    def test_no_screening_needs_nothing(self):
        _require_role_extras(make_role())  # no key, no error

    def test_missing_key_raises_missing_api_key(self):
        # The autouse fixture leaves no TypeSafe key.
        with pytest.raises(MissingApiKeyError) as exc:
            _require_role_extras(_role(input=True))
        assert exc.value.env_var == "TYPESAFE_API_KEY"
        assert "security.content.screening.input" in str(exc.value)

    def test_missing_extra_raises_with_install_hint(self, monkeypatch):
        def _missing():
            raise MissingExtraError(
                "'typesafe-sdk' is required: uv pip install initrunner[jev]",
                extra="jev",
                pip_name="typesafe-sdk",
            )

        monkeypatch.setattr("initrunner._compat.require_jev", _missing)
        with pytest.raises(MissingExtraError, match=r"initrunner\[jev\]"):
            _require_role_extras(_role(tool_results=True))

    def test_build_agent_reports_the_missing_extra_as_a_load_error(self, monkeypatch):
        def _missing():
            raise MissingExtraError("needs jev", extra="jev", pip_name="typesafe-sdk")

        monkeypatch.setattr("initrunner._compat.require_jev", _missing)
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            with pytest.raises(RoleLoadError) as exc:
                build_agent(_role(input=True))
        assert isinstance(exc.value.__cause__, MissingExtraError)

    def test_key_present_builds(self, monkeypatch):
        import initrunner.jev as jev

        monkeypatch.setattr(jev, "api_key", lambda: "ts_test")
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            agent = build_agent(_role(input=True, tool_results=True))
        assert agent is not None
