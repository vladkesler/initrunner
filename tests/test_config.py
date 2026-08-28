"""Tests for the centralized config module."""

from pathlib import Path

import pytest

from initrunner.config import (
    get_audit_db_path,
    get_global_env_path,
    get_home_dir,
    get_memory_dir,
    get_roles_dir,
    get_skills_dir,
    get_stores_dir,
)


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    """Clear lru_cache before and after each test."""
    get_home_dir.cache_clear()
    # Remove env vars that could interfere
    monkeypatch.delenv("INITRUNNER_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("INITRUNNER_AUDIT_DB", raising=False)
    yield
    get_home_dir.cache_clear()


class TestGetHomeDir:
    def test_default_fallback(self):
        result = get_home_dir()
        assert result == Path.home() / ".initrunner"

    def test_initrunner_home_override(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_HOME", "/tmp/custom-ir")
        get_home_dir.cache_clear()
        result = get_home_dir()
        assert result == Path("/tmp/custom-ir")

    def test_xdg_data_home_fallback(self, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg-data")
        get_home_dir.cache_clear()
        result = get_home_dir()
        assert result == Path("/tmp/xdg-data/initrunner")

    def test_initrunner_home_takes_precedence_over_xdg(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_HOME", "/tmp/custom-ir")
        monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg-data")
        get_home_dir.cache_clear()
        result = get_home_dir()
        assert result == Path("/tmp/custom-ir")

    def test_cache_returns_same_object(self):
        a = get_home_dir()
        b = get_home_dir()
        assert a is b


class TestDerivedPaths:
    def test_audit_db_path(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_HOME", "/tmp/ir")
        get_home_dir.cache_clear()
        assert get_audit_db_path() == Path("/tmp/ir/audit.db")

    def test_audit_db_env_overrides_home(self, monkeypatch):
        """INITRUNNER_AUDIT_DB wins over the home-derived default."""
        monkeypatch.setenv("INITRUNNER_HOME", "/tmp/ir")
        monkeypatch.setenv("INITRUNNER_AUDIT_DB", "/tmp/elsewhere/custom.db")
        get_home_dir.cache_clear()
        assert get_audit_db_path() == Path("/tmp/elsewhere/custom.db")

    def test_audit_db_env_read_per_call(self, monkeypatch):
        """Not cached: a changed env var takes effect without a cache_clear."""
        monkeypatch.setenv("INITRUNNER_AUDIT_DB", "/tmp/first.db")
        assert get_audit_db_path() == Path("/tmp/first.db")
        monkeypatch.setenv("INITRUNNER_AUDIT_DB", "/tmp/second.db")
        assert get_audit_db_path() == Path("/tmp/second.db")

    def test_audit_db_empty_env_falls_back(self, monkeypatch):
        """An empty value is not a path; fall back to the home default."""
        monkeypatch.setenv("INITRUNNER_HOME", "/tmp/ir")
        monkeypatch.setenv("INITRUNNER_AUDIT_DB", "")
        get_home_dir.cache_clear()
        assert get_audit_db_path() == Path("/tmp/ir/audit.db")

    def test_stores_dir(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_HOME", "/tmp/ir")
        get_home_dir.cache_clear()
        assert get_stores_dir() == Path("/tmp/ir/stores")

    def test_memory_dir(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_HOME", "/tmp/ir")
        get_home_dir.cache_clear()
        assert get_memory_dir() == Path("/tmp/ir/memory")

    def test_roles_dir(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_HOME", "/tmp/ir")
        get_home_dir.cache_clear()
        assert get_roles_dir() == Path("/tmp/ir/roles")

    def test_skills_dir(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_HOME", "/tmp/ir")
        get_home_dir.cache_clear()
        assert get_skills_dir() == Path("/tmp/ir/skills")

    def test_global_env_path(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_HOME", "/tmp/ir")
        get_home_dir.cache_clear()
        assert get_global_env_path() == Path("/tmp/ir/.env")
