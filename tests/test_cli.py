"""Tests for the CLI."""

import textwrap
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from initrunner import __version__
from initrunner.cli.main import app

runner = CliRunner()


class TestVersion:
    def test_version(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output


class TestValidate:
    def test_valid_role(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-agent
              description: test
            spec:
              role: You are helpful.
              model:
                provider: openai
                name: gpt-5-mini
        """)
        )
        result = runner.invoke(app, ["validate", str(role_file)])
        assert result.exit_code == 0
        assert "Valid" in result.output

    def test_valid_role_with_tools_and_triggers(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-agent
              description: test
            spec:
              role: You are helpful.
              model:
                provider: openai
                name: gpt-5-mini
              tools:
                - type: filesystem
                  root_path: /src
              triggers:
                - type: cron
                  schedule: "0 9 * * 1"
                  prompt: "Weekly report"
              ingest:
                sources:
                  - "./docs/**/*.md"
        """)
        )
        result = runner.invoke(app, ["validate", str(role_file)])
        assert result.exit_code == 0
        assert "filesystem" in result.output
        assert "cron" in result.output
        assert "1 source(s)" in result.output

    def test_invalid_role(self, tmp_path):
        role_file = tmp_path / "bad.yaml"
        role_file.write_text("apiVersion: wrong\n")
        result = runner.invoke(app, ["validate", str(role_file)])
        assert result.exit_code == 1
        assert "Invalid" in result.output

    def test_missing_file(self):
        result = runner.invoke(app, ["validate", "/nonexistent/role.yaml"])
        assert result.exit_code == 1


class TestRun:
    def test_missing_role_file(self):
        result = runner.invoke(app, ["run", "/nonexistent/role.yaml", "-p", "hello"])
        assert result.exit_code == 1

    @patch("initrunner.runner.run_single")
    @patch("initrunner.agent.loader.load_and_build")
    def test_single_prompt(self, mock_load, mock_run_single, tmp_path):
        from initrunner.agent.executor import RunResult

        role = MagicMock()
        role.spec.memory = None
        role.spec.sinks = []
        role.spec.observability = None
        agent = MagicMock()
        mock_load.return_value = (role, agent)
        mock_run_single.return_value = (
            RunResult(run_id="test", output="hello", success=True),
            [],
        )

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")  # won't be read due to mock

        # Use --format rich to force buffered panel path (CliRunner is non-TTY)
        result = runner.invoke(
            app, ["run", str(role_file), "-p", "hello", "--format", "rich", "--no-audit"]
        )
        assert result.exit_code == 0
        mock_run_single.assert_called_once()

    def test_no_role_ephemeral_rejects_daemon(self):
        """Ephemeral mode should reject --daemon."""
        result = runner.invoke(app, ["run", "--daemon"])
        assert result.exit_code == 1
        assert "--daemon" in result.output

    def test_role_and_sense_mutually_exclusive(self, tmp_path):
        """Providing both a role file and --sense should error."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")
        result = runner.invoke(app, ["run", str(role_file), "--sense", "-p", "hello"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_sense_requires_prompt(self):
        """--sense without -p should error."""
        result = runner.invoke(app, ["run", "--sense"])
        assert result.exit_code == 1
        assert "--sense requires --prompt" in result.output

    @patch("initrunner.runner.run_single")
    @patch("initrunner.agent.loader.load_and_build")
    @patch("initrunner.services.role_selector.select_role_sync")
    def test_auto_selects_and_executes(self, mock_select, mock_load, mock_run_single, tmp_path):
        """--sense resolves a role and runs it."""
        from initrunner.agent.executor import RunResult
        from initrunner.services.role_selector import RoleCandidate, SelectionResult

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        cand = RoleCandidate(
            path=role_file,
            name="test-agent",
            description="A test agent",
            tags=["test"],
        )
        mock_select.return_value = SelectionResult(candidate=cand, method="keyword")

        role = MagicMock()
        role.spec.memory = None
        role.spec.sinks = []
        role.spec.observability = None
        agent = MagicMock()
        mock_load.return_value = (role, agent)
        mock_run_single.return_value = (
            RunResult(run_id="test", output="hello", success=True),
            [],
        )

        # Use --format rich to force buffered panel path (CliRunner is non-TTY)
        result = runner.invoke(
            app, ["run", "--sense", "-p", "test task", "--format", "rich", "--no-audit"]
        )
        assert result.exit_code == 0
        mock_select.assert_called_once_with("test task", role_dir=None, allow_llm=True)
        mock_run_single.assert_called_once()

    @patch("initrunner.services.role_selector.select_role_sync")
    def test_auto_dry_run_passes_allow_llm_false(self, mock_select, tmp_path):
        """--dry-run with --sense passes allow_llm=False to select_role_sync."""
        from initrunner.services.role_selector import NoRolesFoundError

        mock_select.side_effect = NoRolesFoundError("no roles")
        result = runner.invoke(app, ["run", "--sense", "--dry-run", "-p", "task"])
        assert result.exit_code == 1
        mock_select.assert_called_once_with("task", role_dir=None, allow_llm=False)

    @patch("initrunner.runner.run_single")
    @patch("initrunner.agent.loader.load_and_build")
    @patch("initrunner.services.role_selector.select_role_sync")
    def test_auto_confirm_role_interactive_yes(
        self, mock_select, mock_load, mock_run_single, tmp_path
    ):
        """--confirm-role with 'y' on a TTY-like stdin proceeds."""
        import io

        from initrunner.agent.executor import RunResult
        from initrunner.services.role_selector import RoleCandidate, SelectionResult

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        cand = RoleCandidate(
            path=role_file,
            name="test-agent",
            description="desc",
            tags=[],
        )
        mock_select.return_value = SelectionResult(candidate=cand, method="keyword")

        role = MagicMock()
        role.spec.memory = None
        role.spec.sinks = []
        role.spec.observability = None
        mock_load.return_value = (role, MagicMock())
        mock_run_single.return_value = (
            RunResult(run_id="x", output="ok", success=True),
            [],
        )

        # Use a custom stream that reports isatty()=True; Click passes non-string
        # inputs through directly as sys.stdin inside isolation()
        class _FakeTTY(io.BytesIO):
            def isatty(self):
                return True

        # Use --format rich to force buffered panel path (CliRunner is non-TTY)
        result = runner.invoke(
            app,
            ["run", "--sense", "--confirm-role", "-p", "task", "--format", "rich", "--no-audit"],
            input=_FakeTTY(b"y\n"),
        )
        assert result.exit_code == 0

    @patch("initrunner.services.role_selector.select_role_sync")
    def test_auto_confirm_role_non_tty_errors(self, mock_select, tmp_path):
        """--confirm-role in a non-TTY environment (CliRunner default) should error."""
        from initrunner.services.role_selector import RoleCandidate, SelectionResult

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        cand = RoleCandidate(
            path=role_file,
            name="test-agent",
            description="desc",
            tags=[],
        )
        mock_select.return_value = SelectionResult(candidate=cand, method="keyword")

        # No stdin patch: CliRunner provides a BytesIO stdin with isatty()=False
        result = runner.invoke(
            app,
            ["run", "--sense", "--confirm-role", "-p", "task"],
        )
        assert result.exit_code == 1
        assert "interactive terminal" in result.output

    @patch("initrunner.services.role_selector.select_role_sync")
    def test_auto_confirm_role_interactive_no(self, mock_select, tmp_path):
        """--confirm-role with 'n' on a TTY-like stdin cancels the run (exit 0)."""
        import io

        from initrunner.services.role_selector import RoleCandidate, SelectionResult

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        cand = RoleCandidate(
            path=role_file,
            name="test-agent",
            description="desc",
            tags=[],
        )
        mock_select.return_value = SelectionResult(candidate=cand, method="keyword")

        class _FakeTTY(io.BytesIO):
            def isatty(self):
                return True

        result = runner.invoke(
            app,
            ["run", "--sense", "--confirm-role", "-p", "task"],
            input=_FakeTTY(b"n\n"),
        )
        # typer.Exit() without code = 0
        assert result.exit_code == 0


class TestRunStreaming:
    """Tests for the --no-stream flag and TTY streaming gate."""

    @patch("initrunner.runner.run_single_stream")
    @patch("initrunner.runner.run_single")
    @patch("initrunner.agent.loader.load_and_build")
    def test_tty_text_output_uses_streaming(
        self, mock_load, mock_run_single, mock_run_stream, tmp_path
    ):
        """TTY + text output role should use run_single_stream."""
        from initrunner.agent.executor import RunResult
        from initrunner.agent.schema.output import OutputConfig

        role = MagicMock()
        role.spec.memory = None
        role.spec.sinks = []
        role.spec.observability = None
        role.spec.output = OutputConfig(type="text")
        mock_load.return_value = (role, MagicMock())
        mock_run_stream.return_value = (
            RunResult(run_id="test", output="hello", success=True),
            [],
        )

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        with patch("initrunner.cli._run_agent.sys") as mock_sys:
            mock_sys.stdout.isatty.return_value = True
            result = runner.invoke(app, ["run", str(role_file), "-p", "hello", "--no-audit"])

        assert result.exit_code == 0
        mock_run_stream.assert_called_once()
        mock_run_single.assert_not_called()

    @patch("initrunner.cli._run_agent._run_formatted")
    @patch("initrunner.runner.run_single_stream")
    @patch("initrunner.agent.loader.load_and_build")
    def test_non_tty_uses_plain_text(self, mock_load, mock_run_stream, mock_formatted, tmp_path):
        """Non-TTY should use _run_formatted with effective='text'."""
        from initrunner.agent.executor import RunResult
        from initrunner.agent.schema.output import OutputConfig

        role = MagicMock()
        role.spec.memory = None
        role.spec.sinks = []
        role.spec.observability = None
        role.spec.output = OutputConfig(type="text")
        mock_load.return_value = (role, MagicMock())
        mock_formatted.return_value = (
            RunResult(run_id="test", output="hello", success=True),
            [],
        )

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        with patch("initrunner.cli._run_agent.sys") as mock_sys:
            mock_sys.stdout.isatty.return_value = False
            result = runner.invoke(app, ["run", str(role_file), "-p", "hello", "--no-audit"])

        assert result.exit_code == 0
        mock_formatted.assert_called_once()
        assert mock_formatted.call_args[0][0] == "text"
        mock_run_stream.assert_not_called()

    @patch("initrunner.runner.run_single_stream")
    @patch("initrunner.runner.run_single")
    @patch("initrunner.agent.loader.load_and_build")
    def test_no_stream_forces_buffered(self, mock_load, mock_run_single, mock_run_stream, tmp_path):
        """--no-stream on TTY should use run_single (buffered)."""
        from initrunner.agent.executor import RunResult
        from initrunner.agent.schema.output import OutputConfig

        role = MagicMock()
        role.spec.memory = None
        role.spec.sinks = []
        role.spec.observability = None
        role.spec.output = OutputConfig(type="text")
        mock_load.return_value = (role, MagicMock())
        mock_run_single.return_value = (
            RunResult(run_id="test", output="hello", success=True),
            [],
        )

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        with patch("initrunner.cli._run_agent.sys") as mock_sys:
            mock_sys.stdout.isatty.return_value = True
            result = runner.invoke(
                app, ["run", str(role_file), "-p", "hello", "--no-stream", "--no-audit"]
            )

        assert result.exit_code == 0
        mock_run_single.assert_called_once()
        mock_run_stream.assert_not_called()

    @patch("initrunner.runner.run_interactive")
    @patch("initrunner.runner.run_single_stream")
    @patch("initrunner.agent.loader.load_and_build")
    def test_initial_prompt_interactive_passes_stream(
        self, mock_load, mock_run_stream, mock_interactive, tmp_path
    ):
        """-p 'hi' -i should pass stream=True to run_interactive on TTY."""
        from initrunner.agent.executor import RunResult
        from initrunner.agent.schema.output import OutputConfig

        role = MagicMock()
        role.spec.memory = None
        role.spec.sinks = []
        role.spec.observability = None
        role.spec.output = OutputConfig(type="text")
        mock_load.return_value = (role, MagicMock())
        mock_run_stream.return_value = (
            RunResult(run_id="test", output="hello", success=True),
            [],
        )

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        with patch("initrunner.cli._run_agent.sys") as mock_sys:
            mock_sys.stdout.isatty.return_value = True
            result = runner.invoke(app, ["run", str(role_file), "-p", "hi", "-i", "--no-audit"])

        assert result.exit_code == 0
        mock_interactive.assert_called_once()
        call_kwargs = mock_interactive.call_args.kwargs
        assert call_kwargs["stream"] is True

    @patch("initrunner.runner.run_autonomous")
    @patch("initrunner.runner.run_single_stream")
    @patch("initrunner.runner.run_single")
    @patch("initrunner.agent.loader.load_and_build")
    def test_autonomous_does_not_stream(
        self, mock_load, mock_run_single, mock_run_stream, mock_autonomous, tmp_path
    ):
        """-a -p 'hi' should not use streaming."""
        from initrunner.agent.schema.output import OutputConfig

        role = MagicMock()
        role.spec.memory = None
        role.spec.sinks = []
        role.spec.observability = None
        role.spec.output = OutputConfig(type="text")
        mock_load.return_value = (role, MagicMock())

        auto_result = MagicMock()
        auto_result.success = True
        auto_result.total_tokens = 100
        mock_autonomous.return_value = auto_result

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        with patch("initrunner.cli._run_agent.sys") as mock_sys:
            mock_sys.stdout.isatty.return_value = True
            result = runner.invoke(app, ["run", str(role_file), "-a", "-p", "hi", "--no-audit"])

        assert result.exit_code == 0
        mock_autonomous.assert_called_once()
        mock_run_stream.assert_not_called()
        mock_run_single.assert_not_called()


class TestRunOutputFormat:
    """Tests for --format flag and plain/json output modes."""

    def _mock_role(self):
        from initrunner.agent.schema.output import OutputConfig

        role = MagicMock()
        role.spec.memory = None
        role.spec.sinks = []
        role.spec.observability = None
        role.spec.output = OutputConfig(type="text")
        return role

    @patch("initrunner.cli._run_agent._run_formatted")
    @patch("initrunner.agent.loader.load_and_build")
    def test_format_json_calls_run_formatted(self, mock_load, mock_formatted, tmp_path):
        """--format json should use _run_formatted with effective='json'."""
        from initrunner.agent.executor import RunResult

        role = self._mock_role()
        mock_load.return_value = (role, MagicMock())
        mock_formatted.return_value = (
            RunResult(run_id="test", output="hello", success=True),
            [],
        )

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        result = runner.invoke(
            app, ["run", str(role_file), "-p", "hello", "--format", "json", "--no-audit"]
        )

        assert result.exit_code == 0
        mock_formatted.assert_called_once()
        assert mock_formatted.call_args[0][0] == "json"

    @patch("initrunner.cli._run_agent._run_formatted")
    @patch("initrunner.agent.loader.load_and_build")
    def test_format_text_calls_run_formatted(self, mock_load, mock_formatted, tmp_path):
        """--format text should use _run_formatted with effective='text'."""
        from initrunner.agent.executor import RunResult

        role = self._mock_role()
        mock_load.return_value = (role, MagicMock())
        mock_formatted.return_value = (
            RunResult(run_id="test", output="hello", success=True),
            [],
        )

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        result = runner.invoke(
            app, ["run", str(role_file), "-p", "hello", "--format", "text", "--no-audit"]
        )

        assert result.exit_code == 0
        mock_formatted.assert_called_once()
        assert mock_formatted.call_args[0][0] == "text"

    @patch("initrunner.cli._run_agent._run_formatted")
    @patch("initrunner.runner.run_single_stream")
    @patch("initrunner.agent.loader.load_and_build")
    def test_format_auto_non_tty_uses_text(
        self, mock_load, mock_run_stream, mock_formatted, tmp_path
    ):
        """auto format + non-TTY should use _run_formatted with effective='text'."""
        from initrunner.agent.executor import RunResult

        role = self._mock_role()
        mock_load.return_value = (role, MagicMock())
        mock_formatted.return_value = (
            RunResult(run_id="test", output="hello", success=True),
            [],
        )

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        with patch("initrunner.cli._run_agent.sys") as mock_sys:
            mock_sys.stdout.isatty.return_value = False
            result = runner.invoke(app, ["run", str(role_file), "-p", "hello", "--no-audit"])

        assert result.exit_code == 0
        mock_formatted.assert_called_once()
        assert mock_formatted.call_args[0][0] == "text"
        mock_run_stream.assert_not_called()

    @patch("initrunner.runner.run_single_stream")
    @patch("initrunner.runner.run_single")
    @patch("initrunner.agent.loader.load_and_build")
    def test_format_auto_tty_still_streams(
        self, mock_load, mock_run_single, mock_run_stream, tmp_path
    ):
        """auto format + TTY should still use run_single_stream."""
        from initrunner.agent.executor import RunResult

        role = self._mock_role()
        mock_load.return_value = (role, MagicMock())
        mock_run_stream.return_value = (
            RunResult(run_id="test", output="hello", success=True),
            [],
        )

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        with patch("initrunner.cli._run_agent.sys") as mock_sys:
            mock_sys.stdout.isatty.return_value = True
            result = runner.invoke(app, ["run", str(role_file), "-p", "hello", "--no-audit"])

        assert result.exit_code == 0
        mock_run_stream.assert_called_once()
        mock_run_single.assert_not_called()

    @patch("initrunner.runner.run_single")
    @patch("initrunner.runner.run_single_stream")
    @patch("initrunner.agent.loader.load_and_build")
    def test_format_rich_uses_buffered(self, mock_load, mock_run_stream, mock_run_single, tmp_path):
        """--format rich should use run_single (buffered panel)."""
        from initrunner.agent.executor import RunResult

        role = self._mock_role()
        mock_load.return_value = (role, MagicMock())
        mock_run_single.return_value = (
            RunResult(run_id="test", output="hello", success=True),
            [],
        )

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        with patch("initrunner.cli._run_agent.sys") as mock_sys:
            mock_sys.stdout.isatty.return_value = True
            result = runner.invoke(
                app, ["run", str(role_file), "-p", "hello", "--format", "rich", "--no-audit"]
            )

        assert result.exit_code == 0
        mock_run_single.assert_called_once()
        mock_run_stream.assert_not_called()

    def test_format_json_with_interactive_errors(self, tmp_path):
        """--format json with -i should be rejected."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        result = runner.invoke(
            app,
            ["run", str(role_file), "-p", "hello", "--format", "json", "-i", "--no-audit"],
        )
        assert result.exit_code == 1
        assert "not supported with -i" in result.output

    def test_format_text_with_autonomous_errors(self, tmp_path):
        """--format text with -a should be rejected."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        result = runner.invoke(
            app,
            ["run", str(role_file), "-p", "hello", "--format", "text", "-a", "--no-audit"],
        )
        assert result.exit_code == 1
        assert "not supported with -a" in result.output

    def test_format_invalid_errors(self, tmp_path):
        """Unknown format value should be rejected."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        result = runner.invoke(
            app,
            ["run", str(role_file), "-p", "hello", "--format", "xml", "--no-audit"],
        )
        assert result.exit_code == 1
        assert "Unknown format" in result.output

    def test_no_stream_deprecation_warning(self, tmp_path):
        """--no-stream should emit a deprecation warning."""
        from initrunner.agent.executor import RunResult

        role = self._mock_role()

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        with (
            patch("initrunner.agent.loader.load_and_build", return_value=(role, MagicMock())),
            patch(
                "initrunner.runner.run_single",
                return_value=(RunResult(run_id="t", output="ok", success=True), []),
            ),
            patch("initrunner.cli._run_agent.sys") as mock_sys,
        ):
            mock_sys.stdout.isatty.return_value = True
            result = runner.invoke(
                app, ["run", str(role_file), "-p", "hello", "--no-stream", "--no-audit"]
            )

        assert result.exit_code == 0
        # Deprecation warning goes to stderr (captured by typer.echo(err=True))
        # CliRunner merges stdout+stderr in output by default
        assert "deprecated" in result.output.lower()


class TestDisplayResultPlain:
    """Tests for _display_result_plain output format."""

    def test_success_writes_output_to_stdout(self, capsys):
        from initrunner.agent.executor import RunResult
        from initrunner.runner.display import _display_result_plain

        result = RunResult(
            run_id="r1",
            output="The answer is 42.",
            success=True,
            tokens_in=10,
            tokens_out=5,
            duration_ms=120,
        )
        _display_result_plain(result)

        captured = capsys.readouterr()
        assert captured.out == "The answer is 42.\n"
        assert "tokens: 10in/5out | 120ms" in captured.err

    def test_error_writes_to_stderr_only(self, capsys):
        from initrunner.agent.executor import RunResult
        from initrunner.runner.display import _display_result_plain

        result = RunResult(run_id="r1", output="", success=False, error="Model error")
        _display_result_plain(result)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Error: Model error" in captured.err

    def test_no_extra_newline_when_output_ends_with_newline(self, capsys):
        from initrunner.agent.executor import RunResult
        from initrunner.runner.display import _display_result_plain

        result = RunResult(run_id="r1", output="hello\n", success=True)
        _display_result_plain(result)

        captured = capsys.readouterr()
        assert captured.out == "hello\n"  # no double newline


class TestDisplayResultJson:
    """Tests for _display_result_json output format."""

    def test_success_produces_valid_json(self, capsys):
        import json

        from initrunner.agent.executor import RunResult
        from initrunner.runner.display import _display_result_json

        result = RunResult(
            run_id="r1",
            output="hello",
            success=True,
            tokens_in=10,
            tokens_out=5,
            total_tokens=15,
            tool_calls=2,
            duration_ms=100,
            tool_call_names=["web_search", "filesystem"],
        )
        _display_result_json(result)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["run_id"] == "r1"
        assert data["output"] == "hello"
        assert data["success"] is True
        assert data["error"] is None
        assert data["tokens_in"] == 10
        assert data["tokens_out"] == 5
        assert data["total_tokens"] == 15
        assert data["tool_calls"] == 2
        assert data["tool_call_names"] == ["web_search", "filesystem"]
        assert data["duration_ms"] == 100
        assert captured.err == ""

    def test_error_includes_error_field(self, capsys):
        import json

        from initrunner.agent.executor import RunResult
        from initrunner.runner.display import _display_result_json

        result = RunResult(
            run_id="r1",
            output="",
            success=False,
            error="Model timeout",
        )
        _display_result_json(result)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is False
        assert data["error"] == "Model timeout"

    def test_no_final_messages_in_output(self, capsys):
        """JSON envelope must not include final_messages (non-serializable)."""
        import json

        from initrunner.agent.executor import RunResult
        from initrunner.runner.display import _display_result_json

        result = RunResult(run_id="r1", output="ok", success=True)
        _display_result_json(result)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "final_messages" not in data
        assert "messages" not in data


class TestIngest:
    def test_missing_role_file(self):
        result = runner.invoke(app, ["ingest", "/nonexistent/role.yaml"])
        assert result.exit_code == 1

    def test_no_ingest_config(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-agent
            spec:
              role: Test
              model:
                provider: openai
                name: gpt-5-mini
        """)
        )
        result = runner.invoke(app, ["ingest", str(role_file)])
        assert result.exit_code == 1
        assert "No ingest config" in result.output

    def test_ingest_force_flag(self, tmp_path):
        """Verify --force flag is accepted by the CLI."""
        from initrunner.ingestion.pipeline import IngestStats

        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-agent
            spec:
              role: Test
              model:
                provider: openai
                name: gpt-5-mini
              ingest:
                sources:
                  - "*.txt"
        """)
        )
        (tmp_path / "a.txt").write_text("hello")

        with patch(
            "initrunner.ingestion.pipeline.run_ingest",
            return_value=IngestStats(new=1, total_chunks=1),
        ) as mock_ingest:
            result = runner.invoke(app, ["ingest", str(role_file), "--force"])
            assert result.exit_code == 0
            # Verify force=True was passed
            mock_ingest.assert_called_once()
            call_kwargs = mock_ingest.call_args
            assert call_kwargs.kwargs.get("force") is True

    def test_ingest_shows_summary(self, tmp_path):
        """Verify the summary output format."""
        from initrunner.ingestion.pipeline import IngestStats

        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-agent
            spec:
              role: Test
              model:
                provider: openai
                name: gpt-5-mini
              ingest:
                sources:
                  - "*.txt"
        """)
        )
        (tmp_path / "a.txt").write_text("hello")

        with patch(
            "initrunner.ingestion.pipeline.run_ingest",
            return_value=IngestStats(new=2, updated=1, skipped=3, total_chunks=10),
        ):
            result = runner.invoke(app, ["ingest", str(role_file)])
            assert result.exit_code == 0
            assert "New: 2" in result.output
            assert "Updated: 1" in result.output
            assert "Skipped: 3" in result.output
            assert "10 chunks stored" in result.output


class TestAuditExport:
    def _seed_db(self, db_path):
        import json

        from initrunner.audit.logger import AuditLogger, AuditRecord

        with AuditLogger(db_path) as logger:
            logger.log(
                AuditRecord(
                    run_id="r1",
                    agent_name="agent-a",
                    timestamp="2025-01-01T00:00:00Z",
                    user_prompt="hello",
                    model="gpt-5-mini",
                    provider="openai",
                    output="hi",
                    tokens_in=10,
                    tokens_out=5,
                    total_tokens=15,
                    tool_calls=0,
                    duration_ms=100,
                    success=True,
                    error=None,
                    trigger_type="cron",
                    trigger_metadata=json.dumps({"schedule": "daily"}),
                )
            )
            logger.log(
                AuditRecord(
                    run_id="r2",
                    agent_name="agent-b",
                    timestamp="2025-01-02T00:00:00Z",
                    user_prompt="world",
                    model="gpt-5-mini",
                    provider="openai",
                    output="ok",
                    tokens_in=20,
                    tokens_out=10,
                    total_tokens=30,
                    tool_calls=1,
                    duration_ms=200,
                    success=True,
                    error=None,
                )
            )

    def test_export_json_stdout(self, tmp_path):
        import json

        db_path = tmp_path / "audit.db"
        self._seed_db(db_path)

        result = runner.invoke(app, ["audit", "export", "--audit-db", str(db_path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2
        # Ordered by timestamp DESC
        assert data[0]["run_id"] == "r2"
        assert data[1]["run_id"] == "r1"
        # trigger_metadata deserialized to dict in JSON output
        assert data[1]["trigger_metadata"] == {"schedule": "daily"}
        assert data[0]["trigger_metadata"] is None

    def test_export_csv_stdout(self, tmp_path):
        db_path = tmp_path / "audit.db"
        self._seed_db(db_path)

        result = runner.invoke(app, ["audit", "export", "-f", "csv", "--audit-db", str(db_path)])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 3  # header + 2 rows
        assert "run_id" in lines[0]
        assert "trigger_type" in lines[0]

    def test_export_to_file(self, tmp_path):
        import json

        db_path = tmp_path / "audit.db"
        self._seed_db(db_path)
        out_file = tmp_path / "export.json"

        result = runner.invoke(
            app,
            [
                "audit",
                "export",
                "--audit-db",
                str(db_path),
                "-o",
                str(out_file),
            ],
        )
        assert result.exit_code == 0
        assert "Exported" in result.output
        assert "2 record(s)" in result.output
        data = json.loads(out_file.read_text())
        assert len(data) == 2

    def test_export_filter_agent(self, tmp_path):
        import json

        db_path = tmp_path / "audit.db"
        self._seed_db(db_path)

        result = runner.invoke(
            app,
            [
                "audit",
                "export",
                "--audit-db",
                str(db_path),
                "--agent",
                "agent-a",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["agent_name"] == "agent-a"

    def test_export_filter_trigger_type(self, tmp_path):
        import json

        db_path = tmp_path / "audit.db"
        self._seed_db(db_path)

        result = runner.invoke(
            app,
            [
                "audit",
                "export",
                "--audit-db",
                str(db_path),
                "--trigger-type",
                "cron",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["trigger_type"] == "cron"

    def test_export_missing_db(self, tmp_path):
        db_path = tmp_path / "nonexistent.db"
        result = runner.invoke(app, ["audit", "export", "--audit-db", str(db_path)])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_export_help(self):
        result = runner.invoke(app, ["audit", "export", "--help"])
        assert result.exit_code == 0
        assert "export" in result.output.lower()


class TestTestCommand:
    def _make_role_file(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-agent
            spec:
              role: You are a test.
              model:
                provider: openai
                name: gpt-5-mini
        """)
        )
        return role_file

    def _make_suite_file(self, tmp_path, name="test-suite", cases=None):
        suite_file = tmp_path / "suite.yaml"
        if cases is None:
            cases = [
                {
                    "name": "basic",
                    "prompt": "Hello",
                    "expected_output": "Hello!",
                    "assertions": [{"type": "contains", "value": "Hello"}],
                }
            ]
        import yaml

        data = {
            "apiVersion": "initrunner/v1",
            "kind": "TestSuite",
            "metadata": {"name": name},
            "cases": cases,
        }
        suite_file.write_text(yaml.dump(data))
        return suite_file

    def test_basic_dry_run(self, tmp_path):
        role_file = self._make_role_file(tmp_path)
        suite_file = self._make_suite_file(tmp_path)
        result = runner.invoke(app, ["test", str(role_file), "-s", str(suite_file), "--dry-run"])
        assert result.exit_code == 0
        assert "PASS" in result.output
        assert "Tokens" in result.output

    def test_concurrency_flag_accepted(self, tmp_path):
        """Verify -j flag is accepted by the CLI (concurrency > 1 needs real factory)."""
        role_file = self._make_role_file(tmp_path)
        suite_file = self._make_suite_file(tmp_path)
        # concurrency=1 exercises the flag parsing without needing agent_factory
        result = runner.invoke(
            app,
            ["test", str(role_file), "-s", str(suite_file), "--dry-run", "-j", "1"],
        )
        assert result.exit_code == 0

    def test_concurrency_display(self, tmp_path):
        """Verify concurrency > 1 displays in the output banner."""
        role_file = self._make_role_file(tmp_path)
        suite_file = self._make_suite_file(tmp_path)
        # With concurrency > 1, it needs a factory via load_and_build which
        # requires API keys. We just verify the display line appears.
        result = runner.invoke(
            app,
            ["test", str(role_file), "-s", str(suite_file), "--dry-run", "-j", "2"],
        )
        # May fail at execution due to missing API key, but the concurrency
        # display should appear before that
        assert "concurrency=2" in result.output

    def test_output_flag_creates_json(self, tmp_path):
        role_file = self._make_role_file(tmp_path)
        suite_file = self._make_suite_file(tmp_path)
        output_file = tmp_path / "results.json"
        result = runner.invoke(
            app,
            [
                "test",
                str(role_file),
                "-s",
                str(suite_file),
                "--dry-run",
                "-o",
                str(output_file),
            ],
        )
        assert result.exit_code == 0
        assert output_file.exists()
        import json

        data = json.loads(output_file.read_text())
        assert data["suite_name"] == "test-suite"
        assert "summary" in data
        assert "cases" in data
        assert "Results saved" in result.output

    def test_tag_filter(self, tmp_path):
        role_file = self._make_role_file(tmp_path)
        suite_file = self._make_suite_file(
            tmp_path,
            cases=[
                {"name": "tagged", "prompt": "p1", "tags": ["fast"], "expected_output": "ok"},
                {"name": "untagged", "prompt": "p2", "expected_output": "ok"},
            ],
        )
        result = runner.invoke(
            app,
            [
                "test",
                str(role_file),
                "-s",
                str(suite_file),
                "--dry-run",
                "--tag",
                "fast",
            ],
        )
        assert result.exit_code == 0
        # Only the tagged case should run
        assert "tagged" in result.output

    def test_missing_suite_file(self, tmp_path):
        role_file = self._make_role_file(tmp_path)
        result = runner.invoke(app, ["test", str(role_file), "-s", str(tmp_path / "missing.yaml")])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_verbose_shows_details(self, tmp_path):
        role_file = self._make_role_file(tmp_path)
        suite_file = self._make_suite_file(tmp_path)
        result = runner.invoke(
            app,
            ["test", str(role_file), "-s", str(suite_file), "--dry-run", "-v"],
        )
        assert result.exit_code == 0
        # Verbose adds a Details column and assertion messages
        assert "contains" in result.output.lower()

    def test_summary_stats_shown(self, tmp_path):
        role_file = self._make_role_file(tmp_path)
        suite_file = self._make_suite_file(tmp_path)
        result = runner.invoke(app, ["test", str(role_file), "-s", str(suite_file), "--dry-run"])
        assert result.exit_code == 0
        assert "tokens" in result.output.lower()
        assert "total" in result.output.lower()


class TestDaemonFlag:
    def test_missing_role_file(self):
        result = runner.invoke(app, ["run", "/nonexistent/role.yaml", "--daemon"])
        assert result.exit_code == 1


class TestResolveRolePathInstalled:
    """resolve_role_path falls through to installed role lookup."""

    def test_local_file_takes_precedence(self, tmp_path):
        """A local file path is returned without hitting the registry."""
        from initrunner.cli._helpers import resolve_role_path

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")
        assert resolve_role_path(role_file) == role_file

    def test_local_dir_takes_precedence(self, tmp_path):
        """A local directory with role.yaml is returned without hitting the registry."""
        from initrunner.cli._helpers import resolve_role_path

        (tmp_path / "role.yaml").write_text("dummy")
        assert resolve_role_path(tmp_path) == tmp_path / "role.yaml"

    def test_falls_through_to_installed(self, tmp_path, monkeypatch):
        """A non-existent path resolves via the registry."""
        import json
        from pathlib import Path

        from initrunner.cli._helpers import resolve_role_path

        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)
        role_dir = roles_dir / "hub__alice__code-reviewer"
        role_dir.mkdir()
        (role_dir / "role.yaml").write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: code-reviewer
            spec:
              role: You review code.
              model:
                provider: openai
                name: gpt-5-mini
        """)
        )

        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "hub:alice/code-reviewer": {
                            "display_name": "code-reviewer",
                            "source_type": "hub",
                            "local_path": "hub__alice__code-reviewer",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        resolved = resolve_role_path(Path("code-reviewer"))
        assert resolved == role_dir / "role.yaml"

    def test_run_command_with_installed_name(self, tmp_path, monkeypatch):
        """'initrunner run code-reviewer -p hello' resolves via registry."""
        import json

        roles_dir = tmp_path / "roles"
        roles_dir.mkdir(parents=True)
        role_dir = roles_dir / "hub__alice__code-reviewer"
        role_dir.mkdir()
        (role_dir / "role.yaml").write_text("dummy")

        manifest_path = roles_dir / "registry.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roles": {
                        "hub:alice/code-reviewer": {
                            "display_name": "code-reviewer",
                            "source_type": "hub",
                            "local_path": "hub__alice__code-reviewer",
                        }
                    }
                }
            )
        )

        monkeypatch.setattr("initrunner.registry.ROLES_DIR", roles_dir)
        monkeypatch.setattr("initrunner.registry.MANIFEST_PATH", manifest_path)

        from initrunner.agent.executor import RunResult

        role = MagicMock()
        role.spec.memory = None
        role.spec.sinks = []
        role.spec.observability = None
        agent = MagicMock()

        with (
            patch("initrunner.agent.loader.load_and_build", return_value=(role, agent)),
            patch(
                "initrunner.runner.run_single",
                return_value=(RunResult(run_id="t", output="ok", success=True), []),
            ),
        ):
            # Use --format rich to force buffered panel path (CliRunner is non-TTY)
            result = runner.invoke(
                app, ["run", "code-reviewer", "-p", "hello", "--format", "rich", "--no-audit"]
            )

        assert result.exit_code == 0


class TestHelpPanels:
    """Verify --help groups commands into rich_help_panel sections."""

    def test_all_panels_present(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for panel in (
            "Getting Started",
            "Run & Test",
            "Interfaces",
            "Package Registry",
            "Agent Internals",
        ):
            assert panel in result.output, f"Panel '{panel}' missing from help output"

    def test_no_default_commands_panel(self):
        """All commands are assigned to a panel -- no leftover 'Commands' group."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # Typer renders a "Commands" header when ungrouped commands exist.
        # With every command assigned to a panel, it should not appear.
        lines = result.output.splitlines()
        assert not any(
            line.strip() == "Commands" or line.strip() == "Commands:" for line in lines
        ), "Default 'Commands' panel should not appear when all commands are grouped"

    def test_hub_hidden_from_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # hub should not appear as a listed command in any panel
        lines = result.output.splitlines()
        hub_lines = [ln for ln in lines if ln.strip().startswith("hub ")]
        assert len(hub_lines) == 0, "Deprecated 'hub' should be hidden from --help"

    def test_hub_still_works(self):
        """hidden=True hides from help but the sub-app remains invocable."""
        result = runner.invoke(app, ["hub", "--help"])
        assert result.exit_code == 0


class TestSuggestNext:
    """Tests for the suggest_next() helper and its CLI integration."""

    def test_suggest_next_tty_shows_footer(self):
        """suggest_next prints suggestions when stdout is a TTY."""
        from initrunner.cli._helpers import suggest_next

        role = MagicMock()
        role.spec.autonomy = None
        role.spec.ingest = None
        role.spec.memory = None

        from io import StringIO

        buf = StringIO()
        with patch("sys.stdout", buf), patch("sys.stdout.isatty", return_value=True):
            suggest_next("run_single", role, __import__("pathlib").Path("role.yaml"))

        output = buf.getvalue()
        assert "Next steps" in output
        assert "initrunner run" in output

    def test_suggest_next_non_tty_silent(self):
        """suggest_next prints nothing when stdout is not a TTY."""
        from initrunner.cli._helpers import suggest_next

        role = MagicMock()
        role.spec.autonomy = None

        from io import StringIO

        buf = StringIO()
        with patch("sys.stdout", buf), patch("sys.stdout.isatty", return_value=False):
            suggest_next("run_single", role, __import__("pathlib").Path("role.yaml"))

        assert buf.getvalue() == ""

    @patch("initrunner.runner.run_single")
    @patch("initrunner.agent.loader.load_and_build")
    def test_run_format_json_no_footer(self, mock_load, mock_run_single, tmp_path):
        """--format json must not append next-step text."""
        from initrunner.agent.executor import RunResult
        from initrunner.agent.schema.output import OutputConfig

        role = MagicMock()
        role.spec.memory = None
        role.spec.sinks = []
        role.spec.observability = None
        role.spec.output = OutputConfig(type="text")
        agent = MagicMock()
        mock_load.return_value = (role, agent)
        mock_run_single.return_value = (
            RunResult(run_id="test", output='{"result": "ok"}', success=True),
            [],
        )

        role_file = tmp_path / "role.yaml"
        role_file.write_text("dummy")

        result = runner.invoke(
            app, ["run", str(role_file), "-p", "hello", "--format", "json", "--no-audit"]
        )
        assert result.exit_code == 0
        assert "Next steps" not in result.output

    def test_validate_shows_next_steps(self, tmp_path):
        """validate should show next-step suggestions for Agent roles."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-agent
              description: test
            spec:
              role: You are helpful.
              model:
                provider: openai
                name: gpt-5-mini
        """)
        )
        # CliRunner is non-TTY, so suggest_next should be suppressed
        result = runner.invoke(app, ["validate", str(role_file)])
        assert result.exit_code == 0
        assert "Valid" in result.output
        # Non-TTY: no footer expected
        assert "Next steps" not in result.output

    def test_validate_explain_full_role(self, tmp_path):
        """--explain should describe each present section in plain language."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: explainer-test
            spec:
              role: You are a knowledge assistant that answers questions.
              model:
                provider: openai
                name: gpt-5-mini
              tools:
                - type: datetime
              ingest:
                sources:
                  - ./docs/**/*.md
              memory:
                max_sessions: 5
              guardrails:
                max_tool_calls: 10
                timeout_seconds: 120
        """)
        )
        result = runner.invoke(app, ["validate", str(role_file), "--explain"])
        assert result.exit_code == 0
        assert "Valid" in result.output
        assert "system prompt" in result.output
        assert "gpt-5-mini" in result.output
        assert "tool" in result.output.lower()
        assert "knowledge base" in result.output
        assert "memory" in result.output.lower()

    def test_validate_explain_minimal_role(self, tmp_path):
        """--explain on a minimal role should only show Role and Model."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: minimal-agent
            spec:
              role: You are helpful.
              model:
                provider: openai
                name: gpt-5-mini
        """)
        )
        result = runner.invoke(app, ["validate", str(role_file), "--explain"])
        assert result.exit_code == 0
        assert "Valid" in result.output
        assert "gpt-5-mini" in result.output
        # Optional sections should not appear
        assert "Memory" not in result.output
        assert "Ingest" not in result.output
        assert "Triggers" not in result.output

    def test_ingest_no_config_shows_hint(self, tmp_path):
        """Missing ingest config should show a hint."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-agent
            spec:
              role: Test
              model:
                provider: openai
                name: gpt-5-mini
        """)
        )
        result = runner.invoke(app, ["ingest", str(role_file)])
        assert result.exit_code == 1
        assert "Hint" in result.output
        assert "ingest:" in result.output


class TestErrorHints:
    """Tests for inline error hints across CLI commands."""

    def test_missing_role_path_hint(self):
        result = runner.invoke(app, ["validate", "/nonexistent/role.yaml"])
        assert result.exit_code == 1
        assert "Hint" in result.output

    def test_role_load_failure_hint(self, tmp_path):
        """Malformed role YAML should show a hint pointing to validate."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text("not: valid: yaml: content")
        result = runner.invoke(app, ["run", str(role_file), "-p", "hello", "--no-audit"])
        assert result.exit_code == 1
        assert "Hint" in result.output

    def test_memory_no_config_hint(self, tmp_path):
        """Missing memory config should show a hint."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-agent
            spec:
              role: Test
              model:
                provider: openai
                name: gpt-5-mini
        """)
        )
        result = runner.invoke(app, ["memory", "clear", str(role_file)])
        assert result.exit_code == 1
        assert "Hint" in result.output
        assert "memory:" in result.output

    def test_audit_db_not_found_hint(self, tmp_path):
        """Missing audit DB should show a hint."""
        result = runner.invoke(app, ["audit", "prune", "--audit-db", str(tmp_path / "missing.db")])
        assert result.exit_code == 1
        assert "Hint" in result.output
        assert "audit" in result.output.lower()

    def test_no_role_yaml_in_dir_hint(self, tmp_path):
        """Empty directory should show a hint about creating a role."""
        result = runner.invoke(app, ["validate", str(tmp_path)])
        assert result.exit_code == 1
        assert "Hint" in result.output
        assert "initrunner new" in result.output
