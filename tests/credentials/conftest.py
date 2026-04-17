"""Shared fixtures for credential vault tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from initrunner.credentials import resolver


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Point INITRUNNER_HOME at a tmp dir and reset the lru_cache + resolver."""
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("INITRUNNER_VAULT_PASSPHRASE", raising=False)

    from initrunner.config import get_home_dir

    get_home_dir.cache_clear()
    resolver.reset_resolver()
    yield tmp_path
    get_home_dir.cache_clear()
    resolver.reset_resolver()
