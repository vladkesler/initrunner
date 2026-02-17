"""Tests for the CLI."""

import textwrap
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()


class TestVersion:
    def test_version(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.4.0" in result.output


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
                name: gpt-4o-mini
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
                name: gpt-4o-mini
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
                name: gpt-4o-mini
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
                name: gpt-4o-mini
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
                name: gpt-4o-mini
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
                    model="gpt-4o-mini",
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
                    model="gpt-4o-mini",
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


class TestDaemon:
    def test_missing_role_file(self):
        result = runner.invoke(app, ["daemon", "/nonexistent/role.yaml"])
        assert result.exit_code == 1
