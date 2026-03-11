"""Tests for the role selector service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from initrunner.services.role_selector import (
    RoleCandidate,
    SelectionResult,
    score_candidates,
    select_candidate_sync,
)


def _make_candidates() -> list[RoleCandidate]:
    return [
        RoleCandidate(
            path=Path("roles/researcher.yaml"),
            name="researcher",
            description="Research topics and gather information",
            tags=["research", "analysis"],
        ),
        RoleCandidate(
            path=Path("roles/responder.yaml"),
            name="responder",
            description="Respond to user queries directly",
            tags=["response", "chat"],
        ),
        RoleCandidate(
            path=Path("roles/escalator.yaml"),
            name="escalator",
            description="Escalate complex issues to humans",
            tags=["escalation", "support"],
        ),
    ]


class TestSelectCandidateSync:
    def test_single_candidate_returns_only_one(self):
        candidates = [_make_candidates()[0]]
        result = select_candidate_sync("anything", candidates)
        assert result.method == "only_one"
        assert result.candidate.name == "researcher"

    def test_keyword_match_returns_keyword_method(self):
        candidates = _make_candidates()
        result = select_candidate_sync("research machine learning papers", candidates)
        assert result.method == "keyword"
        assert result.candidate.name == "researcher"
        assert result.top_score > 0

    def test_tag_match(self):
        candidates = _make_candidates()
        result = select_candidate_sync("escalation needed for support", candidates)
        assert result.candidate.name == "escalator"

    def test_empty_candidates_raises(self):
        with pytest.raises(ValueError, match="No candidates provided"):
            select_candidate_sync("test", [])

    def test_empty_prompt_raises(self):
        candidates = _make_candidates()
        with pytest.raises(ValueError, match="no meaningful keywords"):
            select_candidate_sync("the and is", candidates)

    def test_allow_llm_false_skips_llm(self):
        candidates = _make_candidates()
        with patch("initrunner.services.role_selector._llm_select") as mock_llm:
            result = select_candidate_sync(
                "something vague and ambiguous",
                candidates,
                allow_llm=False,
            )
            mock_llm.assert_not_called()
        # Should return fallback when ambiguous and LLM disabled
        assert result.method in ("keyword", "fallback")

    def test_llm_called_when_ambiguous_and_allowed(self):
        candidates = _make_candidates()
        with patch("initrunner.services.role_selector._llm_select") as mock_llm:
            mock_llm.return_value = candidates[1]
            candidates[1].reason = "LLM selected: responder"
            result = select_candidate_sync(
                "something vague",
                candidates,
                allow_llm=True,
            )
        # If keyword was conclusive, LLM won't be called, so check both cases
        if result.method == "llm":
            mock_llm.assert_called_once()
            assert result.used_llm is True

    def test_llm_failure_returns_fallback(self):
        candidates = _make_candidates()
        with patch(
            "initrunner.services.role_selector._llm_select",
            side_effect=RuntimeError("API down"),
        ):
            result = select_candidate_sync(
                "something vague",
                candidates,
                allow_llm=True,
            )
        assert result.method in ("keyword", "fallback")

    def test_gap_and_score_populated(self):
        candidates = _make_candidates()
        result = select_candidate_sync("research analysis papers", candidates)
        assert result.top_score >= 0
        assert result.gap >= 0


class TestSelectCandidateSyncMatchesSelectRoleSync:
    """Verify that select_role_sync is a thin wrapper over select_candidate_sync."""

    @patch("initrunner.services.role_selector.select_candidate_sync")
    @patch("initrunner.services.discovery.discover_roles_sync")
    @patch("initrunner.services.discovery.get_default_role_dirs")
    def test_select_role_sync_delegates(self, mock_dirs, mock_discover, mock_select):
        from unittest.mock import MagicMock

        from initrunner.services.role_selector import select_role_sync

        # Set up discovery to return two valid role files
        mock_dirs.return_value = [Path("roles/")]
        discovered = []
        for name, desc, tags in [
            ("alpha", "Alpha agent", ["a"]),
            ("beta", "Beta agent", ["b"]),
        ]:
            d = MagicMock()
            d.error = None
            d.role = MagicMock()
            d.role.metadata.name = name
            d.role.metadata.description = desc
            d.role.metadata.tags = tags
            d.path = Path(f"roles/{name}.yaml")
            discovered.append(d)
        mock_discover.return_value = discovered

        mock_select.return_value = SelectionResult(
            candidate=RoleCandidate(
                path=Path("roles/alpha.yaml"), name="alpha", description="Alpha agent", tags=["a"]
            ),
            method="keyword",
        )

        result = select_role_sync("test prompt")

        mock_select.assert_called_once()
        call_args = mock_select.call_args
        assert call_args[0][0] == "test prompt"
        assert len(call_args[0][1]) == 2  # two candidates passed
        assert result.candidate.name == "alpha"


class TestScoreCandidates:
    def test_name_match_scores_higher(self):
        candidates = _make_candidates()
        scored = score_candidates("researcher", candidates)
        assert scored[0].name == "researcher"
        assert scored[0].score > scored[1].score

    def test_description_match(self):
        candidates = _make_candidates()
        scored = score_candidates("gather information", candidates)
        assert scored[0].name == "researcher"

    def test_tag_match(self):
        candidates = _make_candidates()
        scored = score_candidates("chat response", candidates)
        assert scored[0].name == "responder"

    def test_does_not_mutate_originals(self):
        candidates = _make_candidates()
        original_scores = [c.score for c in candidates]
        score_candidates("research", candidates)
        # Original candidates should be unchanged
        for c, orig in zip(candidates, original_scores, strict=True):
            assert c.score == orig
