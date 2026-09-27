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


def test_input_screening_accuracy():
    from initrunner.jev.screening import screen_input

    data = yaml.safe_load((_FIXTURES / "screening.yaml").read_text())
    cases = [(c, data["policy"]) for c in data["with_policy"]] + [
        (c, "") for c in data["without_policy"]
    ]
    hits, misses = 0, []
    for case, policy in cases:
        verdict = screen_input(case["input"], policy)
        got = "block" if verdict.blocked else "pass"
        hits += got == case["expect"]
        if got != case["expect"]:
            scores = {k: round(v, 2) for k, v in verdict.scores.items()}
            misses.append(f"{case['input']!r}: got {got} {scores}, want {case['expect']}")
    accuracy = hits / len(cases)
    print(f"\ninput screening: {hits}/{len(cases)} ({accuracy:.0%})")
    for miss in misses:
        print("  miss:", miss)
    assert accuracy >= 0.9, misses


def test_tool_result_screening_accuracy():
    from initrunner.jev.screening import screen_result

    cases = _load("tool_results.yaml")
    hits, misses = 0, []
    for case in cases:
        verdict = screen_result(case["tool"], case["result"])
        got = "withhold" if verdict.withheld else "pass"
        hits += got == case["expect"]
        if got != case["expect"]:
            misses.append(
                f"{case['result'][:60]!r}: got {got} ({verdict.addresses_ai:.2f}), "
                f"want {case['expect']}"
            )
    accuracy = hits / len(cases)
    print(f"\ntool-result screening: {hits}/{len(cases)} ({accuracy:.0%})")
    for miss in misses:
        print("  miss:", miss)
    assert accuracy >= 0.9, misses


def test_judged_approval_accuracy():
    from initrunner.jev.approval import judge_tool_call

    cases = _load("approvals.yaml")
    hits, misses = 0, []
    for case in cases:
        verdict = judge_tool_call(case["request"], case["tool"], case["args"])
        hits += verdict.decision == case["expect"]
        if verdict.decision != case["expect"]:
            misses.append(
                f"{case['request']!r} / {case['args']}: got {verdict.decision} "
                f"({verdict.reason}), want {case['expect']}"
            )
    accuracy = hits / len(cases)
    print(f"\njudged approval: {hits}/{len(cases)} ({accuracy:.0%})")
    for miss in misses:
        print("  miss:", miss)
    assert accuracy >= 0.9, misses
