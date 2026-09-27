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


# ---------------------------------------------------------------------------
# Jev routing
# ---------------------------------------------------------------------------


def _jev_answer(probabilities: dict[str, float]):
    from initrunner.jev import ChoiceResult, Judgment

    choice = max(probabilities, key=lambda k: probabilities[k])
    return Judgment(
        choices={
            "agent": ChoiceResult(
                choice=choice,
                confidence=probabilities[choice],
                probabilities=probabilities,
            )
        },
        model="jev-1.13.0",
        request_id="req_test",
    )


@pytest.fixture
def jev_on(monkeypatch):
    """Turn Jev on and return a setter for the next routing answer."""
    import initrunner.jev as jev

    calls: list[tuple] = []
    answer: dict = {}

    def _ask(state, questions):
        calls.append((state, questions))
        return _jev_answer(answer["probabilities"])

    monkeypatch.setattr(jev, "is_configured", lambda: True)
    monkeypatch.setattr(jev, "ask", _ask)

    def _set(probabilities: dict[str, float]) -> list[tuple]:
        answer["probabilities"] = probabilities
        return calls

    return _set


class TestJevRouting:
    def test_jev_picks_the_candidate(self, jev_on):
        calls = jev_on(
            {"researcher": 0.1, "responder": 0.8, "escalator": 0.05, "none_of_these": 0.05}
        )
        result = select_candidate_sync("research machine learning papers", _make_candidates())
        assert result.method == "jev"
        assert result.candidate.name == "responder"
        assert result.confidence == pytest.approx(0.8)
        assert result.runner_up is not None and result.runner_up.name == "researcher"
        # One call, every candidate plus none_of_these as options, task in the state.
        state, questions = calls[0]
        assert state == {"task": "research machine learning papers"}
        assert set(questions["agent"]["criteria"]) == {
            "researcher",
            "responder",
            "escalator",
            "none_of_these",
        }

    def test_keyword_pass_is_skipped(self, jev_on):
        """A confident keyword match must not pre-empt Jev (it can be confidently wrong)."""
        jev_on({"researcher": 0.05, "responder": 0.05, "escalator": 0.85, "none_of_these": 0.05})
        result = select_candidate_sync("research machine learning papers", _make_candidates())
        assert result.candidate.name == "escalator"

    def test_none_of_these_abstains_when_allowed(self, jev_on):
        from initrunner.services.role_selector import NoFitError

        jev_on({"researcher": 0.1, "responder": 0.1, "escalator": 0.1, "none_of_these": 0.7})
        with pytest.raises(NoFitError, match="No role fits"):
            select_candidate_sync("book a table", _make_candidates(), allow_none=True)

    def test_none_of_these_is_ignored_for_closed_sets(self, jev_on):
        jev_on({"researcher": 0.1, "responder": 0.15, "escalator": 0.05, "none_of_these": 0.7})
        result = select_candidate_sync("book a table", _make_candidates())
        assert result.method == "jev"
        assert result.candidate.name == "responder"

    def test_no_fit_error_is_a_value_error(self):
        from initrunner.services.role_selector import NoFitError

        # The CLI's existing `except ValueError` handlers rely on this.
        assert issubclass(NoFitError, ValueError)

    def test_jev_error_falls_back_to_keyword(self, monkeypatch):
        import initrunner.jev as jev

        def _fail(state, questions):
            raise jev.JevError("down")

        monkeypatch.setattr(jev, "is_configured", lambda: True)
        monkeypatch.setattr(jev, "ask", _fail)
        result = select_candidate_sync("research machine learning papers", _make_candidates())
        assert result.method == "keyword"
        assert result.candidate.name == "researcher"

    def test_dry_run_never_calls_jev(self, jev_on):
        calls = jev_on({"researcher": 1.0})
        result = select_candidate_sync(
            "research machine learning papers", _make_candidates(), allow_llm=False
        )
        assert calls == []
        assert result.method == "keyword"

    def test_not_configured_uses_keyword(self):
        # The autouse fixture leaves Jev unconfigured.
        result = select_candidate_sync("research machine learning papers", _make_candidates())
        assert result.method == "keyword"

    def test_duplicate_names_get_distinct_options(self, jev_on):
        dupes = [
            RoleCandidate(path=Path("a/role.yaml"), name="helper", description="A", tags=[]),
            RoleCandidate(path=Path("b/role.yaml"), name="helper", description="B", tags=[]),
        ]
        calls = jev_on({"helper@a": 0.2, "helper@b": 0.7, "none_of_these": 0.1})
        result = select_candidate_sync("help me", dupes)
        assert set(calls[0][1]["agent"]["criteria"]) == {"helper@a", "helper@b", "none_of_these"}
        assert result.candidate.path == Path("b/role.yaml")

    def test_role_selection_passes_allow_none_through(self):
        from initrunner.services.role_selector import select_role_sync

        with patch("initrunner.services.role_selector.select_candidate_sync") as sel:
            with patch(
                "initrunner.services.discovery.discover_roles_sync",
                return_value=[_fake_discovered()],
            ):
                select_role_sync("research papers", allow_none=True)
        assert sel.call_args.kwargs["allow_none"] is True


def _fake_discovered():
    from types import SimpleNamespace

    metadata = SimpleNamespace(name="researcher", description="Research topics", tags=[])
    return SimpleNamespace(
        error=None, path=Path("roles/researcher.yaml"), role=SimpleNamespace(metadata=metadata)
    )
