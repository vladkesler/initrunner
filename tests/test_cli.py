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


class TestInit:
    def test_creates_file(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(app, ["init", "--name", "my-agent", "--output", str(output)])
        assert result.exit_code == 0
        assert output.exists()
        content = output.read_text()
        assert "my-agent" in content
        assert "initrunner/v1" in content

    def test_refuses_overwrite(self, tmp_path):
        output = tmp_path / "role.yaml"
        output.write_text("existing content")
        result = runner.invoke(app, ["init", "--output", str(output)])
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_default_name(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(app, ["init", "--output", str(output)])
        assert result.exit_code == 0
        content = output.read_text()
        assert "my-agent" in content

    def test_init_validates(self, tmp_path):
        """The generated template should itself be valid."""
        output = tmp_path / "role.yaml"
        runner.invoke(app, ["init", "--output", str(output)])
        result = runner.invoke(app, ["validate", str(output)])
        assert result.exit_code == 0
        assert "Valid" in result.output

    def test_rag_template(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(app, ["init", "--template", "rag", "--output", str(output)])
        assert result.exit_code == 0
        content = output.read_text()
        assert "ingest" in content
        assert "search_documents" in content

    def test_rag_template_validates(self, tmp_path):
        output = tmp_path / "role.yaml"
        runner.invoke(app, ["init", "--template", "rag", "--output", str(output)])
        result = runner.invoke(app, ["validate", str(output)])
        assert result.exit_code == 0

    def test_daemon_template(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(app, ["init", "--template", "daemon", "--output", str(output)])
        assert result.exit_code == 0
        content = output.read_text()
        assert "triggers" in content
        assert "file_watch" in content

    def test_daemon_template_validates(self, tmp_path):
        output = tmp_path / "role.yaml"
        runner.invoke(app, ["init", "--template", "daemon", "--output", str(output)])
        result = runner.invoke(app, ["validate", str(output)])
        assert result.exit_code == 0

    def test_invalid_template(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(app, ["init", "--template", "invalid", "--output", str(output)])
        assert result.exit_code == 1

    def test_provider_hint(self, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(app, ["init", "--provider", "anthropic", "--output", str(output)])
        assert result.exit_code == 0
        assert "pip install" in result.output

    @patch("initrunner.cli.role_cmd.check_ollama_running")
    def test_ollama_template(self, mock_ping, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(app, ["init", "--template", "ollama", "--output", str(output)])
        assert result.exit_code == 0
        content = output.read_text()
        assert "ollama" in content
        assert "llama3.2" in content
        mock_ping.assert_called_once()

    @patch("initrunner.cli.role_cmd.check_ollama_running")
    def test_ollama_template_validates(self, mock_ping, tmp_path):
        output = tmp_path / "role.yaml"
        runner.invoke(app, ["init", "--template", "ollama", "--output", str(output)])
        result = runner.invoke(app, ["validate", str(output)])
        assert result.exit_code == 0
        assert "Valid" in result.output

    @patch("initrunner.cli.role_cmd.check_ollama_running")
    def test_ollama_provider_no_pip_hint(self, mock_ping, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(app, ["init", "--provider", "ollama", "--output", str(output)])
        assert result.exit_code == 0
        assert "pip install" not in result.output

    @patch("urllib.request.urlopen", side_effect=Exception("Connection refused"))
    def test_ollama_ping_warns_when_down(self, mock_urlopen, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(app, ["init", "--template", "ollama", "--output", str(output)])
        assert result.exit_code == 0
        assert "ollama serve" in result.output

    @patch("urllib.request.urlopen")
    def test_ollama_ping_no_warning_when_up(self, mock_urlopen, tmp_path):
        output = tmp_path / "role.yaml"
        result = runner.invoke(app, ["init", "--template", "ollama", "--output", str(output)])
        assert result.exit_code == 0
        assert "ollama serve" not in result.output


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

        result = runner.invoke(app, ["run", str(role_file), "-p", "hello", "--no-audit"])
        assert result.exit_code == 0
        mock_run_single.assert_called_once()

    def test_no_role_no_sense_errors(self):
        """Running without a role file and without --sense should error."""
        result = runner.invoke(app, ["run", "-p", "hello"])
        assert result.exit_code == 1
        assert "--sense" in result.output

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

        result = runner.invoke(app, ["run", "--sense", "-p", "test task", "--no-audit"])
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

        result = runner.invoke(
            app,
            ["run", "--sense", "--confirm-role", "-p", "task", "--no-audit"],
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


class TestDaemon:
    def test_missing_role_file(self):
        result = runner.invoke(app, ["daemon", "/nonexistent/role.yaml"])
        assert result.exit_code == 1
