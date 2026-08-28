"""How a core install behaves when a role asks for an extra it does not have.

The contract: the YAML still validates (schemas are always registered), and
the failure happens at load time with the install command attached, never
half-way through a run. Every test here masks the optional module, so it runs
identically whether or not the extras are installed.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from initrunner._compat import MissingExtraError
from initrunner.agent.loader import RoleLoadError, build_agent
from initrunner.agent.schema.ingestion import IngestConfig
from initrunner.agent.schema.memory import MemoryConfig
from initrunner.agent.schema.tools import McpToolConfig, WebScraperToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, get_builder, get_tool_types
from tests.conftest import make_role

VECTOR_HINT = "'lancedb' is required: uv pip install initrunner[vector]"


@pytest.fixture
def no_fastmcp(monkeypatch):
    """Make ``import fastmcp`` fail, extra installed or not."""
    monkeypatch.setitem(sys.modules, "fastmcp", None)


@pytest.fixture
def no_lancedb(monkeypatch):
    """Make ``import lancedb`` fail, extra installed or not."""
    monkeypatch.setitem(sys.modules, "lancedb", None)


# ---------------------------------------------------------------------------
# Registration survives a missing extra
# ---------------------------------------------------------------------------


class TestMcpStaysRegistered:
    def test_config_class_is_registered(self, no_fastmcp):
        assert get_tool_types()["mcp"] is McpToolConfig

    def test_builder_is_registered(self, no_fastmcp):
        assert get_builder("mcp") is not None

    def test_role_yaml_still_validates(self, no_fastmcp, tmp_path):
        from initrunner.agent.loader import load_role

        path = tmp_path / "agent.yaml"
        path.write_text(
            "name: mcp-user\n"
            "prompt: You use MCP.\n"
            "model:\n"
            "  provider: openai\n"
            "  name: gpt-4o-mini\n"
            "tools:\n"
            "  - type: mcp\n"
            "    command: echo\n"
        )
        role = load_role(path)
        assert role.spec.tools[0].type == "mcp"

    def test_builder_raises_with_the_install_hint(self, no_fastmcp):
        builder = get_builder("mcp")
        ctx = ToolBuildContext(role=make_role())
        with pytest.raises(MissingExtraError, match=r"initrunner\[mcp\]"):
            builder(McpToolConfig(command="echo"), ctx)


# ---------------------------------------------------------------------------
# The failure lands at build time, as a RoleLoadError
# ---------------------------------------------------------------------------


class TestBuildAgentFailsEarly:
    def test_mcp_tool(self, no_fastmcp):
        role = make_role(tools=[McpToolConfig(command="echo")])
        with pytest.raises(RoleLoadError, match=r"initrunner\[mcp\]"):
            build_agent(role)

    def test_native_mcp_capability(self, no_fastmcp):
        role = make_role(capabilities=[{"MCP": {"command": "echo"}}])
        with pytest.raises(RoleLoadError, match=r"initrunner\[mcp\]"):
            build_agent(role)

    def test_memory_block(self, no_lancedb):
        role = make_role(memory=MemoryConfig())
        with pytest.raises(RoleLoadError, match=r"initrunner\[vector\]"):
            build_agent(role)

    def test_ingest_block(self, no_lancedb):
        role = make_role(ingest=IngestConfig(sources=["./docs"]))
        with pytest.raises(RoleLoadError, match=r"initrunner\[vector\]"):
            build_agent(role)

    def test_web_scraper_tool(self, no_lancedb):
        role = make_role(tools=[WebScraperToolConfig()])
        with pytest.raises(RoleLoadError, match=r"initrunner\[vector\]"):
            build_agent(role)

    def test_plain_role_still_builds(self, no_fastmcp, no_lancedb, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        agent = build_agent(make_role())
        assert agent is not None

    def test_cause_is_preserved(self, no_lancedb):
        """The CLI reads __cause__ to know not to suggest 'initrunner validate'."""
        role = make_role(memory=MemoryConfig())
        with pytest.raises(RoleLoadError) as exc:
            build_agent(role)
        assert isinstance(exc.value.__cause__, MissingExtraError)


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------


class TestStoreFactoryGate:
    def test_memory_store(self, no_lancedb, tmp_path):
        from initrunner.stores.factory import create_memory_store

        with pytest.raises(MissingExtraError, match=r"initrunner\[vector\]"):
            create_memory_store(db_path=tmp_path / "mem.lance")

    def test_document_store(self, no_lancedb, tmp_path):
        from initrunner.stores.factory import create_document_store

        with pytest.raises(MissingExtraError, match=r"initrunner\[vector\]"):
            create_document_store(db_path=tmp_path / "docs.lance")


# ---------------------------------------------------------------------------
# CLI surfaces
# ---------------------------------------------------------------------------


class TestMcpCommands:
    @pytest.mark.parametrize(
        "args",
        [
            ["list-tools", "agent.yaml"],
            ["serve", "agent.yaml"],
            ["toolkit"],
            ["browser"],
        ],
    )
    def test_exit_1_with_the_install_hint(self, no_fastmcp, args):
        from initrunner.cli.mcp_cmd import app

        result = CliRunner().invoke(app, args)
        assert result.exit_code == 1
        assert "initrunner[mcp]" in result.output

    def test_browser_console_script_exits_cleanly(self, no_fastmcp, capsys):
        from initrunner.mcp.browser import main

        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        assert "initrunner[mcp]" in capsys.readouterr().err


class TestTheHintSurvivesRichMarkup:
    """``initrunner[vector]`` is markup to Rich, and the bare package name is
    the one the user already has. Every path that prints a hint escapes it."""

    def test_print_error_escapes_markup(self, capsys):
        from initrunner.cli._helpers import print_error

        print_error(MissingExtraError(VECTOR_HINT))

        assert "initrunner[vector]" in " ".join(capsys.readouterr().out.split())

    def test_a_missing_extra_names_the_extra_on_the_run_path(self, no_lancedb, tmp_path):
        """The whole point of the gate is the install command in the message."""
        from initrunner.cli.main import app

        role = tmp_path / "notes.yaml"
        role.write_text(
            "name: notes\ndescription: d\nprompt: p\nmodel: openai:gpt-5-mini\n"
            "memory:\n  enabled: true\n"
        )

        result = CliRunner().invoke(app, ["run", str(role), "-p", "hi", "--no-audit"])

        assert result.exit_code == 1
        assert "initrunner[vector]" in " ".join(result.output.split())


class TestMissingExtraIsReportedOnce:
    def test_app_entry_prints_the_hint_instead_of_a_traceback(self, monkeypatch, capsys):
        """Any command can raise MissingExtraError; app_entry renders all of them."""
        from initrunner import telemetry
        from initrunner.cli import main as cli_main

        def _boom():
            raise MissingExtraError(VECTOR_HINT)

        monkeypatch.setattr(cli_main, "app", _boom)
        monkeypatch.setattr(telemetry, "record_command", lambda **kwargs: None)

        with pytest.raises(SystemExit) as exc:
            cli_main.app_entry()
        assert exc.value.code == 1
        assert "initrunner[vector]" in capsys.readouterr().out


class TestEphemeralModeReportsAMissingExtra:
    """``initrunner run`` with no role file turns persistent memory on, which
    needs the vector extra. It fails at load like the role-file path does, and
    names the flag that runs without memory."""

    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch, tmp_path):
        # Detection prefers Anthropic, and that SDK is an extra; pin the
        # provider to the one in core so the vector gate is what fires.
        for var in (
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "CO_API_KEY",
            "XAI_API_KEY",
            "INITRUNNER_MODEL",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        # Keep the developer's real ~/.initrunner/run.yaml and .env out of it.
        monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path / "home"))

    def test_one_shot_names_the_extra_and_the_flag(self, no_lancedb):
        from initrunner.cli.main import app

        result = CliRunner().invoke(app, ["run", "-p", "hi", "--no-audit"])

        flat = " ".join(result.output.split())
        assert result.exit_code == 1
        assert "initrunner[vector]" in flat
        assert "--no-memory" in flat

    def test_interactive_path_reports_the_same_way(self, no_lancedb):
        """The REPL path reports a missing extra like the one-shot path does."""
        from initrunner.cli.main import app

        result = CliRunner().invoke(app, ["run", "-i", "--no-audit"])

        flat = " ".join(result.output.split())
        assert result.exit_code == 1
        assert "initrunner[vector]" in flat
        assert "--no-memory" in flat

    def test_ingest_needs_the_extra_whatever_memory_does(self, no_lancedb, tmp_path):
        """Turning memory off would not help, so the flag is not offered."""
        from initrunner.cli.main import app

        result = CliRunner().invoke(
            app, ["run", "-p", "hi", "--ingest", str(tmp_path / "docs"), "--no-audit"]
        )

        flat = " ".join(result.output.split())
        assert result.exit_code == 1
        assert "initrunner[vector]" in flat
        assert "--no-memory" not in flat

    def test_no_memory_runs_on_a_core_install(self, no_lancedb):
        """The escape hatch the hint advertises has to work."""
        from initrunner.cli.main import app

        with patch("initrunner.runner.run_single") as run_single:
            result = CliRunner().invoke(app, ["run", "-p", "hi", "--no-memory", "--no-audit"])

        assert result.exit_code == 0, result.output
        run_single.assert_called_once()


# ---------------------------------------------------------------------------
# Offering to install what is missing
# ---------------------------------------------------------------------------


@pytest.fixture
def no_ddgs(monkeypatch):
    """Make ``import ddgs`` fail, extra installed or not."""
    monkeypatch.setitem(sys.modules, "ddgs", None)


@pytest.fixture
def no_webview(monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", None)


@pytest.fixture
def installable(monkeypatch, tmp_path):
    """A uv-tool install whose receipt this machine knows how to rebuild."""
    (tmp_path / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "initrunner", extras = ["recommended"] }]\n'
    )
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr("initrunner._install._in_container", lambda: False)
    monkeypatch.setattr("initrunner._install._is_editable", lambda: False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr("initrunner._install._reexeced", False)
    return tmp_path


def _run_entry(argv):
    """Run the real CLI entry point, returning its exit code."""
    from initrunner.cli.main import app_entry

    with patch.object(sys, "argv", ["initrunner", *argv]):
        try:
            app_entry()
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 1
    return 0


class TestOfferInstall:
    """The prompt, end to end through app_entry, not just the helper."""

    def test_accepting_installs_then_reruns_the_command(self, installable, no_webview, capsys):
        with (
            patch("initrunner.cli._helpers._extras._is_interactive", return_value=True),
            patch("typer.confirm", return_value=True),
            patch("subprocess.run") as run,
            patch("os.execv", side_effect=SystemExit(0)) as execv,
        ):
            _run_entry(["desktop"])

        assert run.call_args[0][0] == [
            "uv",
            "tool",
            "install",
            "initrunner[desktop,recommended]",
        ]
        exe, argv = execv.call_args[0]
        assert exe == sys.executable
        assert argv == [sys.executable, "-m", "initrunner", "desktop"]

    def test_the_rerun_is_marked_so_it_cannot_loop(self, installable, no_webview):
        import os

        seen = {}
        with (
            patch("initrunner.cli._helpers._extras._is_interactive", return_value=True),
            patch("typer.confirm", return_value=True),
            patch("subprocess.run"),
            patch(
                "os.execv",
                side_effect=lambda *a: (
                    seen.update(os.environ) or (_ for _ in ()).throw(SystemExit(0))
                ),
            ),
        ):
            _run_entry(["desktop"])

        from initrunner._install import REEXEC_ENV_VAR

        assert seen[REEXEC_ENV_VAR] == "1"

    def test_declining_prints_the_command_and_exits(self, installable, no_webview, capsys):
        with (
            patch("initrunner.cli._helpers._extras._is_interactive", return_value=True),
            patch("typer.confirm", return_value=False),
            patch("subprocess.run") as run,
            patch("os.execv") as execv,
        ):
            code = _run_entry(["desktop"])

        out = " ".join(capsys.readouterr().out.split())
        assert code == 1
        assert "uv tool install 'initrunner[desktop,recommended]'" in out
        run.assert_not_called()
        execv.assert_not_called()

    def test_a_failed_install_does_not_rerun(self, installable, no_webview):
        import subprocess

        with (
            patch("initrunner.cli._helpers._extras._is_interactive", return_value=True),
            patch("typer.confirm", return_value=True),
            patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["uv"])),
            patch("os.execv") as execv,
        ):
            code = _run_entry(["desktop"])

        assert code == 1
        execv.assert_not_called()

    def test_non_interactive_never_prompts(self, installable, no_webview, capsys):
        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("typer.confirm") as confirm,
            patch("subprocess.run") as run,
        ):
            code = _run_entry(["desktop"])

        out = " ".join(capsys.readouterr().out.split())
        assert code == 1
        confirm.assert_not_called()
        run.assert_not_called()
        assert "uv tool install" in out

    def test_ci_never_prompts(self, installable, no_webview, monkeypatch):
        monkeypatch.setenv("CI", "true")
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch("typer.confirm") as confirm,
        ):
            code = _run_entry(["desktop"])

        assert code == 1
        confirm.assert_not_called()

    def test_a_rerun_that_still_fails_does_not_ask_again(
        self, installable, no_webview, monkeypatch
    ):
        """Otherwise a broken install loops between prompt and re-exec."""
        monkeypatch.setenv("INITRUNNER_REEXEC", "1")
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch("typer.confirm") as confirm,
        ):
            code = _run_entry(["desktop"])

        assert code == 1
        confirm.assert_not_called()

    def test_the_loop_guard_is_not_inherited_by_children(
        self, installable, no_webview, monkeypatch
    ):
        """Daemons and service ticks would otherwise never offer to install."""
        import os

        monkeypatch.setenv("INITRUNNER_REEXEC", "1")
        with patch("sys.stdin.isatty", return_value=False):
            _run_entry(["desktop"])
        assert "INITRUNNER_REEXEC" not in os.environ

    def test_an_install_that_cannot_be_rebuilt_only_prints(self, no_webview, monkeypatch, capsys):
        """A checkout gets uv sync, never an unattended reinstall."""
        monkeypatch.setattr("initrunner._install.install_method", lambda: "editable")
        monkeypatch.setattr("initrunner._install._reexeced", False)
        with (
            patch("initrunner.cli._helpers._extras._is_interactive", return_value=True),
            patch("typer.confirm") as confirm,
            patch("subprocess.run") as run,
        ):
            code = _run_entry(["desktop"])

        out = " ".join(capsys.readouterr().out.split())
        assert code == 1
        confirm.assert_not_called()
        run.assert_not_called()
        assert "uv sync --extra desktop" in out


class TestEveryGapCarriesItsExtra:
    """The prompt can only fire when the exception names the extra."""

    def test_search_fails_at_build_not_on_the_first_search(self, no_ddgs):
        from initrunner.agent.schema.tools import SearchToolConfig

        role = make_role(tools=[SearchToolConfig(type="search")])
        with pytest.raises(RoleLoadError) as exc:
            build_agent(role)

        assert "initrunner[search]" in str(exc.value)
        assert isinstance(exc.value.__cause__, MissingExtraError)
        assert exc.value.__cause__.extra == "search"

    def test_a_non_duckduckgo_provider_needs_no_extra(self, no_ddgs):
        """Brave and friends run on core httpx."""
        from initrunner.agent.schema.tools import SearchToolConfig

        role = make_role(tools=[SearchToolConfig(type="search", provider="brave", api_key="k")])
        build_agent(role)

    def test_missing_provider_sdk_keeps_its_cause(self):
        """`from None` here would hide the extra from the prompt."""
        role = make_role(provider="anthropic", model_name="claude-sonnet-4-6")
        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(RoleLoadError) as exc:
                build_agent(role)

        assert isinstance(exc.value.__cause__, MissingExtraError)
        assert exc.value.__cause__.extra == "anthropic"

    def test_vector_gap_carries_its_extra(self, no_lancedb):
        role = make_role(memory=MemoryConfig())
        with pytest.raises(RoleLoadError) as exc:
            build_agent(role)

        cause = exc.value.__cause__
        assert isinstance(cause, MissingExtraError)
        assert cause.extra == "vector"


class TestMcpKeepsStdoutClean:
    """`mcp serve` speaks the protocol on stdout; a hint there is a parse error."""

    def test_nothing_reaches_stdout(self, no_fastmcp, installable, tmp_path, capsys):
        role = tmp_path / "agent.yaml"
        role.write_text("name: a\nprompt: p\nmodel:\n  provider: openai\n  name: gpt-5-mini\n")
        with patch("sys.stdin.isatty", return_value=False):
            code = _run_entry(["mcp", "serve", str(role)])

        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert "initrunner[mcp]" in " ".join(captured.err.split())
