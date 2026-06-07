"""Tests for the CLI ``new`` command."""

from __future__ import annotations

import re
import textwrap
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from initrunner.cli.main import app
from initrunner.services.agent_builder import PostCreateResult, TurnResult

runner = CliRunner()

_VALID_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: test-agent
      description: A test agent
    spec:
      role: You are a helpful assistant.
      model:
        provider: openai
        name: gpt-5-mini
      guardrails:
        timeout_seconds: 30
""")


def _mock_builder_session():
    """Create a mock BuilderSession that returns valid YAML."""
    from initrunner.services.agent_builder import TurnResult

    turn = TurnResult(
        explanation="Generated from your description.",
        yaml_text=_VALID_YAML,
        issues=[],
    )

    session = MagicMock()
    session.seed_blank.return_value = turn
    session.seed_template.return_value = turn
    session.seed_description.return_value = turn
    session.seed_from_file.return_value = turn
    session.seed_from_example.return_value = turn
    session.omitted_assets = []
    session.role = MagicMock()
    session.role.metadata.name = "test-agent"
    return session, turn


# ---------------------------------------------------------------------------
# Seed mode mutual exclusivity
# ---------------------------------------------------------------------------


class TestNewSeedModes:
    def test_multiple_seed_modes_errors(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "a chatbot", "--blank", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 1
        assert "at most one" in result.output.lower()

    def test_description_and_template_errors(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "a chatbot", "--template", "rag", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 1

    def test_description_and_from_errors(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "a chatbot", "--from", "hello-world", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Blank seed
# ---------------------------------------------------------------------------


class TestNewBlank:
    def test_blank_creates_file(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "--blank", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 0
        assert output.exists()
        content = output.read_text()
        assert "my-agent" in content
        assert "initrunner/v1" in content

    def test_blank_with_provider(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            [
                "new",
                "--blank",
                "--provider",
                "anthropic",
                "--output",
                str(output),
                "--no-refine",
            ],
        )
        assert result.exit_code == 0
        content = output.read_text()
        assert "anthropic" in content


# ---------------------------------------------------------------------------
# Template seed
# ---------------------------------------------------------------------------


class TestNewTemplate:
    def test_template_rag(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "--template", "rag", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 0
        content = output.read_text()
        assert "ingest" in content

    def test_template_daemon(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "--template", "daemon", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 0
        content = output.read_text()
        assert "triggers" in content

    def test_template_memory(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "--template", "memory", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 0
        content = output.read_text()
        assert "memory" in content

    def test_template_invalid(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "--template", "nonexistent", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# --no-refine
# ---------------------------------------------------------------------------


class TestNewNoRefine:
    def test_no_refine_skips_loop(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "--blank", "--output", str(output), "--no-refine"],
        )
        assert result.exit_code == 0
        assert output.exists()
        # Should show next steps
        assert "Next steps" in result.output


# ---------------------------------------------------------------------------
# Overwrite handling
# ---------------------------------------------------------------------------


class TestNewOverwrite:
    def test_refuses_overwrite_without_force(self, tmp_path):
        output = tmp_path / "role.yaml"
        output.write_text("existing")
        runner.invoke(
            app,
            ["new", "--blank", "--output", str(output), "--no-refine"],
            input="n\n",
        )
        # User said no to overwrite
        assert output.read_text() == "existing"

    def test_force_overwrites(self, tmp_path):
        output = tmp_path / "role.yaml"
        output.write_text("existing")
        result = runner.invoke(
            app,
            ["new", "--blank", "--output", str(output), "--no-refine", "--force"],
        )
        assert result.exit_code == 0
        assert output.read_text() != "existing"


# ---------------------------------------------------------------------------
# --list-templates
# ---------------------------------------------------------------------------

_ROLE_TEMPLATES = {"basic", "rag", "daemon", "memory", "ollama", "api", "telegram", "discord"}


class TestListTemplates:
    def test_list_templates_exits_zero(self):
        result = runner.invoke(app, ["new", "--list-templates"])
        assert result.exit_code == 0

    def test_list_templates_shows_all_role_templates(self):
        result = runner.invoke(app, ["new", "--list-templates"])
        for name in _ROLE_TEMPLATES:
            assert name in result.output

    def test_list_templates_excludes_non_role(self):
        result = runner.invoke(app, ["new", "--list-templates"])
        # blank is a separate flag; tool/skill are scaffolds
        assert "blank" not in result.output.lower().split()
        assert "tool" not in result.output.lower().split()
        assert "skill" not in result.output.lower().split()

    def test_list_templates_in_help(self):
        result = runner.invoke(app, ["new", "--help"])
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "--list-templates" in plain


# ---------------------------------------------------------------------------
# Command surface: init and create are gone, new is registered
# ---------------------------------------------------------------------------


class TestCommandSurface:
    def test_init_not_registered(self):
        result = runner.invoke(app, ["init"])
        # Should fail -- not a recognized command
        assert result.exit_code != 0

    def test_create_not_registered(self):
        result = runner.invoke(app, ["create", "some description"])
        assert result.exit_code != 0

    def test_new_is_registered(self):
        result = runner.invoke(app, ["new", "--help"])
        assert result.exit_code == 0
        assert "Create a new agent" in result.output

    def test_skill_new_registered(self):
        result = runner.invoke(app, ["skill", "new", "--help"])
        assert result.exit_code == 0
        assert "Scaffold" in result.output


# ---------------------------------------------------------------------------
# Zero-arg behavior
# ---------------------------------------------------------------------------


class TestZeroArg:
    def test_non_tty_shows_help(self):
        """Non-TTY (piped) should show help text."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_new_command_in_help(self):
        """The 'new' command should appear in help output."""
        result = runner.invoke(app, ["--help"])
        assert "new" in result.output

    def test_init_not_in_help(self):
        """The old 'init' command should not appear in help output."""
        result = runner.invoke(app, ["--help"])
        # Check for 'init' as a command, not as substring of other words
        lines = result.output.split("\n")
        command_lines = [line.strip() for line in lines if line.strip().startswith("init ")]
        assert len(command_lines) == 0

    def test_create_not_in_help(self):
        """The old 'create' command should not appear in help output."""
        result = runner.invoke(app, ["--help"])
        lines = result.output.split("\n")
        command_lines = [line.strip() for line in lines if line.strip().startswith("create ")]
        assert len(command_lines) == 0


# ---------------------------------------------------------------------------
# Provider/model resolution -- run.yaml precedence
# ---------------------------------------------------------------------------


class TestProviderResolution:
    """init new should respect run.yaml over env-var auto-detection."""

    def test_run_yaml_overrides_env_detection(self, tmp_path, monkeypatch):
        """run.yaml provider takes precedence over higher-priority env vars."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stale-key")
        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)

        # Patch detect_default_model to simulate run.yaml returning openai
        with patch(
            "initrunner.agent.loader.detect_default_model",
            return_value=("openai", "gpt-5-mini", None, None, "run_yaml"),
        ):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "--blank", "--output", str(output), "--no-refine"],
            )
        assert result.exit_code == 0
        content = output.read_text()
        assert "openai" in content

    def test_cli_flags_override_run_yaml(self, tmp_path, monkeypatch):
        """Explicit --provider flag overrides run.yaml."""
        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)

        with patch(
            "initrunner.agent.loader.detect_default_model",
            return_value=("openai", "gpt-5-mini", None, None, "run_yaml"),
        ):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                [
                    "new",
                    "--blank",
                    "--provider",
                    "anthropic",
                    "--output",
                    str(output),
                    "--no-refine",
                ],
            )
        assert result.exit_code == 0
        content = output.read_text()
        assert "anthropic" in content

    def test_base_url_injected_into_yaml(self, tmp_path, monkeypatch):
        """base_url from run.yaml is injected into generated YAML."""
        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)

        with patch(
            "initrunner.agent.loader.detect_default_model",
            return_value=(
                "openai",
                "gpt-5-mini",
                "https://openrouter.ai/api/v1",
                "OPENROUTER_API_KEY",
                "run_yaml",
            ),
        ):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "--blank", "--output", str(output), "--no-refine"],
            )
        assert result.exit_code == 0
        content = output.read_text()
        assert "https://openrouter.ai/api/v1" in content
        assert "OPENROUTER_API_KEY" in content


# ---------------------------------------------------------------------------
# 401 error handling
# ---------------------------------------------------------------------------


class TestAuthErrorHandling:
    """401 errors should show clear guidance, not raw tracebacks."""

    def test_seed_401_shows_auth_message(self, tmp_path, monkeypatch):
        """A 401 during seed shows authentication guidance."""
        from pydantic_ai.exceptions import ModelHTTPError

        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)

        session, _ = _mock_builder_session()
        session.seed_description.side_effect = ModelHTTPError(
            status_code=401, model_name="test-model", body=None
        )

        with (
            patch("initrunner.services.agent_builder.BuilderSession", return_value=session),
            patch(
                "initrunner.agent.loader.detect_default_model",
                return_value=("openai", "gpt-5-mini", None, None, "run_yaml"),
            ),
        ):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "a chatbot", "--output", str(output), "--no-refine"],
            )
        assert result.exit_code == 1
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "authentication failed" in plain.lower()
        assert "initrunner setup" in plain

    def test_seed_other_http_error_shows_status(self, tmp_path, monkeypatch):
        """Non-401 HTTP errors show the status code."""
        from pydantic_ai.exceptions import ModelHTTPError

        monkeypatch.delenv("INITRUNNER_MODEL", raising=False)

        session, _ = _mock_builder_session()
        session.seed_description.side_effect = ModelHTTPError(
            status_code=429, model_name="test-model", body=None
        )

        with (
            patch("initrunner.services.agent_builder.BuilderSession", return_value=session),
            patch(
                "initrunner.agent.loader.detect_default_model",
                return_value=("openai", "gpt-5-mini", None, None, "run_yaml"),
            ),
        ):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "a chatbot", "--output", str(output), "--no-refine"],
            )
        assert result.exit_code == 1
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "429" in plain


# ---------------------------------------------------------------------------
# Post-creation "Run it now?" offer (--run / --no-run)
# ---------------------------------------------------------------------------


def _mock_session_for_offer(
    *,
    test_prompt: str | None,
    valid: bool = True,
    triggers=None,
    ingest=None,
):
    """Build a mocked BuilderSession that produces a controlled TurnResult/PostCreateResult.

    Used by the post-creation offer tests so we don't depend on the real
    blank-template flow when we need to simulate a tailored test_prompt or a
    role with triggers/ingest.
    """
    turn = TurnResult(
        explanation="Generated.",
        yaml_text=_VALID_YAML,
        issues=[],
        test_prompt=test_prompt,
    )

    role = MagicMock()
    role.metadata.name = "test-agent"
    role.spec.triggers = triggers
    role.spec.ingest = ingest

    session = MagicMock()
    session.seed_blank.return_value = turn
    session.seed_template.return_value = turn
    session.seed_description.return_value = turn
    session.seed_from_file.return_value = turn
    session.seed_from_example.return_value = turn
    session.omitted_assets = []
    session.import_warnings = []
    session.yaml_text = _VALID_YAML
    session.role = role

    def _save(path, force=False):
        # Materialize the file so existence checks downstream don't surprise us.
        path.write_text(_VALID_YAML)
        return PostCreateResult(
            yaml_path=path,
            valid=valid,
            issues=[],
            next_steps=[f"initrunner run {path} -p 'hello'"],
            omitted_assets=[],
        )

    session.save.side_effect = _save
    return session


class TestPostCreateRunOffer:
    """Coverage for the new ``--run``/``--no-run`` flow on ``initrunner new``."""

    def test_run_and_no_run_are_mutually_exclusive(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            [
                "new",
                "--blank",
                "--output",
                str(output),
                "--no-refine",
                "--run",
                "hello",
                "--no-run",
            ],
        )
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output.lower()

    def test_explicit_run_dispatches_regardless_of_tty(self, tmp_path, monkeypatch):
        """`--run TEXT` is the scripting path: bypasses TTY and tailored-prompt gates."""
        calls: dict = {}

        def fake_run_agent(**kwargs):
            calls.update(kwargs)

        monkeypatch.setattr("initrunner.cli._run_agent._run_agent", fake_run_agent)
        # Prove the explicit path bypasses the TTY check.
        monkeypatch.setattr("initrunner.cli.new_cmd._stdin_is_interactive", lambda: False)

        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            [
                "new",
                "--blank",
                "--output",
                str(output),
                "--no-refine",
                "--run",
                "what is 2+2",
            ],
        )
        assert result.exit_code == 0, result.output
        assert calls.get("prompt") == "what is 2+2"
        assert calls.get("role_file") == output
        assert calls.get("output_format") == "auto"
        assert calls.get("interactive") is False
        assert calls.get("autonomous") is False

    def test_no_run_skips_dispatch(self, tmp_path, monkeypatch):
        called = False

        def fake_run_agent(**kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr("initrunner.cli._run_agent._run_agent", fake_run_agent)
        monkeypatch.setattr("initrunner.cli.new_cmd._stdin_is_interactive", lambda: True)

        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            ["new", "--blank", "--output", str(output), "--no-refine", "--no-run"],
        )
        assert result.exit_code == 0, result.output
        assert called is False
        assert "Run it now" not in result.output

    def test_interactive_accept_dispatches_with_tailored_prompt(self, tmp_path, monkeypatch):
        calls: dict = {}

        def fake_run_agent(**kwargs):
            calls.update(kwargs)

        monkeypatch.setattr("initrunner.cli._run_agent._run_agent", fake_run_agent)
        monkeypatch.setattr("initrunner.cli.new_cmd._stdin_is_interactive", lambda: True)

        session = _mock_session_for_offer(test_prompt="say hi to the user")
        with patch("initrunner.services.agent_builder.BuilderSession", return_value=session):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "--blank", "--output", str(output), "--no-refine"],
                input="y\n",
            )
        assert result.exit_code == 0, result.output
        assert "Run it now" in result.output
        assert "say hi to the user" in result.output
        assert calls.get("prompt") == "say hi to the user"
        assert calls.get("role_file") == output

    def test_interactive_decline_skips_dispatch(self, tmp_path, monkeypatch):
        called = False

        def fake_run_agent(**kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr("initrunner.cli._run_agent._run_agent", fake_run_agent)
        monkeypatch.setattr("initrunner.cli.new_cmd._stdin_is_interactive", lambda: True)

        session = _mock_session_for_offer(test_prompt="say hi")
        with patch("initrunner.services.agent_builder.BuilderSession", return_value=session):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "--blank", "--output", str(output), "--no-refine"],
                input="n\n",
            )
        assert result.exit_code == 0, result.output
        assert "Run it now" in result.output
        assert called is False

    def test_non_interactive_stdin_skips_offer(self, tmp_path, monkeypatch):
        called = False

        def fake_run_agent(**kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr("initrunner.cli._run_agent._run_agent", fake_run_agent)
        monkeypatch.setattr("initrunner.cli.new_cmd._stdin_is_interactive", lambda: False)

        session = _mock_session_for_offer(test_prompt="say hi")
        with patch("initrunner.services.agent_builder.BuilderSession", return_value=session):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "--blank", "--output", str(output), "--no-refine"],
            )
        assert result.exit_code == 0, result.output
        assert "Run it now" not in result.output
        assert called is False

    def test_no_tailored_prompt_skips_offer(self, tmp_path, monkeypatch):
        """Blank seed has no LLM call -> no tailored prompt -> no offer."""
        called = False

        def fake_run_agent(**kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr("initrunner.cli._run_agent._run_agent", fake_run_agent)
        monkeypatch.setattr("initrunner.cli.new_cmd._stdin_is_interactive", lambda: True)

        output = tmp_path / "role.yaml"
        # Real blank flow -- no mocking. test_prompt is None for blank seeds.
        result = runner.invoke(
            app,
            ["new", "--blank", "--output", str(output), "--no-refine"],
            input="y\n",
        )
        assert result.exit_code == 0, result.output
        assert "Run it now" not in result.output
        assert called is False

    def test_role_with_triggers_skips_offer(self, tmp_path, monkeypatch):
        called = False

        def fake_run_agent(**kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr("initrunner.cli._run_agent._run_agent", fake_run_agent)
        monkeypatch.setattr("initrunner.cli.new_cmd._stdin_is_interactive", lambda: True)

        session = _mock_session_for_offer(
            test_prompt="say hi",
            triggers=[MagicMock()],  # Truthy non-empty list.
        )
        with patch("initrunner.services.agent_builder.BuilderSession", return_value=session):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "--blank", "--output", str(output), "--no-refine"],
                input="y\n",
            )
        assert result.exit_code == 0, result.output
        assert "Run it now" not in result.output
        assert called is False

    def test_role_with_ingest_skips_offer(self, tmp_path, monkeypatch):
        called = False

        def fake_run_agent(**kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr("initrunner.cli._run_agent._run_agent", fake_run_agent)
        monkeypatch.setattr("initrunner.cli.new_cmd._stdin_is_interactive", lambda: True)

        session = _mock_session_for_offer(
            test_prompt="say hi",
            ingest=MagicMock(),  # Truthy.
        )
        with patch("initrunner.services.agent_builder.BuilderSession", return_value=session):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "--blank", "--output", str(output), "--no-refine"],
                input="y\n",
            )
        assert result.exit_code == 0, result.output
        assert "Run it now" not in result.output
        assert called is False

    def test_invalid_save_skips_offer(self, tmp_path, monkeypatch):
        called = False

        def fake_run_agent(**kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr("initrunner.cli._run_agent._run_agent", fake_run_agent)
        monkeypatch.setattr("initrunner.cli.new_cmd._stdin_is_interactive", lambda: True)

        session = _mock_session_for_offer(test_prompt="say hi", valid=False)
        with patch("initrunner.services.agent_builder.BuilderSession", return_value=session):
            output = tmp_path / "role.yaml"
            result = runner.invoke(
                app,
                ["new", "--blank", "--output", str(output), "--no-refine"],
                input="y\n",
            )
        assert result.exit_code == 0, result.output
        assert "Run it now" not in result.output
        assert called is False


# ---------------------------------------------------------------------------
# Offline form + guided menu + no-AI guard
# ---------------------------------------------------------------------------


def _full_mock_session(test_prompt=None, valid=True):
    """Mock BuilderSession supporting all seed paths + a real save() result."""
    turn = TurnResult(
        explanation="Built.", yaml_text=_VALID_YAML, issues=[], test_prompt=test_prompt
    )
    role = MagicMock()
    role.metadata.name = "test-agent"
    role.kind = "Agent"
    role.spec.triggers = None
    role.spec.ingest = None

    session = MagicMock()
    for m in (
        "seed_blank",
        "seed_template",
        "seed_description",
        "seed_from_example",
        "seed_yaml",
        "seed_from_agent_spec",
    ):
        getattr(session, m).return_value = turn
    session.current_turn.return_value = turn
    session.omitted_assets = []
    session.import_warnings = []
    session.issues = []
    session.yaml_text = _VALID_YAML
    session.role = role

    def _save(path, force=False):
        path.write_text(_VALID_YAML)
        return PostCreateResult(
            yaml_path=path,
            valid=valid,
            issues=[],
            next_steps=[f"initrunner validate {path}"],
            omitted_assets=[],
        )

    session.save.side_effect = _save
    return session


_DETECT = ("openai", "gpt-5-mini", None, None, "test")


class TestOfflineAndMenu:
    def test_offline_and_blank_mutually_exclusive(self, tmp_path):
        result = runner.invoke(
            app, ["new", "--offline", "--blank", "--output", str(tmp_path / "r.yaml")]
        )
        assert result.exit_code == 1
        assert "at most one" in result.output.lower()

    def test_offline_requires_tty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("initrunner.cli.new_cmd._stdin_is_interactive", lambda: False)
        result = runner.invoke(app, ["new", "--offline", "--output", str(tmp_path / "r.yaml")])
        assert result.exit_code == 1
        assert "interactive terminal" in result.output.lower()

    def test_offline_builds_via_form_without_llm(self, tmp_path, monkeypatch):
        session = _full_mock_session()
        monkeypatch.setattr("initrunner.cli.new_cmd._stdin_is_interactive", lambda: True)
        monkeypatch.setattr(
            "initrunner.cli._helpers._display.prompt_model_selection",
            lambda *a, **k: "gpt-5-mini",
        )
        out = tmp_path / "role.yaml"
        # name, desc, sysprompt, editor?, use-provider?, tools, memory?, rag?, trigger?
        form = "off-bot\n\n\nn\ny\n\nn\nn\nn\n"
        with (
            patch("initrunner.services.agent_builder.BuilderSession", return_value=session),
            patch("initrunner.agent.loader.detect_default_model", return_value=_DETECT),
        ):
            result = runner.invoke(
                app, ["new", "--offline", "--no-refine", "--output", str(out)], input=form
            )
        assert result.exit_code == 0, result.output
        assert session.seed_yaml.called
        assert not session.seed_description.called
        assert out.exists()

    def test_menu_routes_to_template(self, tmp_path, monkeypatch):
        session = _full_mock_session()
        monkeypatch.setattr("initrunner.cli.new_cmd._stdin_is_interactive", lambda: True)
        out = tmp_path / "role.yaml"
        with (
            patch("initrunner.services.agent_builder.BuilderSession", return_value=session),
            patch("initrunner.agent.loader.detect_default_model", return_value=_DETECT),
        ):
            # menu "2" (template) -> template "1" (basic)
            result = runner.invoke(
                app, ["new", "--no-refine", "--output", str(out)], input="2\n1\n"
            )
        assert result.exit_code == 0, result.output
        session.seed_template.assert_called_once()
        assert session.seed_template.call_args[0][0] == "basic"
        assert not session.seed_description.called

    def test_offline_plain_text_refine_blocked_without_key(self, tmp_path, monkeypatch):
        session = _full_mock_session()
        monkeypatch.setattr("initrunner.cli.new_cmd._stdin_is_interactive", lambda: True)
        monkeypatch.setattr("initrunner.cli.new_cmd._key_available", lambda *a, **k: False)
        monkeypatch.setattr(
            "initrunner.cli._helpers._display.prompt_model_selection",
            lambda *a, **k: "gpt-5-mini",
        )
        out = tmp_path / "role.yaml"
        form = "off-bot\n\n\nn\ny\n\nn\nn\nn\n"
        refine = "add a web tool\n\n"  # plain text -> blocked; empty -> save
        with (
            patch("initrunner.services.agent_builder.BuilderSession", return_value=session),
            patch("initrunner.agent.loader.detect_default_model", return_value=_DETECT),
        ):
            result = runner.invoke(
                app, ["new", "--offline", "--no-run", "--output", str(out)], input=form + refine
            )
        assert result.exit_code == 0, result.output
        assert not session.refine.called
        assert "no api key configured for ai refinement" in result.output.lower()


# ---------------------------------------------------------------------------
# Refinement-loop command handlers (direct, no CliRunner)
# ---------------------------------------------------------------------------


def _loop_ctx(issues=None, role_kind="Agent"):
    from initrunner.cli.new_cmd import _LoopCtx

    session = MagicMock()
    session.yaml_text = _VALID_YAML
    session.issues = issues if issues is not None else []
    role = MagicMock()
    role.kind = role_kind
    role.metadata.name = "x"
    role.spec.tools = []
    session.role = role
    return _LoopCtx(session, "openai", "gpt-5-mini", None, None), session


class TestLoopCommands:
    def test_save_and_quit_signals(self):
        from initrunner.cli.new_cmd import _CMD_QUIT, _CMD_SAVE, _handle_command

        ctx, _ = _loop_ctx()
        assert _handle_command(":save", ctx) == _CMD_SAVE
        assert _handle_command(":quit", ctx) == _CMD_QUIT

    def test_unknown_command(self, capsys):
        from initrunner.cli.new_cmd import _CMD_CONTINUE, _handle_command

        ctx, _ = _loop_ctx()
        assert _handle_command(":bogus", ctx) == _CMD_CONTINUE
        assert "unknown command" in capsys.readouterr().out.lower()

    def test_help_lists_all_commands(self, capsys):
        from initrunner.cli.new_cmd import _handle_command

        ctx, _ = _loop_ctx()
        _handle_command(":help", ctx)
        out = capsys.readouterr().out
        for usage in (":yaml", ":validate", ":explain", ":tools", ":diff", ":model", ":undo"):
            assert usage in out

    def test_help_alias_question_mark(self, capsys):
        from initrunner.cli.new_cmd import _handle_command

        ctx, _ = _loop_ctx()
        _handle_command("?", ctx)
        assert ":save" in capsys.readouterr().out

    def test_model_with_arg_is_deterministic(self):
        from initrunner.cli.new_cmd import _CMD_CONTINUE, _handle_command

        ctx, session = _loop_ctx()
        with patch(
            "initrunner.services.agent_builder.rewrite_model_block", return_value="NEW_YAML"
        ) as rw:
            assert _handle_command(":model openai:gpt-5-nano", ctx) == _CMD_CONTINUE
        rw.assert_called_once()
        session.checkpoint.assert_called_once()
        assert session.yaml_text == "NEW_YAML"

    def test_model_bad_arg_no_checkpoint(self, capsys):
        from initrunner.cli.new_cmd import _handle_command

        ctx, session = _loop_ctx()
        _handle_command(":model openai", ctx)  # missing :name
        session.checkpoint.assert_not_called()
        assert "usage" in capsys.readouterr().out.lower()

    def test_undo_calls_session(self):
        from initrunner.cli.new_cmd import _handle_command

        ctx, session = _loop_ctx()
        session.undo.return_value = True
        _handle_command(":undo", ctx)
        session.undo.assert_called_once()

    def test_validate_uses_shared_panel(self):
        from initrunner.cli.new_cmd import _handle_command
        from initrunner.services.agent_builder import ValidationIssue

        ctx, session = _loop_ctx(
            issues=[ValidationIssue(field="x", message="m", severity="warning")]
        )
        with patch(
            "initrunner.cli._validation_panel.render_validation_panel", return_value="PANEL"
        ) as rv:
            _handle_command(":validate", ctx)
        rv.assert_called_once()
        assert rv.call_args[0][2] == session.issues

    def test_explain_guards_invalid_yaml(self, capsys):
        from initrunner.cli.new_cmd import _handle_command

        ctx, session = _loop_ctx()
        session.role = None
        _handle_command(":explain", ctx)
        assert "fix validation errors" in capsys.readouterr().out.lower()
