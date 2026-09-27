"""Every question InitRunner asks Jev, and every threshold that acts on the answers.

The thresholds are calibrated against :data:`MODEL`. Before moving to a new Jev
version, re-run ``tests/jev/test_live.py`` and re-tune anything it flags.

Questions use the SDK's documented dict form (``{"type": "choice", ...}``) so this
module imports without the ``jev`` extra installed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MODEL = "jev-1.13.0"

Question = dict[str, Any]

# ---------------------------------------------------------------------------
# Routing: which agent should handle a task
# ---------------------------------------------------------------------------

ROUTE_KEY = "agent"
NONE_OF_THESE = "none_of_these"
# Below this probability for the chosen agent, the sense panel shows the
# runner-up so the person confirming the pick sees the alternative.
ROUTE_CONFIDENT = 0.6
# A Choice takes up to 255 options; one is reserved for NONE_OF_THESE.
ROUTE_MAX_OPTIONS = 250


def route(options: Mapping[str, str]) -> dict[str, Question]:
    """One Choice over the candidate agents, keyed by agent name.

    *options* maps each agent's key to a one-line description of what it does.
    ``none_of_these`` soaks up probability when no agent fits, which keeps the
    real options honest even when the caller ignores it.
    """
    criteria: dict[str, str] = dict(options)
    criteria[NONE_OF_THESE] = "No agent above is built for this task."
    return {
        ROUTE_KEY: {
            "type": "choice",
            "instructions": "Which agent is the best fit to carry out `task`?",
            "criteria": criteria,
        }
    }
