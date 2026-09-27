"""The intent-sensing panel names the method, and shows a runner-up when Jev is unsure."""

from __future__ import annotations

from pathlib import Path

from initrunner.cli._helpers._console import console
from initrunner.cli._helpers._display import display_sense_result
from initrunner.services.role_selector import RoleCandidate, SelectionResult


def _candidate(name: str) -> RoleCandidate:
    return RoleCandidate(path=Path(f"roles/{name}.yaml"), name=name, description="", tags=[])


def _render(result: SelectionResult) -> str:
    with console.capture() as cap:
        display_sense_result(result)
    return cap.get()


def test_jev_method_shows_confidence():
    out = _render(
        SelectionResult(
            candidate=_candidate("changelog-generator"),
            method="jev",
            confidence=0.78,
            runner_up=_candidate("changelog-slack"),
        )
    )
    assert "Jev (confidence 0.78)" in out
    assert "fallback" not in out
    assert "Runner-up" not in out  # confident enough to hide it


def test_low_confidence_shows_runner_up():
    out = _render(
        SelectionResult(
            candidate=_candidate("pr-reviewer"),
            method="jev",
            confidence=0.54,
            runner_up=_candidate("code-reviewer"),
        )
    )
    assert "Runner-up" in out
    assert "code-reviewer" in out
