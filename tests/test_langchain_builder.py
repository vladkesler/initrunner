"""Tests for LangChain import integration with BuilderSession and CLI."""

from __future__ import annotations

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
      description: Imported from LangChain
      spec_version: 2
    spec:
      role: You are a helpful weather assistant.
      model:
        provider: openai
        name: gpt-5
      tools:
        - type: custom
          module: _langchain_tools
""")

_VALID_YAML_NO_TOOLS = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: simple-bot
      description: Imported from LangChain
      spec_version: 2
    spec:
      role: You are a helpful assistant.
      model:
        provider: openai
        name: gpt-5
""")

_LC_SOURCE_WITH_TOOLS = textwrap.dedent("""\
    import json
    from langchain.agents import create_agent
    from langchain.tools import tool

    @tool
    def get_weather(city: str) -> str:
        \"\"\"Get current weather for a city.\"\"\"
        return f"Sunny in {city}"

    agent = create_agent(
        model="openai:gpt-5",
        tools=[get_weather],
        system_prompt="You are a helpful weather assistant.",
    )
""")

_LC_SOURCE_NO_TOOLS = textwrap.dedent("""\
    from langchain.agents import create_agent

    agent = create_agent(
        model="openai:gpt-5",
        tools=[],
        system_prompt="You are a helpful assistant.",
    )
""")

_LC_SOURCE_WITH_MEMORY = textwrap.dedent("""\
    from langchain.agents import create_agent
    from langchain.memory import ConversationBufferMemory
    from langchain.tools import tool

    memory = ConversationBufferMemory()

    @tool
    def greet(name: str) -> str:
        \"\"\"Greet someone.\"\"\"
        return f"Hello {name}"

    agent = create_agent("openai:gpt-5", tools=[greet])
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


def _patch_llm():
    """Decorator stack that patches the LLM calls in seed_from_langchain."""
    # Agent and _build_model are imported locally inside seed_from_langchain,
    # so we patch at their source modules.
    return [
        patch("pydantic_ai.Agent", side_effect=lambda *a, **kw: _make_fake_agent("")),
        patch("initrunner.agent.loader._build_model", return_value=MagicMock()),
    ]


def _apply_patches(response_text: str):
    """Return a pair of patch context managers with a pre-set LLM response."""
    fake = _make_fake_agent(response_text)
    p1 = patch("pydantic_ai.Agent", return_value=fake)
    p2 = patch("initrunner.agent.loader._build_model", return_value=MagicMock())
    return p1, p2


# ---------------------------------------------------------------------------
# BuilderSession.seed_from_langchain
# ---------------------------------------------------------------------------


class TestSeedFromLangchain:
    def test_basic_import(self, tmp_path):
        """Basic LangChain file produces valid YAML and sidecar."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_LC_SOURCE_WITH_TOOLS)

        response = f"Here is your agent:\n\n```yaml\n{_VALID_YAML}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            turn = session.seed_from_langchain(source_file, "openai")

        assert turn.yaml_text
        assert session._sidecar_source is not None
        assert "def get_weather" in session._sidecar_source
        assert session.seed_source == f"langchain:{source_file}"

    def test_no_tools_no_sidecar(self, tmp_path):
        """Source with no @tool functions produces no sidecar."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_LC_SOURCE_NO_TOOLS)

        response = f"```yaml\n{_VALID_YAML_NO_TOOLS}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            turn = session.seed_from_langchain(source_file, "openai")

        assert turn.yaml_text
        assert session._sidecar_source is None

    def test_import_warnings_surfaced(self, tmp_path):
        """Unsupported features produce import warnings in TurnResult."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_LC_SOURCE_WITH_MEMORY)

        response = f"```yaml\n{_VALID_YAML}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            turn = session.seed_from_langchain(source_file, "openai")

        assert len(turn.import_warnings) > 0
        assert any("memory" in w.lower() for w in turn.import_warnings)

    def test_sidecar_strips_langchain_imports(self, tmp_path):
        """Sidecar module should not contain LangChain imports."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_LC_SOURCE_WITH_TOOLS)

        response = f"```yaml\n{_VALID_YAML}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            session.seed_from_langchain(source_file, "openai")

        assert session._sidecar_source is not None
        assert "from langchain" not in session._sidecar_source
        assert "import json" in session._sidecar_source


# ---------------------------------------------------------------------------
# BuilderSession.save with sidecar
# ---------------------------------------------------------------------------


class TestSaveWithSidecar:
    def test_save_writes_sidecar(self, tmp_path):
        """Save writes both YAML and sidecar .py file."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_LC_SOURCE_WITH_TOOLS)

        response = f"```yaml\n{_VALID_YAML}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            session.seed_from_langchain(source_file, "openai")

        output_path = tmp_path / "role.yaml"
        result = session.save(output_path)

        # YAML written
        assert output_path.exists()
        # Sidecar written with stem-derived name
        sidecar_path = tmp_path / "role_tools.py"
        assert sidecar_path.exists()
        assert "def get_weather" in sidecar_path.read_text()
        # Module reference in YAML should match
        yaml_content = output_path.read_text()
        assert "role_tools" in yaml_content
        assert "_langchain_tools" not in yaml_content
        # Generated assets reported
        assert str(sidecar_path) in result.generated_assets

    def test_sidecar_name_follows_yaml_stem(self, tmp_path):
        """Sidecar filename is derived from the output YAML stem."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_LC_SOURCE_WITH_TOOLS)

        response = f"```yaml\n{_VALID_YAML}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            session.seed_from_langchain(source_file, "openai")

        output_path = tmp_path / "my-weather-agent.yaml"
        session.save(output_path)

        # Hyphens in stem are sanitized to underscores for valid Python module name
        sidecar_path = tmp_path / "my_weather_agent_tools.py"
        assert sidecar_path.exists()

    def test_save_without_sidecar(self, tmp_path):
        """Save without custom tools produces no sidecar file."""
        source_file = tmp_path / "agent.py"
        source_file.write_text(_LC_SOURCE_NO_TOOLS)

        response = f"```yaml\n{_VALID_YAML_NO_TOOLS}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            session.seed_from_langchain(source_file, "openai")

        output_path = tmp_path / "role.yaml"
        result = session.save(output_path)

        assert output_path.exists()
        assert not (tmp_path / "role_tools.py").exists()
        assert result.generated_assets == []


# ---------------------------------------------------------------------------
# CLI --langchain flag
# ---------------------------------------------------------------------------


class TestCLILangchain:
    def test_langchain_and_blank_errors(self, tmp_path):
        """--langchain and --blank are mutually exclusive."""
        output = tmp_path / "role.yaml"
        lc_file = tmp_path / "agent.py"
        lc_file.write_text(_LC_SOURCE_NO_TOOLS)
        result = runner.invoke(
            app,
            [
                "new",
                "--langchain",
                str(lc_file),
                "--blank",
                "--output",
                str(output),
                "--no-refine",
            ],
        )
        assert result.exit_code == 1
        assert "at most one" in result.output.lower()

    def test_langchain_and_description_errors(self, tmp_path):
        """--langchain and description are mutually exclusive."""
        output = tmp_path / "role.yaml"
        lc_file = tmp_path / "agent.py"
        lc_file.write_text(_LC_SOURCE_NO_TOOLS)
        result = runner.invoke(
            app,
            [
                "new",
                "a chatbot",
                "--langchain",
                str(lc_file),
                "--output",
                str(output),
                "--no-refine",
            ],
        )
        assert result.exit_code == 1

    def test_langchain_file_not_found(self, tmp_path):
        """Non-existent LangChain file produces error."""
        output = tmp_path / "role.yaml"
        result = runner.invoke(
            app,
            [
                "new",
                "--langchain",
                "/nonexistent/agent.py",
                "--output",
                str(output),
                "--no-refine",
            ],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_langchain_in_help(self):
        """--langchain flag appears in help output."""
        result = runner.invoke(app, ["new", "--help"])
        assert "--langchain" in result.output


# ---------------------------------------------------------------------------
# Blocked import warnings
# ---------------------------------------------------------------------------


class TestBlockedImportWarnings:
    def test_blocked_imports_warned(self, tmp_path):
        """Custom tools importing blocked modules produce warnings."""
        source = textwrap.dedent("""\
            import os
            from langchain.tools import tool

            @tool
            def list_files(path: str) -> str:
                \"\"\"List files in directory.\"\"\"
                return str(os.listdir(path))

            from langchain.agents import create_agent
            agent = create_agent("openai:gpt-5", tools=[list_files])
        """)
        source_file = tmp_path / "agent.py"
        source_file.write_text(source)

        response = f"```yaml\n{_VALID_YAML}```"
        p1, p2 = _apply_patches(response)

        with p1, p2:
            session = BuilderSession()
            turn = session.seed_from_langchain(source_file, "openai")

        assert any("blocked" in w.lower() for w in turn.import_warnings)
