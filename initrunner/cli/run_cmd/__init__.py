"""Run command: unified dispatcher for agent, team, flow, and ephemeral modes."""

from initrunner.cli.run_cmd._command import run
from initrunner.cli.run_cmd._removed import RunCommand

__all__ = ["RunCommand", "run"]
