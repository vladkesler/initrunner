"""Tests for RunConfig schema and ephemeral path integration."""

from __future__ import annotations

from unittest.mock import patch

from initrunner.run_config import RunConfig


class TestRunConfigFields:
    def test_round_trips_base_url_api_key_env(self, tmp_path):
        """RunConfig serializes and deserializes base_url and api_key_env."""
        import yaml

        cfg = RunConfig(
            provider="openai",
            model="anthropic/claude-sonnet-4",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
        )
        data = cfg.model_dump(exclude_none=True)
        text = yaml.dump(data, default_flow_style=False)

        # Write and read back
        path = tmp_path / "run.yaml"
        path.write_text(text)
        loaded = yaml.safe_load(path.read_text())
        restored = RunConfig.model_validate(loaded)

        assert restored.base_url == "https://openrouter.ai/api/v1"
        assert restored.api_key_env == "OPENROUTER_API_KEY"
        assert restored.provider == "openai"
        assert restored.model == "anthropic/claude-sonnet-4"

    def test_defaults_to_none(self):
        """base_url and api_key_env default to None."""
        cfg = RunConfig()
        assert cfg.base_url is None
        assert cfg.api_key_env is None


class TestQuickChatHonorsEndpoint:
    def test_build_quick_chat_role_passes_base_url(self):
        """build_quick_chat_role_sync threads base_url and api_key_env to ModelConfig."""
        from initrunner.services.providers import build_quick_chat_role_sync

        with patch("initrunner.services.providers._load_env"):
            role, _prov, _mod = build_quick_chat_role_sync(
                provider="openai",
                model="anthropic/claude-sonnet-4",
                base_url="https://openrouter.ai/api/v1",
                api_key_env="OPENROUTER_API_KEY",
                with_memory=False,
            )

        assert role.spec.model is not None
        assert role.spec.model.base_url == "https://openrouter.ai/api/v1"
        assert role.spec.model.api_key_env == "OPENROUTER_API_KEY"
        assert role.spec.model.provider == "openai"


def _tool_types(role) -> list[str]:
    return [t.type for t in role.spec.tools]


class TestQuickChatToolContract:
    def test_none_defs_use_minimal(self):
        from initrunner.services.providers import build_quick_chat_role_sync

        with patch("initrunner.services.providers._load_env"):
            role, _, _ = build_quick_chat_role_sync(
                provider="openai",
                model="gpt-5-mini",
                tool_defs=None,
                with_memory=False,
            )

        assert _tool_types(role) == ["datetime", "web_reader"]
        assert role.spec.tool_search.enabled is False

    def test_empty_defs_attach_no_tools(self):
        from initrunner.services.providers import build_quick_chat_role_sync

        with patch("initrunner.services.providers._load_env"):
            role, _, _ = build_quick_chat_role_sync(
                provider="openai",
                model="gpt-5-mini",
                tool_defs=[],
                with_memory=False,
            )

        assert role.spec.tools == []
        assert role.spec.tool_search.enabled is False

    def test_all_enables_tool_search_with_minimal_pinned(self):
        from initrunner.services.providers import (
            TOOL_PROFILES,
            build_quick_chat_role_sync,
        )

        with (
            patch("initrunner.services.providers._load_env"),
            patch("initrunner.services.providers.check_tool_envs", return_value={}),
        ):
            role, _, _ = build_quick_chat_role_sync(
                provider="openai",
                model="gpt-5-mini",
                tool_defs=list(TOOL_PROFILES["all"]),
                with_memory=False,
            )

        types = _tool_types(role)
        assert "python" in types
        assert "shell" in types
        assert "datetime" in types
        from initrunner.agent.tools.registry import resolve_func_names

        assert role.spec.tool_search.enabled is True
        # Full catalog must not be always-available — only the minimal set.
        pinned = set(role.spec.tool_search.always_available)
        expected = set(resolve_func_names(list(TOOL_PROFILES["minimal"])))
        assert pinned == expected
        assert "run_python" not in pinned

    def test_minimal_plus_python_does_not_pin_python(self):
        from initrunner.agent.tools.registry import resolve_func_names
        from initrunner.services.providers import (
            EPHEMERAL_TOOL_DEFAULTS,
            TOOL_PROFILES,
            build_quick_chat_role_sync,
        )

        attached = [*TOOL_PROFILES["minimal"], EPHEMERAL_TOOL_DEFAULTS["python"]]
        with patch("initrunner.services.providers._load_env"):
            role, _, _ = build_quick_chat_role_sync(
                provider="openai",
                model="gpt-5-mini",
                tool_defs=attached,
                with_memory=False,
            )

        assert set(_tool_types(role)) == {"datetime", "web_reader", "python"}
        assert role.spec.tool_search.enabled is True
        assert set(role.spec.tool_search.always_available) == set(
            resolve_func_names(list(TOOL_PROFILES["minimal"]))
        )
        assert "run_python" not in role.spec.tool_search.always_available

    def test_skips_only_selected_tools_missing_env(self):
        from initrunner.services.providers import (
            EPHEMERAL_TOOL_DEFAULTS,
            build_quick_chat_role_sync,
        )

        with (
            patch("initrunner.services.providers._load_env"),
            patch(
                "initrunner.services.providers.check_tool_envs",
                return_value={"slack": ["SLACK_WEBHOOK_URL"]},
            ) as mock_check,
        ):
            role, _, _ = build_quick_chat_role_sync(
                provider="openai",
                model="gpt-5-mini",
                tool_defs=[EPHEMERAL_TOOL_DEFAULTS["slack"]],
                with_memory=False,
            )

        mock_check.assert_called_once()
        assert mock_check.call_args[0][0] == {"slack"}
        assert role.spec.tools == []
