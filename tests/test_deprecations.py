"""Tests for the centralized deprecation system."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from initrunner.deprecations import (
    CURRENT_ROLE_SPEC_VERSION,
    SchemaKind,
    _get_nested,
    apply_deprecations,
    inspect_role_data,
    validate_flow_dict,
    validate_role_dict,
    validate_team_dict,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_role_dict(**overrides) -> dict:
    """Build a minimal valid role dict."""
    d = {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent", "spec_version": 2},
        "spec": {
            "role": "You are helpful.",
            "model": {"provider": "openai", "name": "gpt-5-mini"},
        },
    }
    for key, val in overrides.items():
        parts = key.split(".")
        cursor = d
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})  # type: ignore[no-matching-overload]
        cursor[parts[-1]] = val  # type: ignore[invalid-assignment]
    return d


def _minimal_flow_dict(**spec_overrides) -> dict:
    d = {
        "apiVersion": "initrunner/v1",
        "kind": "Flow",
        "metadata": {"name": "test-flow"},
        "spec": {
            "agents": {
                "agent-a": {"role": "roles/a.yaml"},
                "agent-b": {"role": "roles/b.yaml"},
            },
        },
    }
    for key, val in spec_overrides.items():
        d["spec"][key] = val
    return d


def _minimal_team_dict(**spec_overrides) -> dict:
    d = {
        "apiVersion": "initrunner/v1",
        "kind": "Team",
        "metadata": {"name": "test-team"},
        "spec": {
            "model": {"provider": "openai", "name": "gpt-5-mini"},
            "personas": {
                "writer": {"role": "You write."},
                "editor": {"role": "You edit."},
            },
        },
    }
    for key, val in spec_overrides.items():
        d["spec"][key] = val
    return d


# ---------------------------------------------------------------------------
# _get_nested
# ---------------------------------------------------------------------------


class TestGetNested:
    def test_found(self):
        assert _get_nested({"a": {"b": 1}}, "a.b") == (True, 1)

    def test_not_found(self):
        assert _get_nested({"a": {}}, "a.b") == (False, None)

    def test_top_level(self):
        assert _get_nested({"x": 42}, "x") == (True, 42)

    def test_non_dict_intermediate(self):
        assert _get_nested({"a": "string"}, "a.b") == (False, None)


# ---------------------------------------------------------------------------
# apply_deprecations
# ---------------------------------------------------------------------------


class TestApplyDeprecations:
    def test_clean_role_no_hits(self):
        data = _minimal_role_dict()
        migrated, hits = apply_deprecations(data, SchemaKind.ROLE)
        assert hits == []
        assert migrated == data

    def test_zvec_role_ingest(self):
        data = _minimal_role_dict()
        data["spec"]["ingest"] = {"sources": ["*.md"], "store_backend": "zvec"}
        migrated, hits = apply_deprecations(data, SchemaKind.ROLE)
        assert len(hits) == 1
        assert hits[0].id == "DEP002"
        assert hits[0].severity == "error"
        assert hits[0].auto_fixed
        assert migrated["spec"]["ingest"]["store_backend"] == "lancedb"

    def test_zvec_role_memory(self):
        data = _minimal_role_dict()
        data["spec"]["memory"] = {"store_backend": "zvec"}
        _, hits = apply_deprecations(data, SchemaKind.ROLE)
        assert len(hits) == 1
        assert hits[0].id == "DEP003"

    def test_zvec_flow(self):
        data = _minimal_flow_dict(
            shared_memory={"store_backend": "zvec"},
            shared_documents={"store_backend": "zvec"},
        )
        _, hits = apply_deprecations(data, SchemaKind.FLOW)
        ids = {h.id for h in hits}
        assert "DEP004" in ids
        assert "DEP005" in ids

    def test_zvec_team(self):
        data = _minimal_team_dict(
            shared_memory={"store_backend": "zvec"},
            shared_documents={"store_backend": "zvec"},
        )
        _, hits = apply_deprecations(data, SchemaKind.TEAM)
        ids = {h.id for h in hits}
        assert "DEP004" in ids
        assert "DEP005" in ids

    def test_max_memories_error(self):
        data = _minimal_role_dict()
        data["spec"]["memory"] = {"max_memories": 500}
        _, hits = apply_deprecations(data, SchemaKind.ROLE)
        assert len(hits) == 1
        assert hits[0].id == "DEP001"
        assert hits[0].severity == "error"

    def test_wrong_kind_ignored(self):
        """Role-only rules don't fire on flow kind."""
        data = _minimal_flow_dict()
        data["spec"]["memory"] = {"max_memories": 500}
        _, hits = apply_deprecations(data, SchemaKind.FLOW)
        assert not any(h.id == "DEP001" for h in hits)

    def test_lancedb_does_not_trigger(self):
        """store_backend: lancedb should not trigger zvec rules."""
        data = _minimal_role_dict()
        data["spec"]["ingest"] = {"sources": ["*.md"], "store_backend": "lancedb"}
        _, hits = apply_deprecations(data, SchemaKind.ROLE)
        assert not any(h.id == "DEP002" for h in hits)

    def test_deep_copy(self):
        """apply_deprecations does not mutate input."""
        data = _minimal_role_dict()
        data["spec"]["memory"] = {"max_memories": 500}
        original_memory = data["spec"]["memory"].copy()
        apply_deprecations(data, SchemaKind.ROLE)
        assert data["spec"]["memory"] == original_memory


# ---------------------------------------------------------------------------
# validate_role_dict
# ---------------------------------------------------------------------------


class TestValidateRoleDict:
    def test_clean(self):
        role, hits = validate_role_dict(_minimal_role_dict())
        assert role.metadata.name == "test-agent"
        assert hits == []

    def test_future_version_rejects(self):
        data = _minimal_role_dict()
        data["metadata"]["spec_version"] = 99
        with pytest.raises(ValueError, match="newer than the supported version"):
            validate_role_dict(data)

    def test_auto_fixed_hit_does_not_raise(self):
        """Auto-fixed deprecations (with migrate callables) should not raise."""
        data = _minimal_role_dict()
        data["spec"]["memory"] = {"max_memories": 500}
        role, hits = validate_role_dict(data)
        assert any(h.id == "DEP001" and h.auto_fixed for h in hits)
        # The migrated role should have semantic.max_memories instead
        assert role.metadata.name == "test-agent"

    def test_zvec_auto_fixed(self):
        """zvec deprecation is auto-fixed and no longer raises."""
        data = _minimal_role_dict()
        data["spec"]["ingest"] = {"sources": ["*.md"], "store_backend": "zvec"}
        role, hits = validate_role_dict(data)
        assert any(h.id == "DEP002" and h.auto_fixed for h in hits)

    def test_stale_version_accepted(self):
        """spec_version: 1 (stale) is accepted at runtime."""
        data = _minimal_role_dict()
        data["metadata"]["spec_version"] = 1
        role, _hits = validate_role_dict(data)
        assert role.metadata.spec_version == 1


# ---------------------------------------------------------------------------
# validate_flow_dict / validate_team_dict
# ---------------------------------------------------------------------------


class TestValidateFlowDict:
    def test_clean(self):
        flow, hits = validate_flow_dict(_minimal_flow_dict())
        assert flow.metadata.name == "test-flow"
        assert hits == []

    def test_zvec_auto_fixed(self):
        """zvec in flow is auto-fixed and no longer raises."""
        data = _minimal_flow_dict(shared_memory={"store_backend": "zvec"})
        flow, hits = validate_flow_dict(data)
        assert any(h.id == "DEP004" and h.auto_fixed for h in hits)

    def test_hard_break_kind_compose(self):
        """Old kind: Compose triggers a clear migration error."""
        data = {
            "apiVersion": "initrunner/v1",
            "kind": "Compose",
            "metadata": {"name": "old"},
            "spec": {
                "services": {
                    "svc-a": {"role": "a.yaml", "depends_on": ["svc-b"]},
                    "svc-b": {"role": "b.yaml"},
                },
            },
        }
        with pytest.raises(ValueError, match="kind: Compose has been renamed to kind: Flow"):
            validate_flow_dict(data)

    def test_hard_break_services_only(self):
        """spec.services without kind: Compose still triggers."""
        data = {
            "apiVersion": "initrunner/v1",
            "kind": "Flow",
            "metadata": {"name": "old"},
            "spec": {
                "services": {
                    "svc-a": {"role": "a.yaml"},
                },
            },
        }
        with pytest.raises(ValueError, match=r"spec\.services -> spec\.agents"):
            validate_flow_dict(data)


class TestValidateTeamDict:
    def test_clean(self):
        team, hits = validate_team_dict(_minimal_team_dict())
        assert team.metadata.name == "test-team"
        assert hits == []

    def test_zvec_auto_fixed(self):
        """zvec in team is auto-fixed and no longer raises."""
        data = _minimal_team_dict(shared_documents={"store_backend": "zvec"})
        team, hits = validate_team_dict(data)
        assert any(h.id == "DEP005" and h.auto_fixed for h in hits)


# ---------------------------------------------------------------------------
# inspect_role_data
# ---------------------------------------------------------------------------


class TestInspectRoleData:
    def test_clean(self):
        result = inspect_role_data(_minimal_role_dict())
        assert result.role is not None
        assert result.schema_error is None
        assert result.hits == []
        assert result.spec_version == 2

    def test_future_version_raises(self):
        data = _minimal_role_dict()
        data["metadata"]["spec_version"] = 99
        with pytest.raises(ValueError, match="newer than the supported version"):
            inspect_role_data(data)

    def test_stale_version(self):
        data = _minimal_role_dict()
        data["metadata"]["spec_version"] = 1
        result = inspect_role_data(data)
        assert result.spec_version == 1
        assert result.current_version == CURRENT_ROLE_SPEC_VERSION
        assert result.role is not None

    def test_captures_deprecation_errors(self):
        data = _minimal_role_dict()
        data["spec"]["memory"] = {"max_memories": 500}
        result = inspect_role_data(data)
        assert any(h.id == "DEP001" for h in result.hits)
        # inspect is non-raising, schema validation may also fail
        # because max_memories hits the Pydantic guard too

    def test_captures_schema_errors(self):
        data = _minimal_role_dict()
        data["apiVersion"] = "wrong/v1"
        result = inspect_role_data(data)
        assert result.schema_error is not None
        assert result.role is None


# ---------------------------------------------------------------------------
# End-to-end: load_role
# ---------------------------------------------------------------------------


class TestLoadRoleDeprecation:
    def test_auto_fixes_zvec(self, tmp_path: Path):
        from initrunner.agent.loader import load_role

        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-zvec
            spec:
              role: test
              model:
                provider: openai
                name: gpt-5-mini
              ingest:
                sources: ["*.md"]
                store_backend: zvec
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        role = load_role(p)
        assert role.metadata.name == "test-zvec"

    def test_rejects_future_version(self, tmp_path: Path):
        from initrunner.agent.loader import RoleLoadError, load_role

        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-future
              spec_version: 99
            spec:
              role: test
              model:
                provider: openai
                name: gpt-5-mini
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        with pytest.raises(RoleLoadError, match="newer than the supported version"):
            load_role(p)

    def test_auto_fixes_max_memories(self, tmp_path: Path):
        from initrunner.agent.loader import load_role

        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-maxmem
            spec:
              role: test
              model:
                provider: openai
                name: gpt-5-mini
              memory:
                max_memories: 500
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)
        role = load_role(p)
        assert role.metadata.name == "test-maxmem"
