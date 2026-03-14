"""Tests for agent_principal_from_role() and Principal with Any attrs."""

from __future__ import annotations

from initrunner.agent.schema.base import Metadata
from initrunner.authz import Principal, agent_principal_from_role


class TestAgentPrincipalFromRole:
    def test_basic_principal(self):
        meta = Metadata(name="my-agent", description="test")
        p = agent_principal_from_role(meta)
        assert p.id == "agent:my-agent"
        assert p.roles == ["agent"]
        assert p.attrs["team"] == ""
        assert p.attrs["author"] == ""
        assert p.attrs["tags"] == []
        assert p.attrs["version"] == ""

    def test_team_role_added(self):
        meta = Metadata(name="my-agent", description="test", team="platform")
        p = agent_principal_from_role(meta)
        assert "agent" in p.roles
        assert "team:platform" in p.roles
        assert len(p.roles) == 2

    def test_no_team_no_extra_role(self):
        meta = Metadata(name="my-agent", description="test", team="")
        p = agent_principal_from_role(meta)
        assert p.roles == ["agent"]

    def test_attrs_populated(self):
        meta = Metadata(
            name="my-agent",
            description="test",
            team="backend",
            author="alice",
            tags=["trusted", "code"],
            version="1.2.3",
        )
        p = agent_principal_from_role(meta)
        assert p.attrs["team"] == "backend"
        assert p.attrs["author"] == "alice"
        assert p.attrs["version"] == "1.2.3"

    def test_tags_as_list_not_csv(self):
        """Tags must be stored as a native list, not CSV string."""
        meta = Metadata(name="my-agent", description="test", tags=["a", "b", "c"])
        p = agent_principal_from_role(meta)
        assert isinstance(p.attrs["tags"], list)
        assert p.attrs["tags"] == ["a", "b", "c"]

    def test_tags_is_copy(self):
        """Tags list in attrs should be a copy, not a reference."""
        tags = ["x", "y"]
        meta = Metadata(name="my-agent", description="test", tags=tags)
        p = agent_principal_from_role(meta)
        tags.append("z")
        assert p.attrs["tags"] == ["x", "y"]


class TestPrincipalAttrsAny:
    def test_attrs_accepts_any_values(self):
        """Principal.attrs accepts dict[str, Any], not just dict[str, str]."""
        p = Principal(
            id="test",
            roles=["agent"],
            attrs={
                "tags": ["a", "b"],
                "count": 42,
                "nested": {"key": "value"},
            },
        )
        assert p.attrs["tags"] == ["a", "b"]
        assert p.attrs["count"] == 42
        assert p.attrs["nested"] == {"key": "value"}

    def test_attrs_default_empty(self):
        p = Principal(id="test", roles=["agent"])
        assert p.attrs == {}
