"""Tests for the examples CLI sub-commands and service layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from initrunner.examples import ExampleEntry, ExampleNotFoundError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CATALOG = [
    ExampleEntry(
        name="hello-world",
        category="role",
        description="A friendly greeter agent",
        tags=["example", "greeting"],
        files=["hello-world.yaml"],
        primary_file="hello-world.yaml",
        primary_content="apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: hello-world\n",
        multi_file=False,
        difficulty="beginner",
        features=[],
        tools=[],
    ),
    ExampleEntry(
        name="rag-agent",
        category="role",
        description="Knowledge base Q&A agent with document ingestion",
        tags=["example", "rag"],
        files=[
            "rag-agent/rag-agent.yaml",
            "rag-agent/docs/faq.md",
            "rag-agent/docs/getting-started.md",
        ],
        primary_file="rag-agent/rag-agent.yaml",
        primary_content="apiVersion: initrunner/v1\nkind: Agent\nmetadata:\n  name: rag-agent\n",
        multi_file=True,
        difficulty="advanced",
        features=["ingestion"],
        tools=["filesystem"],
    ),
    ExampleEntry(
        name="email-pipeline",
        category="compose",
        description="Multi-agent email processing pipeline",
        tags=["example", "compose"],
        files=["compose.yaml", "roles/triager.yaml"],
        primary_file="compose.yaml",
        primary_content="apiVersion: initrunner/v1\nkind: Compose\n",
        multi_file=True,
        difficulty="advanced",
        features=["compose"],
        tools=[],
    ),
    ExampleEntry(
        name="code-tools",
        category="skill",
        description="Code execution and file browsing tools",
        tags=["code", "development"],
        files=["code-tools.md"],
        primary_file="code-tools.md",
        primary_content="---\nname: code-tools\n---\nPrompt body.\n",
        multi_file=False,
        difficulty="beginner",
        features=["skills"],
        tools=["filesystem", "python"],
    ),
]


def _mock_load_catalog():
    return list(SAMPLE_CATALOG)


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------


class TestExamplesService:
    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_list_examples_all(self):
        from initrunner.examples import list_examples

        results = list_examples()
        assert len(results) == 4

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_list_examples_filter_category(self):
        from initrunner.examples import list_examples

        results = list_examples(category="role")
        assert len(results) == 2
        assert all(e.category == "role" for e in results)

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_list_examples_filter_tag(self):
        from initrunner.examples import list_examples

        results = list_examples(tag="rag")
        assert len(results) == 1
        assert results[0].name == "rag-agent"

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_list_examples_filter_no_match(self):
        from initrunner.examples import list_examples

        results = list_examples(category="role", tag="nonexistent")
        assert len(results) == 0

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_get_example_found(self):
        from initrunner.examples import get_example

        entry = get_example("hello-world")
        assert entry.name == "hello-world"
        assert entry.category == "role"

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_get_example_not_found(self):
        from initrunner.examples import get_example

        with pytest.raises(ExampleNotFoundError, match="not-real"):
            get_example("not-real")

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_show_example(self):
        from initrunner.examples import show_example

        content = show_example("hello-world")
        assert "initrunner/v1" in content

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_copy_single_file(self, tmp_path: Path):
        from initrunner.examples import copy_example

        written = copy_example("hello-world", tmp_path)
        assert len(written) == 1
        assert written[0].exists()
        assert "initrunner/v1" in written[0].read_text()

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_copy_refuses_overwrite(self, tmp_path: Path):
        from initrunner.examples import copy_example

        # Create the file first
        (tmp_path / "hello-world.yaml").write_text("existing")

        with pytest.raises(FileExistsError, match="already exists"):
            copy_example("hello-world", tmp_path)

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_copy_not_found(self, tmp_path: Path):
        from initrunner.examples import copy_example

        with pytest.raises(ExampleNotFoundError):
            copy_example("nope", tmp_path)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestExamplesCLI:
    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_list_all(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["examples", "list"])
        assert result.exit_code == 0
        assert "hello-world" in result.output
        assert "rag-agent" in result.output
        assert "email-pipeline" in result.output
        assert "code-tools" in result.output

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_list_filter_category(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["examples", "list", "--category", "skill"])
        assert result.exit_code == 0
        assert "code-tools" in result.output
        assert "hello-world" not in result.output

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_list_filter_tag(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["examples", "list", "--tag", "greeting"])
        assert result.exit_code == 0
        assert "hello-world" in result.output
        assert "rag-agent" not in result.output

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_list_empty(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        with patch("initrunner.examples._load_catalog", return_value=[]):
            runner = CliRunner()
            result = runner.invoke(app, ["examples", "list"])
            assert result.exit_code == 0
            assert "No examples found" in result.output

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_show_displays_content(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["examples", "show", "hello-world"])
        assert result.exit_code == 0
        assert "initrunner/v1" in result.output

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_show_unknown_name(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["examples", "show", "nonexistent"])
        assert result.exit_code == 1
        assert "Error" in result.output

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_show_multi_file_hint(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["examples", "show", "rag-agent"])
        assert result.exit_code == 0
        assert "multi-file" in result.output

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_copy_single_file(self, tmp_path: Path):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["examples", "copy", "hello-world", "--output", str(tmp_path)])
        assert result.exit_code == 0
        assert "Copied 1 file" in result.output
        assert (tmp_path / "hello-world.yaml").exists()

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_copy_refuses_overwrite(self, tmp_path: Path):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        (tmp_path / "hello-world.yaml").write_text("existing")

        runner = CliRunner()
        result = runner.invoke(app, ["examples", "copy", "hello-world", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "already exists" in result.output

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_copy_unknown_name(self, tmp_path: Path):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["examples", "copy", "nope", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "Error" in result.output

    @patch("initrunner.examples._load_catalog", _mock_load_catalog)
    def test_copy_shows_next_steps(self, tmp_path: Path):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["examples", "copy", "hello-world", "--output", str(tmp_path)])
        assert result.exit_code == 0
        assert "initrunner validate" in result.output
        assert "initrunner run" in result.output
