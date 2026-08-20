"""What a core install must not import.

MCP and LanceDB are optional extras because they are the two heaviest things
in the dependency tree (the MCP client stack alone is about a quarter of a
plain agent's RSS, and it loads eagerly the moment fastmcp is importable).
That only holds if nothing on the ordinary build path reaches for them, so
this asserts on ``sys.modules`` rather than on megabytes: module names are
deterministic across platforms and allocators, RSS numbers are not.

Runs in every environment. The extras-absent half is skipped when the extras
are installed; CI has a lean job that runs it for real.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HELLO_WORLD = REPO_ROOT / "examples" / "roles" / "hello-world.yaml"

LEAN_INSTALL = (
    importlib.util.find_spec("fastmcp") is None and importlib.util.find_spec("lancedb") is None
)

_PROBE = """
import json, sys

from initrunner.agent.loader import load_and_build
from initrunner.agent.tools._registry import get_tool_types

tool_types = sorted(get_tool_types())
role, agent = load_and_build(PATH, model_override="openai:gpt-4o-mini")

print(json.dumps({
    "tool_types": tool_types,
    "agent_name": role.metadata.name,
    "modules": sorted(sys.modules),
}))
"""


def _probe(tmp_path: Path) -> dict:
    """Build the hello-world agent in a fresh interpreter, report sys.modules."""
    source = f"PATH = __import__('pathlib').Path({str(HELLO_WORLD)!r})\n" + textwrap.dedent(_PROBE)
    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=REPO_ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "OPENAI_API_KEY": "sk-test",
            "INITRUNNER_HOME": str(tmp_path / "initrunner"),
            "INITRUNNER_NO_TELEMETRY_PROMPT": "1",
            "INITRUNNER_TELEMETRY": "0",
        },
    )
    assert result.returncode == 0, f"probe failed:\n{result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> dict:
    return _probe(tmp_path_factory.mktemp("footprint"))


class TestCoreFootprint:
    def test_mcp_tool_type_is_registered(self, probe):
        """``type: mcp`` must validate everywhere, extra installed or not."""
        assert "mcp" in probe["tool_types"]

    def test_agent_builds(self, probe):
        assert probe["agent_name"] == "hello-world"

    def test_mcp_implementation_not_imported(self, probe):
        """Registration goes through the shim; the MCPToolset wrapper stays cold."""
        assert "initrunner.mcp.server" not in probe["modules"]

    def test_vector_store_not_imported(self, probe):
        """A role without memory or ingest never touches LanceDB."""
        modules = probe["modules"]
        assert "lancedb" not in modules
        assert "pyarrow" not in modules
        assert "initrunner.stores.lance_store" not in modules

    @pytest.mark.skipif(not LEAN_INSTALL, reason="mcp/vector extras are installed")
    def test_mcp_stack_absent_in_a_lean_install(self, probe):
        """The whole point: no fastmcp means pydantic_ai stops importing it."""
        modules = probe["modules"]
        for name in ("fastmcp", "pydantic_ai.mcp", "mcp", "beartype"):
            assert name not in modules, f"{name} was imported by a core install"

    @pytest.mark.skipif(not LEAN_INSTALL, reason="mcp/vector extras are installed")
    def test_serve_stack_is_core(self):
        """starlette and uvicorn used to arrive via the MCP SDK; they are core now."""
        assert importlib.util.find_spec("starlette") is not None
        assert importlib.util.find_spec("uvicorn") is not None

    def test_cli_imports_cleanly(self, tmp_path):
        """``initrunner --help`` must work without any extra installed."""
        result = subprocess.run(
            [sys.executable, "-c", "from initrunner.cli.main import app; print(app.info.name)"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=REPO_ROOT,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(tmp_path),
                "INITRUNNER_HOME": str(tmp_path / "initrunner"),
                "INITRUNNER_NO_TELEMETRY_PROMPT": "1",
                "INITRUNNER_TELEMETRY": "0",
            },
        )
        assert result.returncode == 0, result.stderr
        assert "initrunner" in result.stdout
