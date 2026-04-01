"""Tests for PydanticAI import integration with BuilderSession and CLI."""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from initrunner.cli.main import app
from initrunner.services.agent_builder import BuilderSession

runner = CliRunner()

_VALID_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: weather-bot
      description: Imported from PydanticAI
      spec_version: 2
    spec:
      role: You are a helpful weather assistant.
      model:
        provider: openai
        name: gpt-5
      tools:
        - type: custom
          module: _pydanticai_tools
""")

_VALID_YAML_NO_TOOLS = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: simple-bot
      description: Imported from PydanticAI
      spec_version: 2
    spec:
      role: You are a helpful assistant.
      model:
        provider: openai
        name: gpt-5
""")

_PAI_SOURCE_WITH_TOOLS = textwrap.dedent("""\
    import httpx
    from pydantic_ai import Agent, RunContext

    agent = Agent("openai:gpt-5", system_prompt="You are a helpful weather assistant.")

    @agent.tool
    def get_weather(ctx: RunContext[str], city: str) -> str:
        \"\"\"Get current weather for a city.\"\"\"
        return f"Sunny in {city}"
""")

_PAI_SOURCE_NO_TOOLS = textwrap.dedent("""\
    from pydantic_ai import Agent

    agent = Agent("openai:gpt-5", system_prompt="You are a helpful assistant.")
""")

_PAI_SOURCE_WITH_LOGFIRE = textwrap.dedent("""\
    import logfire
    from pydantic_ai import Agent

    agent = Agent("openai:gpt-5", instrument=True)

    @agent.tool_plain
    def greet(name: str) -> str:
        \"\"\"Greet someone.\"\"\"
        return f"Hello {name}"
""")


@dataclass
class _FakeResult:
    """Mimics pydantic_ai RunResult for testing."""

    output: str
    _messages: list

    def all_messages(self):
        return self._messages


def _make_fake_agent(response_text: str):
    """Create a mock PydanticAI Agent that returns a canned response."""
    agent = MagicMock()
    agent.run_sync.return_value = _FakeResult(
        output=response_text,
        _messages=[{"role": "assistant", "content": response_text}],
    )
    return agent


def _apply_patches(response_text: str):
    """Return a pair of patch context managers with a pre-set LLM response."""
    fake = _make_fake_agent(response_text)
    p1 = patch("pydantic_ai.Agent", return_value=fake)
    p2 = patch("initrunner.agent.loader._build_model", return_value=MagicMock())
    return p1, p2


# ---------------------------------------------------------------------------
# BuilderSession.seed_from_pydanticai
# ---------------------------------------------------------------------------


class TestSeedFromPydanticAI:
    def test_basic_import(self, tmp_path):
        """Basic PydanticAI file produces valid YAML and sidecar."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_PAI_SOURCE_WITH_TOOLS)

        response = f"Here is your agent:\n\n```yaml\n{_VALID_YAML}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            turn = session.seed_from_pydanticai(source_file, "openai")

        assert turn.yaml_text
        assert session._sidecar_source is not None
        assert "def get_weather" in session._sidecar_source
        assert session.seed_source == f"pydanticai:{source_file}"

    def test_no_tools_no_sidecar(self, tmp_path):
        """Source with no tool functions produces no sidecar."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_PAI_SOURCE_NO_TOOLS)

        response = f"```yaml\n{_VALID_YAML_NO_TOOLS}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            turn = session.seed_from_pydanticai(source_file, "openai")

        assert turn.yaml_text
        assert session._sidecar_source is None

    def test_import_warnings_surfaced(self, tmp_path):
        """Unsupported features produce import warnings in TurnResult."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_PAI_SOURCE_WITH_LOGFIRE)

        response = f"```yaml\n{_VALID_YAML}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            turn = session.seed_from_pydanticai(source_file, "openai")

        assert len(turn.import_warnings) > 0
        assert any(
            "logfire" in w.lower() or "observability" in w.lower() for w in turn.import_warnings
        )

    def test_sidecar_strips_pydanticai_imports(self, tmp_path):
        """Sidecar module should not contain PydanticAI imports."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_PAI_SOURCE_WITH_TOOLS)

        response = f"```yaml\n{_VALID_YAML}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            session.seed_from_pydanticai(source_file, "openai")

        assert session._sidecar_source is not None
        assert "from pydantic_ai" not in session._sidecar_source
        assert "import httpx" in session._sidecar_source


# ---------------------------------------------------------------------------
# BuilderSession.save with sidecar
# ---------------------------------------------------------------------------


class TestSaveWithSidecar:
    def test_save_writes_sidecar(self, tmp_path):
        """Save writes both YAML and sidecar .py file."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_PAI_SOURCE_WITH_TOOLS)

        response = f"```yaml\n{_VALID_YAML}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            session.seed_from_pydanticai(source_file, "openai")

        output_path = tmp_path / "role.yaml"
        result = session.save(output_path)

        assert output_path.exists()
        sidecar_path = tmp_path / "role_tools.py"
        assert sidecar_path.exists()
        assert "def get_weather" in sidecar_path.read_text()
        yaml_content = output_path.read_text()
        assert "role_tools" in yaml_content
        assert "_pydanticai_tools" not in yaml_content
        assert str(sidecar_path) in result.generated_assets

    def test_sidecar_name_follows_yaml_stem(self, tmp_path):
        """Sidecar filename is derived from the output YAML stem."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_PAI_SOURCE_WITH_TOOLS)

        response = f"```yaml\n{_VALID_YAML}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            session.seed_from_pydanticai(source_file, "openai")

        output_path = tmp_path / "my-weather-agent.yaml"
        session.save(output_path)

        sidecar_path = tmp_path / "my_weather_agent_tools.py"
        assert sidecar_path.exists()

    def test_save_without_sidecar(self, tmp_path):
        """Save without custom tools produces no sidecar file."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_PAI_SOURCE_NO_TOOLS)

        response = f"```yaml\n{_VALID_YAML_NO_TOOLS}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            session.seed_from_pydanticai(source_file, "openai")

        output_path = tmp_path / "role.yaml"
        result = session.save(output_path)

        assert output_path.exists()
        assert not (tmp_path / "role_tools.py").exists()
        assert result.generated_assets == []


# ---------------------------------------------------------------------------
# CLI --pydantic-ai flag
# ---------------------------------------------------------------------------


class TestCLIPydanticAI:
    def test_pydantic_ai_and_blank_errors(self, tmp_path):
        """--pydantic-ai and --blank are mutually exclusive."""
        output = tmp_path / "role.yaml"
        pai_file = tmp_path / "agent.py"
        pai_file.write_text(_PAI_SOURCE_NO_TOOLS)
        result = runner.invoke(
            app,
            [
                "new",
                "--pydantic-ai",
                str(pai_file),
                "--blank",
                "--output",
                str(output),
                "--no-refine",
            ],
        )
        assert result.exit_code == 1
        assert "at most one" in result.output.lower()

    def test_pydantic_ai_and_langchain_errors(self, tmp_path):
        """--pydantic-ai and --langchain are mutually exclusive."""
        output = tmp_path / "role.yaml"
        pai_file = tmp_path / "agent.py"
        pai_file.write_text(_PAI_SOURCE_NO_TOOLS)
        result = runner.invoke(
            app,
            [
                "new",
                "--pydantic-ai",
                str(pai_file),
                "--langchain",
                str(pai_file),
                "--output",
                str(output),
                "--no-refine",
            ],
        )
        assert result.exit_code == 1
        assert "at most one" in result.output.lower()

    def test_pydantic_ai_file_not_found(self, tmp_path):
        """Non-existent PydanticAI file produces error."""
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            [
                "new",
                "--pydantic-ai",
                "/nonexistent/agent.py",
                "--output",
                str(output),
                "--no-refine",
            ],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_pydantic_ai_in_help(self):
        """--pydantic-ai flag appears in help output."""
        result = runner.invoke(app, ["new", "--help"])
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "--pydantic-ai" in plain


# ---------------------------------------------------------------------------
# Blocked import warnings
# ---------------------------------------------------------------------------


class TestBlockedImportWarnings:
    def test_blocked_imports_warned(self, tmp_path):
        """Custom tools importing blocked modules produce warnings."""
        source = textwrap.dedent("""\
            import os
            from pydantic_ai import Agent

            agent = Agent("openai:gpt-5")

            @agent.tool_plain
            def list_files(path: str) -> str:
                \"\"\"List files in directory.\"\"\"
                return str(os.listdir(path))
        """)
        source_file = tmp_path / "agent.py"
        source_file.write_text(source)

        response = f"```yaml\n{_VALID_YAML}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            turn = session.seed_from_pydanticai(source_file, "openai")

        assert any("blocked" in w.lower() for w in turn.import_warnings)
