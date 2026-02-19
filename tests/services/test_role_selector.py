"""Tests for initrunner.services.role_selector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from initrunner.services.role_selector import (
    NoRolesFoundError,
    RoleCandidate,
    _llm_select,
    _tokenize,
    score_candidates,
    select_role_sync,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate(
    name: str,
    description: str = "",
    tags: list[str] | None = None,
    path: Path | None = None,
) -> RoleCandidate:
    return RoleCandidate(
        path=path or Path(f"/roles/{name}.yaml"),
        name=name,
        description=description,
        tags=tags or [],
    )


def _discovered(role_name: str, tags: list[str] | None = None, error: str | None = None):
    """Build a mock DiscoveredRole."""
    dr = MagicMock()
    dr.error = error
    if error is None:
        role = MagicMock()
        role.metadata.name = role_name
        role.metadata.description = f"{role_name} description"
        role.metadata.tags = tags or []
        dr.role = role
        dr.path = Path(f"/roles/{role_name}.yaml")
    else:
        dr.role = None
        dr.path = Path(f"/roles/{role_name}.yaml")
    return dr


# ---------------------------------------------------------------------------
# TestTokenize
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_lowercases(self):
        assert "hello" in _tokenize("Hello")

    def test_strips_punctuation(self):
        assert "hello" in _tokenize("hello!")
        assert "world" in _tokenize("world.")

    def test_splits_on_hyphen(self):
        tokens = _tokenize("code-review")
        assert "code" in tokens
        assert "review" in tokens

    def test_splits_on_underscore(self):
        tokens = _tokenize("web_search")
        assert "web" in tokens
        assert "search" in tokens

    def test_removes_stop_words(self):
        tokens = _tokenize("the quick fox")
        assert "the" not in tokens
        assert "quick" in tokens

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_all_stop_words(self):
        assert _tokenize("the and or") == []


# ---------------------------------------------------------------------------
# TestScoreCandidates
# ---------------------------------------------------------------------------


class TestScoreCandidates:
    def test_tag_match_scores_highest(self):
        # Use candidates where one wins purely on tag match,
        # the other only on description match (no name overlap)
        candidates = [
            _candidate("helper", tags=["csv", "analyze"]),  # tag match for both tokens
            _candidate("general", description="analyzes csv files"),  # desc match only
        ]
        scored = score_candidates("analyze csv", candidates)
        tag_match = next(c for c in scored if c.name == "helper")
        desc_match = next(c for c in scored if c.name == "general")
        assert tag_match.score > desc_match.score

    def test_name_match_beats_description(self):
        candidates = [
            _candidate("web-searcher", description="finds things"),
            _candidate("general", description="web search assistant"),
        ]
        scored = score_candidates("search the web", candidates)
        name_match = next(c for c in scored if c.name == "web-searcher")
        desc_match = next(c for c in scored if c.name == "general")
        assert name_match.score > desc_match.score

    def test_scores_sorted_descending(self):
        candidates = [
            _candidate("z-agent", description="nothing related"),
            _candidate("csv-tool", tags=["csv"]),
        ]
        scored = score_candidates("csv processing", candidates)
        scores = [c.score for c in scored]
        assert scores == sorted(scores, reverse=True)

    def test_empty_candidates(self):
        assert score_candidates("hello", []) == []

    def test_verbose_prompt_not_penalised(self):
        """Denominator cap at 5: 15-token prompt scores same as 3-token prompt."""
        cand = _candidate("csv-tool", tags=["csv"])

        short_scored = score_candidates("analyze csv data", [cand])
        # 15-token prompt with one matching token
        long_prompt = "please help me to analyze and process my csv data files properly today yes"
        long_scored = score_candidates(long_prompt, [cand])

        # Both should have score > 0 and the difference should be small
        # (cap at 5 means both divide by 5)
        assert short_scored[0].score > 0
        assert long_scored[0].score > 0
        # With cap at 5, scores from 15-token and 3-token prompts with same match
        # count use the same denominator (5), so ratio should be ~equal
        ratio = abs(short_scored[0].score - long_scored[0].score) / max(
            short_scored[0].score, 0.001
        )
        assert ratio < 1.0  # within 100% — cap is working (no huge penalty)

    def test_token_normalization_punctuation(self):
        cand = _candidate("csv-tool", description="csv! files.")
        scored = score_candidates("csv", [cand])
        assert scored[0].score > 0

    def test_stop_words_ignored_in_scoring(self):
        cand = _candidate("the-tool", description="the best tool for the job")
        # "the" is a stop word — prompt "the" should yield empty tokens → 0 score
        scored = score_candidates("the", [cand])
        # No meaningful tokens → denominator is 1 (max(0,1)) but no hits
        assert scored[0].score == 0.0

    def test_does_not_mutate_input(self):
        original = _candidate("csv-tool", tags=["csv"])
        original_score = original.score
        candidates = [original]
        scored = score_candidates("csv data", candidates)
        # Original should be unchanged
        assert original.score == original_score
        # Scored copy should have updated score
        assert scored[0].score > 0


# ---------------------------------------------------------------------------
# TestSelectRoleSync
# ---------------------------------------------------------------------------


class TestSelectRoleSync:
    def _patch_discovery(self, discovered_roles, dirs=None):
        """Return patch context managers for discovery functions."""
        return (
            patch(
                "initrunner.services.discovery.get_default_role_dirs",
                return_value=dirs or [Path("/roles")],
            ),
            patch(
                "initrunner.services.discovery.discover_roles_sync",
                return_value=discovered_roles,
            ),
        )

    def test_only_one_role_returns_it(self):
        roles = [_discovered("solo-agent")]
        p1, p2 = self._patch_discovery(roles)
        with p1, p2:
            result = select_role_sync("do something")
        assert result.method == "only_one"
        assert result.candidate.name == "solo-agent"

    def test_keyword_confident_no_llm(self):
        roles = [
            _discovered("csv-analyzer", tags=["csv", "data"]),
            _discovered("web-searcher", tags=["web", "search"]),
        ]
        p1, p2 = self._patch_discovery(roles)
        with p1, p2, patch("initrunner.services.role_selector._llm_select") as mock_llm:
            result = select_role_sync("analyze csv data files")
        assert result.method == "keyword"
        assert result.candidate.name == "csv-analyzer"
        mock_llm.assert_not_called()

    def test_ambiguous_invokes_llm(self):
        roles = [
            _discovered("agent-a", tags=["tool"]),
            _discovered("agent-b", tags=["tool"]),
        ]
        winner = MagicMock()
        winner.name = "agent-a"
        winner.path = Path("/roles/agent-a.yaml")
        winner.reason = "LLM selected: agent-a"
        winner.score = 0.0
        winner.tags = ["tool"]
        winner.description = "agent-a description"

        p1, p2 = self._patch_discovery(roles)
        with (
            p1,
            p2,
            patch("initrunner.services.role_selector._llm_select", return_value=winner) as mock_llm,
        ):
            result = select_role_sync("generic task")
        mock_llm.assert_called_once()
        assert result.method == "llm"
        assert result.used_llm is True

    def test_llm_exception_returns_fallback(self):
        roles = [
            _discovered("agent-a", tags=["tool"]),
            _discovered("agent-b", tags=["tool"]),
        ]
        p1, p2 = self._patch_discovery(roles)
        with (
            p1,
            p2,
            patch(
                "initrunner.services.role_selector._llm_select",
                side_effect=RuntimeError("API error"),
            ),
        ):
            result = select_role_sync("generic task")
        assert result.method == "fallback"
        assert result.used_llm is False

    def test_llm_unparseable_returns_fallback(self):
        roles = [
            _discovered("agent-a", tags=["tool"]),
            _discovered("agent-b", tags=["tool"]),
        ]
        p1, p2 = self._patch_discovery(roles)
        with (
            p1,
            p2,
            patch(
                "initrunner.services.role_selector._llm_select",
                side_effect=ValueError("no match"),
            ),
        ):
            result = select_role_sync("generic task")
        assert result.method == "fallback"

    def test_no_valid_roles_raises_error(self):
        roles = [
            _discovered("bad-role", error="parse error"),
            _discovered("another-bad", error="validation error"),
        ]
        p1, p2 = self._patch_discovery(roles, dirs=[Path("/roles")])
        with p1, p2, pytest.raises(NoRolesFoundError):
            select_role_sync("do something")

    def test_role_dir_forwarded_to_discovery(self):
        roles = [_discovered("solo-agent")]
        custom_dir = Path("/custom/roles")
        with (
            patch(
                "initrunner.services.discovery.get_default_role_dirs",
                return_value=[custom_dir],
            ) as mock_dirs,
            patch(
                "initrunner.services.discovery.discover_roles_sync",
                return_value=roles,
            ),
        ):
            select_role_sync("do something", role_dir=custom_dir)
        mock_dirs.assert_called_once_with(custom_dir)

    def test_allow_llm_false_never_calls_llm(self):
        roles = [
            _discovered("agent-a", tags=["tool"]),
            _discovered("agent-b", tags=["tool"]),
        ]
        p1, p2 = self._patch_discovery(roles)
        with p1, p2, patch("initrunner.services.role_selector._llm_select") as mock_llm:
            result = select_role_sync("generic task", allow_llm=False)
        mock_llm.assert_not_called()
        assert result.method == "fallback"

    def test_all_stopword_prompt_raises_valueerror(self):
        roles = [_discovered("agent-a")]
        p1, p2 = self._patch_discovery(roles)
        with p1, p2, pytest.raises(ValueError, match="no meaningful keywords"):
            select_role_sync("the and or is")

    def test_duplicate_role_names_picks_highest_score(self):
        """When LLM names a role that has duplicates, pick the one with highest score."""
        # Create two roles with same normalized name but different scores
        # (roles variable omitted — we test _llm_select directly with duplicates)
        # Mock _llm_select to return whichever — the real logic should prefer higher score
        # We test the path inside _llm_select directly with duplicates
        cands = [
            RoleCandidate(
                path=Path("/a/my-tool.yaml"),
                name="my-tool",
                description="csv data analysis",
                tags=["csv", "data"],
                score=3.0,
            ),
            RoleCandidate(
                path=Path("/b/my-tool.yaml"),
                name="my-tool",
                description="web browsing",
                tags=["web"],
                score=1.0,
            ),
        ]
        with patch("pydantic_ai.Agent") as MockAgent:
            mock_result = MagicMock()
            mock_result.output = "my-tool"
            MockAgent.return_value.run_sync.return_value = mock_result

            winner = _llm_select("analyze csv data", cands)
        # Should pick the candidate with higher score (3.0)
        assert winner.path == Path("/a/my-tool.yaml")
        assert "ambiguous" in winner.reason
