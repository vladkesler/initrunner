"""Tests for inline API key prompt during ``initrunner run``.

When a user runs an agent without an API key configured, the CLI now
prompts inline (in interactive sessions only), persists the key, and
retries the run instead of forcing a round-trip through
``initrunner setup``.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
import typer

from initrunner.agent.loader import MissingApiKeyError, RoleLoadError
from initrunner.cli._helpers import load_and_build_or_exit, prompt_inline_api_key


@pytest.fixture()
def clean_env(monkeypatch, tmp_path):
    """Remove provider API keys and point INITRUNNER_HOME at a temp dir."""
    for var in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "CO_API_KEY",
        "XAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path / "home"))
    from initrunner.config import get_home_dir

    get_home_dir.cache_clear()
    yield tmp_path
    get_home_dir.cache_clear()


@pytest.fixture()
def fake_tty(monkeypatch):
    """Make stdin and stdout pretend to be TTYs for the prompt gate."""
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)


class TestSubclass:
    def test_missing_api_key_error_subclasses_role_load_error(self):
        # Existing ``except RoleLoadError`` sites must keep working.
        assert issubclass(MissingApiKeyError, RoleLoadError)

    def test_carries_env_var_and_provider(self):
        e = MissingApiKeyError(env_var="OPENAI_API_KEY", provider="openai", message="boom")
        assert e.env_var == "OPENAI_API_KEY"
        assert e.provider == "openai"
        assert "boom" in str(e)


class TestPromptInlineApiKey:
    def test_non_tty_returns_false_without_prompting(self, clean_env, monkeypatch):
        import sys

        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

        with patch("rich.prompt.Prompt.ask") as ask:
            result = prompt_inline_api_key("OPENAI_API_KEY", "openai")

        assert result is False
        ask.assert_not_called()
        assert "OPENAI_API_KEY" not in os.environ

    def test_non_tty_stdout_returns_false(self, clean_env, monkeypatch):
        import sys

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

        with patch("rich.prompt.Prompt.ask") as ask:
            result = prompt_inline_api_key("OPENAI_API_KEY", "openai")

        assert result is False
        ask.assert_not_called()

    def test_tty_happy_path_sets_env_and_persists(self, clean_env, fake_tty):
        with patch("rich.prompt.Prompt.ask", return_value="sk-test123"):
            try:
                result = prompt_inline_api_key("OPENAI_API_KEY", "openai")
                assert result is True
                assert os.environ["OPENAI_API_KEY"] == "sk-test123"
                env_file = clean_env / "home" / ".env"
                assert env_file.is_file()
                assert "sk-test123" in env_file.read_text()
            finally:
                os.environ.pop("OPENAI_API_KEY", None)

    def test_empty_input_returns_false(self, clean_env, fake_tty):
        with patch("rich.prompt.Prompt.ask", return_value=""):
            result = prompt_inline_api_key("OPENAI_API_KEY", "openai")
        assert result is False
        assert "OPENAI_API_KEY" not in os.environ

    def test_whitespace_input_returns_false(self, clean_env, fake_tty):
        with patch("rich.prompt.Prompt.ask", return_value="   \t\n"):
            result = prompt_inline_api_key("OPENAI_API_KEY", "openai")
        assert result is False
        assert "OPENAI_API_KEY" not in os.environ

    def test_keyboard_interrupt_returns_false(self, clean_env, fake_tty):
        with patch("rich.prompt.Prompt.ask", side_effect=KeyboardInterrupt):
            result = prompt_inline_api_key("OPENAI_API_KEY", "openai")
        assert result is False
        assert "OPENAI_API_KEY" not in os.environ

    def test_eof_returns_false(self, clean_env, fake_tty):
        with patch("rich.prompt.Prompt.ask", side_effect=EOFError):
            result = prompt_inline_api_key("OPENAI_API_KEY", "openai")
        assert result is False
        assert "OPENAI_API_KEY" not in os.environ

    def test_persist_failure_still_sets_env_var(self, clean_env, fake_tty):
        # save_env_key returns None when disk write fails. The in-process
        # env var must still be set so the immediate retry can succeed.
        with (
            patch("rich.prompt.Prompt.ask", return_value="sk-test"),
            patch("initrunner.services.setup.save_env_key", return_value=None),
        ):
            try:
                result = prompt_inline_api_key("OPENAI_API_KEY", "openai")
                assert result is True
                assert os.environ["OPENAI_API_KEY"] == "sk-test"
            finally:
                os.environ.pop("OPENAI_API_KEY", None)


class TestLoadAndBuildOrExitRetry:
    """End-to-end retry behavior of ``load_and_build_or_exit``.

    These tests mock ``build_agent_sync`` directly so they don't depend on
    PydanticAI being able to construct a real model client.
    """

    @pytest.fixture()
    def role_path(self, tmp_path):
        # Real file so resolve_role_path passes through unchanged.
        # Content is irrelevant since build_agent_sync is mocked.
        p = tmp_path / "role.yaml"
        p.write_text("dummy: true\n")
        return p

    def test_retry_succeeds_after_inline_prompt(self, role_path, clean_env, fake_tty):
        sentinel = (object(), object())
        calls = {"n": 0}

        def fake_build(path, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise MissingApiKeyError(
                    env_var="OPENAI_API_KEY",
                    provider="openai",
                    message="API key not found",
                )
            return sentinel

        with (
            patch(
                "initrunner.services.execution.build_agent_sync",
                side_effect=fake_build,
            ),
            patch("rich.prompt.Prompt.ask", return_value="sk-test"),
        ):
            try:
                result = load_and_build_or_exit(role_path)
            finally:
                os.environ.pop("OPENAI_API_KEY", None)

        assert result is sentinel
        assert calls["n"] == 2

    def test_non_tty_skips_prompt_and_exits(self, role_path, clean_env, monkeypatch):
        import sys

        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

        def fake_build(path, **kwargs):
            raise MissingApiKeyError(
                env_var="OPENAI_API_KEY",
                provider="openai",
                message="API key not found",
            )

        with (
            patch(
                "initrunner.services.execution.build_agent_sync",
                side_effect=fake_build,
            ),
            patch("rich.prompt.Prompt.ask") as ask,
            pytest.raises(typer.Exit),
        ):
            load_and_build_or_exit(role_path)

        ask.assert_not_called()

    def test_declined_prompt_exits(self, role_path, clean_env, fake_tty):
        def fake_build(path, **kwargs):
            raise MissingApiKeyError(
                env_var="OPENAI_API_KEY",
                provider="openai",
                message="API key not found",
            )

        with (
            patch(
                "initrunner.services.execution.build_agent_sync",
                side_effect=fake_build,
            ),
            patch("rich.prompt.Prompt.ask", return_value=""),
            pytest.raises(typer.Exit),
        ):
            load_and_build_or_exit(role_path)

    def test_post_prompt_failure_exits_without_third_attempt(self, role_path, clean_env, fake_tty):
        # Both attempts raise -- the second one must exit, not retry again.
        calls = {"n": 0}

        def fake_build(path, **kwargs):
            calls["n"] += 1
            raise MissingApiKeyError(
                env_var="OPENAI_API_KEY",
                provider="openai",
                message="still missing",
            )

        with (
            patch(
                "initrunner.services.execution.build_agent_sync",
                side_effect=fake_build,
            ),
            patch("rich.prompt.Prompt.ask", return_value="sk-test"),
            pytest.raises(typer.Exit),
        ):
            try:
                load_and_build_or_exit(role_path)
            finally:
                os.environ.pop("OPENAI_API_KEY", None)

        assert calls["n"] == 2

    def test_non_key_role_load_error_passes_through(self, role_path, clean_env, fake_tty):
        # A plain RoleLoadError (e.g. YAML parse failure) must NOT trigger
        # the inline prompt -- it should hit the existing error path with
        # the validate hint.
        def fake_build(path, **kwargs):
            raise RoleLoadError("YAML parse failure")

        with (
            patch(
                "initrunner.services.execution.build_agent_sync",
                side_effect=fake_build,
            ),
            patch("rich.prompt.Prompt.ask") as ask,
            pytest.raises(typer.Exit),
        ):
            load_and_build_or_exit(role_path)

        ask.assert_not_called()
