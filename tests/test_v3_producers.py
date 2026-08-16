"""Writer/consumer inventory for the v3 cut. Paths must keep existing."""

from __future__ import annotations

from pathlib import Path

from initrunner.agent.schema.producers import YAML_PRODUCERS


def test_every_listed_producer_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    missing = [rel for rel, _note in YAML_PRODUCERS if not (root / rel).is_file()]
    assert missing == []
