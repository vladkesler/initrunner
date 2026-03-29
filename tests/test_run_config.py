"""Tests for RunConfig schema and ephemeral path integration."""

from __future__ import annotations

from unittest.mock import patch

from initrunner.cli.run_config import RunConfig


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
