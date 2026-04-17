"""Tests for initrunner.services.starters."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from initrunner.services.starters import (
    STARTERS_DIR,
    check_prerequisites,
    derive_features,
    get_starter,
    list_starters,
    resolve_starter_path,
)


class TestListStarters:
    def test_returns_non_empty(self):
        starters = list_starters()
        assert len(starters) > 0

    def test_all_entries_have_required_fields(self):
        for entry in list_starters():
            assert entry.slug
            assert entry.name
            assert entry.kind in ("Agent", "Team", "Flow")
            assert isinstance(entry.path, Path)
            assert entry.path.is_file()

    def test_includes_agent_starters(self):
        slugs = {e.slug for e in list_starters()}
        assert "helpdesk" in slugs
        assert "memory" in slugs
        assert "librarian" in slugs

    def test_includes_team_starter(self):
        slugs = {e.slug for e in list_starters()}
        assert "reviewer" in slugs

    def test_includes_composite_starters(self):
        slugs = {e.slug for e in list_starters()}
        assert "pipeline" in slugs
        assert "triage" in slugs

    def test_curated_order_preserved(self):
        starters = list_starters()
        slugs = [e.slug for e in starters]
        # First two should be the hero starters in order
        assert slugs[0] == "helpdesk"
        assert slugs[1] == "reviewer"

    def test_reviewer_is_team_kind(self):
        entry = get_starter("reviewer")
        assert entry is not None
        assert entry.kind == "Team"

    def test_composite_starters_are_flow_kind(self):
        entry = get_starter("pipeline")
        assert entry is not None
        assert entry.kind == "Flow"


class TestGetStarter:
    def test_existing_starter(self):
        entry = get_starter("helpdesk")
        assert entry is not None
        assert entry.slug == "helpdesk"
        assert entry.name == "helpdesk"

    def test_nonexistent_starter(self):
        entry = get_starter("nonexistent-agent")
        assert entry is None


class TestResolveStarterPath:
    def test_resolves_single_file(self):
        path = resolve_starter_path("helpdesk")
        assert path is not None
        assert path.is_file()
        assert path.name == "helpdesk.yaml"

    def test_resolves_composite(self):
        path = resolve_starter_path("pipeline")
        assert path is not None
        assert path.is_file()
        assert path.name == "flow.yaml"

    def test_returns_none_for_unknown(self):
        assert resolve_starter_path("does-not-exist") is None


class TestDeriveFeatures:
    def test_rag_feature(self):
        spec = {"ingest": {"sources": ["./docs/**/*.md"]}}
        features = derive_features(spec)
        assert "RAG" in features

    def test_memory_feature(self):
        spec = {"memory": {"semantic": {"enabled": True}}}
        features = derive_features(spec)
        assert "Memory" in features

    def test_web_feature(self):
        spec = {"tools": [{"type": "search"}]}
        features = derive_features(spec)
        assert "Web" in features

    def test_git_feature(self):
        spec = {"tools": [{"type": "git", "repo_path": "."}]}
        features = derive_features(spec)
        assert "Git" in features

    def test_empty_spec(self):
        assert derive_features({}) == []


class TestCheckPrerequisites:
    def test_telegram_requires_token(self):
        entry = get_starter("telegram")
        assert entry is not None
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("initrunner.agent.loader._load_dotenv"),
        ):
            errors, _warnings = check_prerequisites(entry)
            env_errors = [e for e in errors if "TELEGRAM_BOT_TOKEN" in e]
            assert len(env_errors) > 0

    def test_discord_requires_token(self):
        entry = get_starter("discord")
        assert entry is not None
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("initrunner.agent.loader._load_dotenv"),
        ):
            errors, _warnings = check_prerequisites(entry)
            env_errors = [e for e in errors if "DISCORD_BOT_TOKEN" in e]
            assert len(env_errors) > 0

    def test_helpdesk_warns_about_user_data(self):
        entry = get_starter("helpdesk")
        assert entry is not None
        assert len(entry.requires_user_data) > 0, "helpdesk should require user data paths"
        # check_prerequisites should produce warnings for missing dirs
        _errors, warnings = check_prerequisites(entry)
        data_warnings = [w for w in warnings if "knowledge-base" in w]
        assert len(data_warnings) > 0

    def test_helpdesk_requires_ingest_extra(self):
        entry = get_starter("helpdesk")
        assert entry is not None
        assert "ingest" in entry.requires_extras

    def test_memory_starter_has_no_errors(self):
        """memory starter needs no env vars or extras beyond base."""
        entry = get_starter("memory")
        assert entry is not None
        assert len(entry.requires_env) == 0
        errors, _warnings = check_prerequisites(entry)
        env_errors = [e for e in errors if "Environment variable" in e]
        assert len(env_errors) == 0

    def test_telegram_requires_extras(self):
        entry = get_starter("telegram")
        assert entry is not None
        assert "telegram" in entry.requires_extras
        assert "search" in entry.requires_extras


class TestStartersDir:
    def test_starters_dir_exists(self):
        assert STARTERS_DIR.is_dir()

    def test_starters_dir_has_yaml_files(self):
        yaml_files = list(STARTERS_DIR.glob("*.yaml"))
        assert len(yaml_files) >= 5
