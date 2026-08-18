"""Writer/consumer inventory for the v3 cut. Paths must keep existing."""

from __future__ import annotations

from pathlib import Path

import yaml

from initrunner.agent.schema.producers import YAML_PRODUCERS
from initrunner.templates import LISTABLE_TEMPLATES, TEMPLATES


def test_every_listed_producer_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    missing = [rel for rel, _note in YAML_PRODUCERS if not (root / rel).is_file()]
    assert missing == []


def test_listable_templates_are_flat() -> None:
    for name in LISTABLE_TEMPLATES:
        text = TEMPLATES[name]("sample-agent", "openai", "gpt-5-mini")
        data = yaml.safe_load(text)
        assert isinstance(data, dict), name
        assert data.get("apiVersion") != "initrunner/v1" or data.get("kind") not in {
            "Agent",
            "Team",
            "Flow",
        }
        assert data.get("name") == "sample-agent"
        assert "prompt" in data or "agents" in data
