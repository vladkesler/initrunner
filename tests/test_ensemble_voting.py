"""Tests for ensemble judge voting in eval/judge.py."""

from __future__ import annotations

from unittest.mock import patch

from initrunner.eval.judge import (
    DEFAULT_VOTE_CRITERIA,
    JudgeCriterionResult,
    JudgeResult,
    VotingResult,
    ensemble_judge_vote_sync,
)


def _judge(passed_map: dict[str, bool]) -> JudgeResult:
    return JudgeResult(
        criteria_results=[
            JudgeCriterionResult(criterion=c, passed=p, reason="") for c, p in passed_map.items()
        ]
    )


class TestEnsembleJudgeVote:
    def test_highest_score_wins(self):
        criteria = ["clarity", "accuracy"]
        # output 0 passes both, output 1 passes one
        side_effects = [
            _judge({"clarity": True, "accuracy": True}),
            _judge({"clarity": True, "accuracy": False}),
        ]
        with patch("initrunner.eval.judge.run_judge_sync", side_effect=side_effects):
            result = ensemble_judge_vote_sync(["good", "ok"], criteria)
        assert isinstance(result, VotingResult)
        assert result.winning_index == 0
        assert result.votes[0] == {"clarity": 1, "accuracy": 1}
        assert result.votes[1] == {"clarity": 1, "accuracy": 0}

    def test_tie_breaks_on_lowest_index(self):
        criteria = ["clarity"]
        side_effects = [
            _judge({"clarity": True}),
            _judge({"clarity": True}),
        ]
        with patch("initrunner.eval.judge.run_judge_sync", side_effect=side_effects):
            result = ensemble_judge_vote_sync(["a", "b"], criteria)
        assert result.winning_index == 0

    def test_empty_outputs(self):
        result = ensemble_judge_vote_sync([], ["clarity"])
        assert result.winning_index == -1
        assert result.votes == {}
        assert "No candidate" in result.consensus_text

    def test_default_criteria_used_when_none(self):
        with patch(
            "initrunner.eval.judge.run_judge_sync",
            return_value=_judge(dict.fromkeys(DEFAULT_VOTE_CRITERIA, True)),
        ):
            result = ensemble_judge_vote_sync(["only"], None)
        assert result.criteria == DEFAULT_VOTE_CRITERIA
        assert result.winning_index == 0

    def test_to_dict_serializable(self):
        criteria = ["clarity"]
        with patch(
            "initrunner.eval.judge.run_judge_sync",
            return_value=_judge({"clarity": True}),
        ):
            result = ensemble_judge_vote_sync(["x"], criteria)
        d = result.to_dict()
        assert d["winning_index"] == 0
        assert d["criteria"] == ["clarity"]
        assert d["votes"] == {0: {"clarity": 1}}

    def test_consensus_text_reports_winner(self):
        criteria = ["c1", "c2"]
        side_effects = [
            _judge({"c1": False, "c2": False}),
            _judge({"c1": True, "c2": True}),
        ]
        with patch("initrunner.eval.judge.run_judge_sync", side_effect=side_effects):
            result = ensemble_judge_vote_sync(["weak", "strong"], criteria)
        assert result.winning_index == 1
        assert "Candidate 1 won" in result.consensus_text
        assert "2/2" in result.consensus_text
