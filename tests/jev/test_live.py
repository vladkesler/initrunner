"""Live calibration against the real Jev API.

Skipped without ``TYPESAFE_API_KEY``. Run it before changing a question, a
threshold, or ``questions.MODEL``:

    uv run --extra jev pytest tests/jev/test_live.py -v -s

Each test prints its accuracy so the numbers can go into the PR description.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.jev_live,
    pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY not set"),
]

pytest.importorskip("typesafe_sdk")

_FIXTURES = Path(__file__).parent / "fixtures"
_REPO = Path(__file__).resolve().parents[2]


def _load(name: str) -> list[dict]:
    return yaml.safe_load((_FIXTURES / name).read_text())


def test_routing_accuracy():
    from initrunner.jev.questions import ROUTE_CONFIDENT
    from initrunner.services.discovery import discover_roles_sync
    from initrunner.services.role_selector import (
        NoFitError,
        RoleCandidate,
        select_candidate_sync,
    )

    candidates = [
        RoleCandidate(
            path=d.path,
            name=d.role.metadata.name,
            description=d.role.metadata.description,
            tags=list(d.role.metadata.tags),
        )
        for d in discover_roles_sync([_REPO / "examples" / "roles"])
        if d.role is not None
    ]
    cases = _load("routing.yaml")
    hits, keyword_hits, misses = 0, 0, []
    for case in cases:
        expect = case["expect"]
        try:
            result = select_candidate_sync(case["prompt"], candidates, allow_none=True)
            picked, confidence = result.candidate.name, result.confidence or 0.0
            assert result.method == "jev", result.method
        except NoFitError:
            picked, confidence = "none", 0.0

        if expect == "none":
            ok = picked == "none" or confidence < ROUTE_CONFIDENT
        else:
            ok = picked in expect
        hits += ok
        if not ok:
            misses.append(f"{case['prompt']!r}: got {picked} ({confidence:.2f}), want {expect}")

        if expect != "none":
            kw = select_candidate_sync(case["prompt"], candidates, allow_llm=False)
            keyword_hits += kw.candidate.name in expect

    accuracy = hits / len(cases)
    scored = sum(1 for c in cases if c["expect"] != "none")
    print(
        f"\nrouting: jev {hits}/{len(cases)} ({accuracy:.0%}), "
        f"keyword baseline {keyword_hits}/{scored} on cases with a fitting role"
    )
    for miss in misses:
        print("  miss:", miss)
    assert accuracy >= 0.9, misses
