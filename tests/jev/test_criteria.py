"""jev_judge criteria: one Noul per criterion, statuses from the threshold."""

from __future__ import annotations

import pytest

import initrunner.jev as jev
from initrunner.jev import Judgment
from initrunner.jev import questions as q
from initrunner.jev.criteria import judge_criteria


def _answers(monkeypatch, probabilities: list[float]):
    calls: list[tuple[dict, dict]] = []

    def _ask(state, questions):
        calls.append((state, questions))
        return Judgment(
            nouls={f"criterion::{i}": p for i, p in enumerate(probabilities)}, model="jev-1.13.0"
        )

    monkeypatch.setattr(jev, "ask", _ask)
    return calls


def test_statuses_follow_the_threshold(monkeypatch):
    _answers(monkeypatch, [0.95, 0.5, 0.1])
    verdict = judge_criteria("p", "o", ["a", "b", "c"])
    assert [r.status for r in verdict.results] == ["pass", "uncertain", "fail"]
    assert verdict.passed is False
    assert verdict.summary.startswith("1/3 criteria met")
    assert "uncertain 0.50: b" in verdict.summary


def test_all_met_passes(monkeypatch):
    _answers(monkeypatch, [0.95, 0.9])
    assert judge_criteria("p", "o", ["a", "b"]).passed is True


def test_custom_threshold(monkeypatch):
    _answers(monkeypatch, [0.6])
    assert judge_criteria("p", "o", ["a"], threshold=0.5).passed is True
    assert judge_criteria("p", "o", ["a"], threshold=0.7).passed is False


def test_one_request_prompt_before_output(monkeypatch):
    calls = _answers(monkeypatch, [0.9, 0.9, 0.9])
    judge_criteria("Explain REST", "REST is...", ["a", "b", "c"])
    assert len(calls) == 1
    state, questions = calls[0]
    assert list(state) == ["prompt", "output"]
    assert set(questions) == {"criterion::0", "criterion::1", "criterion::2"}
    assert questions["criterion::1"]["instructions"] == "Does `output` meet this criterion: b"


def test_long_output_is_capped(monkeypatch):
    calls = _answers(monkeypatch, [0.9])
    judge_criteria("p", "x" * (q.EVAL_OUTPUT_CHARS + 500), ["a"])
    assert calls[0][0]["output"].endswith("[truncated]")


def test_jev_error_propagates(monkeypatch):
    def _fail(state, questions):
        raise jev.JevError("down")

    monkeypatch.setattr(jev, "ask", _fail)
    with pytest.raises(jev.JevError):
        judge_criteria("p", "o", ["a"])
