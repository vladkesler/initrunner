"""Autonomous role selection service.

Two-pass selection:
  Pass 1: Keyword/tag scoring — zero API calls, covers obvious matches.
  Pass 2: LLM tiebreaker — compact call used only when Pass 1 is ambiguous.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    pass

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

_CONFIDENCE_THRESHOLD = 0.35
_GAP_THRESHOLD = 0.15
_TAG_WEIGHT = 3.0
_NAME_WEIGHT = 2.0
_DESC_WEIGHT = 1.5

_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "to",
        "and",
        "or",
        "is",
        "for",
        "in",
        "of",
        "that",
        "it",
        "be",
        "this",
        "with",
        "on",
        "at",
        "by",
        "from",
        "as",
        "are",
        "was",
        "were",
        "will",
        "can",
        "do",
        "have",
        "has",
        "had",
    }
)

# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass
class RoleCandidate:
    path: Path
    name: str
    description: str
    tags: list[str]
    score: float = 0.0
    reason: str = ""


@dataclass
class SelectionResult:
    candidate: RoleCandidate
    method: Literal["only_one", "keyword", "llm", "fallback"]
    top_score: float = 0.0
    gap: float = 0.0
    used_llm: bool = False


class NoRolesFoundError(Exception):
    """No valid role files found; message includes searched dirs."""


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_SPLIT = re.compile(r"[\s\-_]+")
_PUNCT_STRIP = re.compile(r"[.,!?;:()\[\]\"']+")


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace/hyphen/underscore, remove stop words."""
    text = _PUNCT_STRIP.sub("", text.lower())
    parts = _TOKEN_SPLIT.split(text)
    return [p for p in parts if p and p not in _STOP_WORDS]


# ---------------------------------------------------------------------------
# Pass 1 — keyword scoring
# ---------------------------------------------------------------------------


def score_candidates(
    prompt: str,
    candidates: list[RoleCandidate],
) -> list[RoleCandidate]:
    """Score and rank candidates by keyword match. Returns new sorted list (descending)."""
    prompt_tokens = _tokenize(prompt)
    denom = min(max(len(prompt_tokens), 1), 5)

    scored: list[RoleCandidate] = []
    for c in candidates:
        import copy

        sc = copy.copy(c)
        score = 0.0

        for token in prompt_tokens:
            # Name match
            for part in _tokenize(sc.name):
                if token == part or part.startswith(token) or token.startswith(part):
                    score += _NAME_WEIGHT

            # Description match (exact token only)
            for part in _tokenize(sc.description):
                if token == part:
                    score += _DESC_WEIGHT

            # Tag match (exact token only)
            for tag in sc.tags:
                for part in _tokenize(tag):
                    if token == part:
                        score += _TAG_WEIGHT

        sc.score = score / denom
        scored.append(sc)

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Pass 2 — LLM tiebreaker (private)
# ---------------------------------------------------------------------------


def _llm_select(prompt: str, top_candidates: list[RoleCandidate]) -> RoleCandidate:
    """Ask the default LLM to pick the best role. Returns the matched candidate.

    Raises an exception (any) if the call fails or the response cannot be
    matched to a candidate — callers must handle this and fall back.
    """
    from pydantic_ai import Agent

    model_str = os.environ.get("INITRUNNER_DEFAULT_MODEL", "openai:gpt-4o-mini")

    lines = []
    for c in top_candidates:
        desc_excerpt = c.description[:200]
        tags_csv = ", ".join(c.tags) if c.tags else "none"
        lines.append(f"{c.name}: {desc_excerpt} [tags: {tags_csv}]")
    roles_block = "\n".join(lines)

    llm_prompt = (
        f'Task: "{prompt}"\n\n'
        "Choose the best agent role. Reply with ONLY the role name.\n\n"
        f"Roles:\n{roles_block}\n\n"
        "Role:"
    )

    agent: Agent[None, str] = Agent(model_str)
    result = agent.run_sync(llm_prompt)
    raw_response = result.output.strip()

    # Normalize response for matching
    normalized_response = _PUNCT_STRIP.sub("", raw_response.lower()).strip()

    # Build name→candidate map; when duplicate names, keep all (pick highest score later)
    name_map: dict[str, list[RoleCandidate]] = {}
    for c in top_candidates:
        key = _PUNCT_STRIP.sub("", c.name.lower()).strip()
        name_map.setdefault(key, []).append(c)

    matches = name_map.get(normalized_response)
    if not matches:
        raise ValueError(f"LLM response {raw_response!r} did not match any candidate name")

    if len(matches) == 1:
        matches[0].reason = f"LLM selected: {raw_response}"
        return matches[0]

    # Duplicate name — pick the one with highest Pass-1 score
    best = max(matches, key=lambda x: x.score)
    best.reason = f"LLM selected: {raw_response} (ambiguous name — picked highest keyword score)"
    return best


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def select_role_sync(
    prompt: str,
    *,
    role_dir: Path | None = None,
    allow_llm: bool = True,
) -> SelectionResult:
    """Select the best matching role for *prompt*.

    Args:
        prompt: The user's task description.
        role_dir: Optional explicit directory to search (passed to discovery).
        allow_llm: When False (e.g. ``--dry-run``), skips the LLM tiebreaker
                   and uses Pass-1 top scorer as fallback instead.

    Returns:
        :class:`SelectionResult` with the chosen candidate and diagnostics.

    Raises:
        ValueError: If the prompt contains no meaningful keywords after filtering.
        NoRolesFoundError: If no valid role files are found in the discovered dirs.
    """
    from initrunner.services.discovery import discover_roles_sync, get_default_role_dirs

    # Validate prompt before doing any I/O
    prompt_tokens = _tokenize(prompt)
    if not prompt_tokens:
        raise ValueError("Prompt contains no meaningful keywords after filtering.")

    dirs = get_default_role_dirs(role_dir)
    discovered = discover_roles_sync(dirs)

    valid = [d for d in discovered if d.error is None and d.role is not None]

    if not valid:
        searched = ", ".join(str(d) for d in dirs)
        raise NoRolesFoundError(f"No valid role files found in: {searched}")

    if len(valid) == 1:
        d = valid[0]
        assert d.role is not None
        cand = RoleCandidate(
            path=d.path,
            name=d.role.metadata.name,
            description=d.role.metadata.description,
            tags=list(d.role.metadata.tags),
        )
        return SelectionResult(candidate=cand, method="only_one")

    # Build candidates list
    candidates: list[RoleCandidate] = []
    for d in valid:
        assert d.role is not None
        candidates.append(
            RoleCandidate(
                path=d.path,
                name=d.role.metadata.name,
                description=d.role.metadata.description,
                tags=list(d.role.metadata.tags),
            )
        )

    scored = score_candidates(prompt, candidates)
    top_score = scored[0].score
    second_score = scored[1].score if len(scored) > 1 else 0.0
    gap = top_score - second_score

    if top_score >= _CONFIDENCE_THRESHOLD and gap >= _GAP_THRESHOLD:
        scored[0].reason = f"keyword match (score: {top_score:.2f}, gap: {gap:.2f})"
        return SelectionResult(
            candidate=scored[0],
            method="keyword",
            top_score=top_score,
            gap=gap,
        )

    # Ambiguous — try LLM tiebreaker
    if not allow_llm:
        scored[0].reason = "fallback — no strong keyword match (LLM disabled)"
        return SelectionResult(
            candidate=scored[0],
            method="fallback",
            top_score=top_score,
            gap=gap,
        )

    try:
        winner = _llm_select(prompt, scored[:5])
        return SelectionResult(
            candidate=winner,
            method="llm",
            top_score=top_score,
            gap=gap,
            used_llm=True,
        )
    except Exception as exc:
        _logger.debug("LLM tiebreaker failed (%s); using fallback", exc)
        scored[0].reason = "fallback — LLM tiebreaker failed"
        return SelectionResult(
            candidate=scored[0],
            method="fallback",
            top_score=top_score,
            gap=gap,
        )
