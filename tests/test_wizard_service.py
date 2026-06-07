"""Tests for the pure wizard service (offline form data + builders)."""

from __future__ import annotations

import pytest

from initrunner.services import wizard

# ---------------------------------------------------------------------------
# Agent name validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("my-agent", True),
        ("agent1", True),
        ("a1b2c3", True),
        ("My-Agent", False),  # uppercase
        ("my_agent", False),  # underscore
        ("-leading", False),
        ("trailing-", False),
        ("ab", True),
        ("a", False),  # schema pattern needs a 2-char minimum
        ("", False),
    ],
)
def test_validate_agent_name(name, ok):
    assert wizard.validate_agent_name(name) is ok


# ---------------------------------------------------------------------------
# Field value coercion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("100", 100),
        ("true", True),
        ("false", False),
        ("[a, b]", ["a", "b"]),
        ("./data.db", "./data.db"),
        ("UTC", "UTC"),
        ("", None),
        ("   ", None),
    ],
)
def test_coerce_field_value(raw, expected):
    assert wizard.coerce_field_value(raw) == expected


# ---------------------------------------------------------------------------
# Tool catalog
# ---------------------------------------------------------------------------


def test_list_tool_choices_is_curated():
    types = {c.type for c in wizard.list_tool_choices()}
    # Complex/nested-config tools are excluded from the offline form.
    assert "mcp" not in types
    assert "api" not in types
    assert "delegate" not in types
    # The simple, flat-promptable tools are present.
    assert {"filesystem", "web_reader", "sql", "http", "datetime", "slack"} <= types


def test_list_tool_choices_flags_required_fields():
    by_type = {c.type: c for c in wizard.list_tool_choices()}
    assert "webhook_url" in by_type["slack"].required_fields
    assert "base_url" in by_type["http"].required_fields
    assert "database" in by_type["sql"].required_fields
    # Tools with sensible defaults need nothing.
    assert by_type["web_reader"].required_fields == []
    assert by_type["datetime"].required_fields == []


# ---------------------------------------------------------------------------
# Offline YAML assembly
# ---------------------------------------------------------------------------


def test_build_offline_yaml_is_valid(tmp_path):
    from initrunner.services.roles import save_role_yaml_sync

    spec = wizard.OfflineFormSpec(
        name="triage-bot",
        description="Triage incoming issues",
        system_prompt="You triage GitHub issues.",
        provider="openai",
        model="gpt-5.4-mini",
        tools=[
            {"type": "web_reader"},
            {"type": "sql", "database": "./data.db", "read_only": True},
        ],
        memory=True,
        ingest_sources=["./docs"],
        triggers=[{"type": "cron", "schedule": "0 * * * *", "prompt": "Triage new issues."}],
    )
    text = wizard.build_offline_yaml(spec)
    role = save_role_yaml_sync(tmp_path / "role.yaml", text)

    assert role.metadata.name == "triage-bot"
    assert {t.type for t in role.spec.tools} == {"web_reader", "sql"}
    assert role.spec.memory is not None
    assert role.spec.ingest is not None
    assert [t.type for t in role.spec.triggers] == ["cron"]


def test_build_offline_yaml_minimal(tmp_path):
    from initrunner.services.roles import save_role_yaml_sync

    spec = wizard.OfflineFormSpec(
        name="plain-bot",
        description="",
        system_prompt="You are helpful.",
        provider="openai",
        model=None,  # resolves to a default
        tools=[],
    )
    role = save_role_yaml_sync(tmp_path / "role.yaml", wizard.build_offline_yaml(spec))
    assert role.metadata.name == "plain-bot"
    assert role.spec.model is not None and role.spec.model.name
