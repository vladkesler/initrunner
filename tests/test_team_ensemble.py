"""Tests for the ensemble team strategy (majority / weighted / judge)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from initrunner.agent.executor import RunResult
from initrunner.eval.judge import VotingResult
from initrunner.team.graph import run_team_graph_sync
from initrunner.team.schema import TeamDefinition, TeamEnsembleConfig


def _make_team(ensemble: dict, personas: dict | None = None) -> TeamDefinition:
    if personas is None:
        personas = {
            "alpha": "first persona role",
            "beta": "second persona role",
            "gamma": "third persona role",
        }
    data = {
        "apiVersion": "initrunner/v1",
        "kind": "Team",
        "metadata": {"name": "ens-team"},
        "spec": {
            "model": {"provider": "openai", "name": "gpt-5-mini"},
            "personas": personas,
            "strategy": "ensemble",
            "ensemble": ensemble,
        },
    }
    return TeamDefinition.model_validate(data)


def _exec_for(outputs: dict[str, str]):
    async def _exec(agent, role, prompt, **kwargs):
        name = role.metadata.name
        return RunResult(run_id=name, output=outputs[name], success=True), []

    return _exec


class TestTeamEnsembleSchema:
    def test_weighted_requires_weights(self):
        with pytest.raises(ValidationError, match="requires a non-empty 'weights'"):
            TeamEnsembleConfig(mode="weighted")

    def test_weights_reference_known_personas(self):
        with pytest.raises(ValidationError, match="unknown personas"):
            _make_team({"mode": "weighted", "weights": {"ghost": 1.0}})

    def test_ensemble_default_strategy_field(self):
        team = _make_team({"mode": "majority"})
        assert team.spec.strategy == "ensemble"
        assert team.spec.ensemble.mode == "majority"


class TestTeamEnsembleExecution:
    @patch("initrunner.agent.loader.build_agent")
    @patch("initrunner.team.graph.execute_run_async")
    def test_majority_vote(self, mock_exec, mock_build, tmp_path):
        team = _make_team({"mode": "majority"})
        mock_build.return_value = MagicMock()
        mock_exec.side_effect = _exec_for({"alpha": "42", "beta": "42", "gamma": "7"})
        audit = MagicMock()

        result = run_team_graph_sync(team, "q", team_dir=tmp_path, audit_logger=audit)

        assert result.success is True
        assert result.final_output == "42"
        call = audit.log_ensemble_vote.call_args
        assert call.kwargs["mode"] == "majority"
        assert call.kwargs["vote_trace"]["counts"] == {"42": 2, "7": 1}

    @patch("initrunner.agent.loader.build_agent")
    @patch("initrunner.team.graph.execute_run_async")
    def test_weighted_vote(self, mock_exec, mock_build, tmp_path):
        team = _make_team(
            {"mode": "weighted", "weights": {"alpha": 0.1, "beta": 0.2, "gamma": 0.9}}
        )
        mock_build.return_value = MagicMock()
        mock_exec.side_effect = _exec_for({"alpha": "A", "beta": "B", "gamma": "C"})
        audit = MagicMock()

        result = run_team_graph_sync(team, "q", team_dir=tmp_path, audit_logger=audit)

        assert result.final_output == "C"
        assert audit.log_ensemble_vote.call_args.kwargs["vote_trace"]["winning_source"] == "gamma"

    @patch("initrunner.agent.loader.build_agent")
    @patch("initrunner.team.graph.execute_run_async")
    def test_judge_vote(self, mock_exec, mock_build, tmp_path):
        team = _make_team({"mode": "judge", "judge_criteria": ["clarity"]})
        mock_build.return_value = MagicMock()
        mock_exec.side_effect = _exec_for({"alpha": "best", "beta": "mid", "gamma": "low"})
        audit = MagicMock()

        def fake_vote(outs, crit, model):
            return VotingResult(
                criteria=["clarity"],
                votes={0: {"clarity": 1}, 1: {"clarity": 0}, 2: {"clarity": 0}},
                winning_index=0,
                consensus_text="c0",
            )

        with patch("initrunner.eval.judge.ensemble_judge_vote_sync", side_effect=fake_vote):
            result = run_team_graph_sync(team, "q", team_dir=tmp_path, audit_logger=audit)

        assert result.final_output == "best"
        assert audit.log_ensemble_vote.call_args.kwargs["mode"] == "judge"

    @patch("initrunner.agent.loader.build_agent")
    @patch("initrunner.team.graph.execute_run_async")
    def test_persona_failure_fails_team(self, mock_exec, mock_build, tmp_path):
        team = _make_team({"mode": "majority"})
        mock_build.return_value = MagicMock()

        async def _exec(agent, role, prompt, **kwargs):
            name = role.metadata.name
            if name == "beta":
                return RunResult(run_id=name, success=False, error="boom"), []
            return RunResult(run_id=name, output="ok", success=True), []

        mock_exec.side_effect = _exec
        result = run_team_graph_sync(team, "q", team_dir=tmp_path)

        assert result.success is False
        assert result.error is not None
        assert "beta" in result.error
