"""Schema command: print the JSON Schema for agent files."""

from __future__ import annotations

import sys


def schema() -> None:
    """Print the JSON Schema for agent YAML files.

    Editors use it for completion and typo checks while you write an agent.
    Save a copy with: initrunner schema > agent.schema.json
    """
    from initrunner.agent.schema.json_schema import render_agent_schema

    sys.stdout.write(render_agent_schema())
