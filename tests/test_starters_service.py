"""Tests for initrunner.services.starters."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from initrunner.services.starters import (
    STARTERS_DIR,
    StarterNotFoundError,
    check_prerequisites,
    copy_starter,
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


class TestGetStarterForPath:
    def test_directory_starter_uses_slug_not_stem(self):
        from initrunner.services.starters import get_starter_for_path

        path = resolve_starter_path("helpdesk")
        assert path is not None
        entry = get_starter_for_path(path)
        assert entry is not None
        assert entry.slug == "helpdesk"

    def test_single_file_starter_uses_stem(self):
        from initrunner.services.starters import get_starter_for_path

        path = resolve_starter_path("memory")
        assert path is not None
        entry = get_starter_for_path(path)
        assert entry is not None
        assert entry.slug == "memory"


class TestStarterContent:
    def test_empty_local_dir_is_missing_not_ready(self, tmp_path):
        from initrunner.services.starters import starter_content

        entry = get_starter("helpdesk")
        assert entry is not None
        empty = tmp_path / "knowledge-base"
        empty.mkdir()
        content = starter_content(entry, cwd=tmp_path)
        assert content.kind == "missing"

    def test_local_files_win(self, tmp_path):
        from initrunner.services.starters import starter_content

        entry = get_starter("helpdesk")
        assert entry is not None
        kb = tmp_path / "knowledge-base"
        kb.mkdir()
        (kb / "policy.md").write_text("# Policy\n", encoding="utf-8")
        content = starter_content(entry, cwd=tmp_path)
        assert content.kind == "local"
        assert any(p.name == "policy.md" for p in content.files)

    def test_pdf_source_requires_ingest_extra(self):
        from initrunner.services.starters import _detect_requires_extras

        extras = _detect_requires_extras({"spec": {"ingest": {"sources": ["./docs/**/*.pdf"]}}})
        assert "ingest" in extras

    def test_md_source_does_not_require_ingest_extra(self):
        from initrunner.services.starters import _detect_requires_extras

        extras = _detect_requires_extras({"spec": {"ingest": {"sources": ["./docs/**/*.md"]}}})
        assert "ingest" not in extras


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
        assert path.name == "role.yaml"
        assert path.parent.name == "helpdesk"

    def test_resolves_composite(self):
        path = resolve_starter_path("pipeline")
        assert path is not None
        assert path.is_file()
        assert path.name == "flow.yaml"

    def test_returns_none_for_unknown(self):
        assert resolve_starter_path("does-not-exist") is None

    def test_rejects_parent_traversal(self):
        # The slug is request-supplied (builder starter_slug); ../ must not escape.
        assert resolve_starter_path("../../../../etc/passwd") is None
        assert resolve_starter_path("../" * 6 + "etc/hosts") is None

    def test_rejects_absolute_name(self):
        assert resolve_starter_path("/etc/passwd") is None

    def test_rejects_symlink_escape(self, tmp_path, monkeypatch):
        # A symlink inside the starters dir pointing outside must not be followed
        # into an arbitrary read.
        import initrunner.services.starters as starters_mod

        fake_starters = tmp_path / "_starters"
        fake_starters.mkdir()
        secret = tmp_path / "secret.yaml"
        secret.write_text("kind: Secret\n", encoding="utf-8")
        (fake_starters / "evil.yaml").symlink_to(secret)
        monkeypatch.setattr(starters_mod, "STARTERS_DIR", fake_starters)

        assert resolve_starter_path("evil") is None

    def test_confined_path_still_resolves(self, tmp_path, monkeypatch):
        import initrunner.services.starters as starters_mod

        fake_starters = tmp_path / "_starters"
        fake_starters.mkdir()
        (fake_starters / "ok.yaml").write_text("kind: Agent\n", encoding="utf-8")
        monkeypatch.setattr(starters_mod, "STARTERS_DIR", fake_starters)

        path = resolve_starter_path("ok")
        assert path is not None and path.is_file()
        assert path.resolve().is_relative_to(fake_starters.resolve())


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

    def test_helpdesk_uses_sample_docs(self):
        entry = get_starter("helpdesk")
        assert entry is not None
        assert len(entry.requires_user_data) > 0, "helpdesk should require user data paths"
        from initrunner.services.starters import starter_content

        content = starter_content(entry, cwd=Path("/tmp/empty-initrunner-cwd"))
        assert content.kind == "bundled"
        _errors, warnings = check_prerequisites(entry)
        assert any("sample docs" in w.lower() for w in warnings)

    def test_helpdesk_md_sources_do_not_require_ingest_extra(self):
        entry = get_starter("helpdesk")
        assert entry is not None
        assert "ingest" not in entry.requires_extras

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


class TestApplyContentRoot:
    def test_rewrites_filesystem_to_bundled_samples(self, tmp_path):
        from initrunner.agent.loader import load_role
        from initrunner.services.starters import apply_starter_content_root, get_starter

        entry = get_starter("helpdesk")
        assert entry is not None
        role = load_role(entry.path)
        rewritten = apply_starter_content_root(role, entry.path)
        fs = next(t for t in rewritten.spec.tools if t.type == "filesystem")
        assert Path(fs.root_path).is_absolute()
        assert (Path(fs.root_path) / "faq.md").is_file()


class TestSampleFilesPackaged:
    def test_helpdesk_samples_exist_in_package(self):
        kb = STARTERS_DIR / "helpdesk" / "knowledge-base"
        assert (kb / "getting-started.md").is_file()
        assert (kb / "faq.md").is_file()


class TestGlobalEnvToken:
    def test_token_in_global_env_counts(self, tmp_path, monkeypatch):
        from initrunner.config import get_home_dir

        home = tmp_path / "irhome"
        home.mkdir()
        (home / ".env").write_text("DISCORD_BOT_TOKEN=from-file\n", encoding="utf-8")
        monkeypatch.setenv("INITRUNNER_HOME", str(home))
        get_home_dir.cache_clear()
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

        entry = get_starter("discord")
        assert entry is not None
        errors, _warnings = check_prerequisites(entry)
        assert not any("DISCORD_BOT_TOKEN" in e for e in errors)
        get_home_dir.cache_clear()


class TestStartersDir:
    def test_starters_dir_exists(self):
        assert STARTERS_DIR.is_dir()

    def test_starters_dir_has_yaml_files(self):
        yaml_files = list(STARTERS_DIR.glob("*.yaml"))
        assert len(yaml_files) >= 5


class TestCopyStarter:
    """copy_starter is the offline starter copy behind `examples copy`."""

    def test_single_file_starter_lands_as_role_yaml(self, tmp_path: Path):
        written = copy_starter("memory", tmp_path)
        assert written == [tmp_path / "role.yaml"]
        assert (tmp_path / "role.yaml").read_text().strip()

    def test_composite_starter_keeps_its_tree(self, tmp_path: Path):
        written = copy_starter("pipeline", tmp_path)
        rel = {p.relative_to(tmp_path).as_posix() for p in written}
        assert "flow.yaml" in rel
        assert any(r.startswith("roles/") for r in rel)

    def test_creates_missing_output_directory(self, tmp_path: Path):
        target = tmp_path / "nested" / "deeper"
        copy_starter("memory", target)
        assert (target / "role.yaml").is_file()

    def test_unknown_slug_raises_and_writes_nothing(self, tmp_path: Path):
        with pytest.raises(StarterNotFoundError):
            copy_starter("no-such-starter", tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_collision_raises_before_writing_anything(self, tmp_path: Path):
        (tmp_path / "roles").mkdir()
        (tmp_path / "roles" / "notifier.yaml").write_text("mine")

        with pytest.raises(FileExistsError):
            copy_starter("pipeline", tmp_path)

        assert not (tmp_path / "flow.yaml").exists()
        assert (tmp_path / "roles" / "notifier.yaml").read_text() == "mine"

    def test_copied_role_is_a_valid_role(self, tmp_path: Path):
        """A copied starter must load, not just land on disk."""
        from initrunner.agent.loader import load_role

        copy_starter("memory", tmp_path)
        role = load_role(tmp_path / "role.yaml")
        assert role.metadata.name


_MCP = {"mcp": {"transport": "sse", "url": "https://mcp.example"}}

# (case id, document body, expected (extra, feature) pairs). Each body is checked
# as a flat document and inside an envelope ``spec``.
_EXTRA_CASES = [
    (
        "markdown-text-html-ingest",
        {"ingest": {"sources": ["./docs/**/*.md", "./notes/*.txt", "./site/*.html"]}},
        [("vector", "ingest")],
    ),
    (
        "pdf-ingest",
        {"ingest": {"sources": ["./docs/**/*.pdf"]}},
        [("ingest", "ingest"), ("vector", "ingest")],
    ),
    (
        "docx-upper",
        {"ingest": {"sources": ["./in/*.DOCX"]}},
        [("ingest", "ingest"), ("vector", "ingest")],
    ),
    (
        "xlsx-ingest",
        {"ingest": {"sources": ["./sheets/q3.xlsx"]}},
        [("ingest", "ingest"), ("vector", "ingest")],
    ),
    ("empty-memory", {"memory": {}}, [("vector", "memory")]),
    ("null-memory", {"memory": None}, []),
    (
        "ingest-local-embeddings",
        {"ingest": {"sources": ["*.md"], "embeddings": {"provider": "local"}}},
        [("local-embeddings", "ingest.embeddings"), ("vector", "ingest")],
    ),
    (
        "memory-local-embeddings",
        {"memory": {"embeddings": {"provider": "local"}}},
        [("local-embeddings", "memory.embeddings"), ("vector", "memory")],
    ),
    (
        "shared-documents-local-embeddings",
        {"shared_documents": {"enabled": True, "embeddings": {"provider": "local", "model": "m"}}},
        [("local-embeddings", "shared_documents.embeddings"), ("vector", "shared_documents")],
    ),
    (
        "shared-documents-pdf",
        {
            "shared_documents": {
                "enabled": True,
                "sources": ["./handbook/*.md", "./contracts/**/*.pdf"],
                "embeddings": {"provider": "openai", "model": "text-embedding-3-small"},
            }
        },
        [("ingest", "shared_documents"), ("vector", "shared_documents")],
    ),
    ("shared-memory-enabled", {"shared_memory": {"enabled": True}}, [("vector", "shared_memory")]),
    ("shared-memory-disabled", {"shared_memory": {"enabled": False}}, []),
    (
        "inline-child-tools",
        {"agents": {"a": {"prompt": "p", "tools": ["search", _MCP]}, "b": "prompt only"}},
        [("mcp", "mcp"), ("search", "search")],
    ),
    (
        "envelope-team-personas",
        {"personas": {"a": {"role": "p", "tools": [{"type": "search"}]}, "b": "p"}},
        [("search", "search")],
    ),
    ("empty-observability", {"observability": {}}, [("observability", "observability")]),
    ("pdf-extract-tool", {"tools": [{"pdf_extract": {}}]}, [("ingest", "pdf_extract")]),
    ("mcp-capability", {"capabilities": ["MCP"]}, [("mcp", "MCP capability")]),
    (
        "mcp-capability-mapping",
        {"capabilities": [{"MCP": {"url": "https://mcp.example"}}]},
        [("mcp", "MCP capability")],
    ),
    ("trigger", {"triggers": [{"type": "telegram"}]}, [("telegram", "telegram")]),
    (
        "one-entry-per-extra-sorted",
        {"tools": ["web_scraper", "search", "web_reader"], "memory": {}},
        [("search", "search"), ("vector", "memory")],
    ),
    ("nothing", {"tools": ["think", "web_reader"]}, []),
]


def _as_flat(body: dict) -> dict:
    return {"name": "probe", "prompt": "p", **body}


def _as_envelope(body: dict) -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": "probe"},
        "spec": body,
    }


class TestDetectExtraRequirements:
    @pytest.mark.parametrize("wrap", [_as_flat, _as_envelope], ids=["flat", "envelope"])
    @pytest.mark.parametrize(
        ("body", "expected"), [c[1:] for c in _EXTRA_CASES], ids=[c[0] for c in _EXTRA_CASES]
    )
    def test_case(self, wrap, body, expected):
        from initrunner.services.starters import detect_extra_requirements

        found = [(r.extra, r.feature) for r in detect_extra_requirements(wrap(body))]
        assert found == expected

    def test_starter_wrapper_lists_extra_names(self):
        from initrunner.services.starters import _detect_requires_extras

        assert _detect_requires_extras(_as_flat({"memory": {}, "tools": ["search"]})) == [
            "search",
            "vector",
        ]

    def test_empty_memory_starters_need_vector(self):
        for slug in ("memory", "telegram"):
            assert "vector" in get_starter(slug).requires_extras, slug

    def test_inline_child_search_is_seen(self):
        assert "search" in get_starter("scholar").requires_extras

    @pytest.mark.parametrize("slug", ["scholar", "writer"])
    def test_shared_memory_starters_need_vector(self, slug):
        assert "vector" in get_starter(slug).requires_extras

    def test_child_trigger_token_is_a_required_env(self):
        from initrunner.services.starters import _detect_requires_env

        data = _as_flat(
            {"prompt": None, "agents": {"bot": {"prompt": "p", "triggers": [{"type": "telegram"}]}}}
        )
        assert _detect_requires_env("", data) == ["TELEGRAM_BOT_TOKEN"]
