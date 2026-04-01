"""Tests for PydanticAI import via /api/builder routes."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.deps import RoleCache, get_role_cache


class _BuilderRoleCache(RoleCache):
    def __init__(self, role_dirs: list[Path]):
        settings = DashboardSettings()
        settings.extra_role_dirs = list(role_dirs)
        self._settings = settings
        self._cache: dict = {}
        self._role_dirs = role_dirs

    def refresh(self):
        return self._cache


@pytest.fixture
def role_dir(tmp_path):
    return tmp_path / "roles"


@pytest.fixture
def builder_client(role_dir):
    role_dir.mkdir(parents=True, exist_ok=True)
    settings = DashboardSettings()
    app = create_app(settings)
    cache = _BuilderRoleCache([role_dir])
    app.dependency_overrides[get_role_cache] = lambda: cache
    return TestClient(app)


_PAI_SOURCE_WITH_TOOLS = textwrap.dedent("""\
    import httpx
    from pydantic_ai import Agent, RunContext

    agent = Agent("openai:gpt-5", system_prompt="You are friendly.")

    @agent.tool
    def greet(ctx: RunContext[str], name: str) -> str:
        \"\"\"Greet someone.\"\"\"
        return f"Hello {name}"
""")

_VALID_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: greeter
      spec_version: 2
    spec:
      role: You are friendly.
      model:
        provider: openai
        name: gpt-5
      tools:
        - type: custom
          module: _pydanticai_tools
""")


# ---------------------------------------------------------------------------
# Seed tests
# ---------------------------------------------------------------------------


@patch("initrunner.agent.loader._build_model", return_value=MagicMock())
@patch("pydantic_ai.Agent")
def test_seed_pydanticai_success(mock_agent_cls, mock_build_model, builder_client):
    """POST /api/builder/seed with mode=pydanticai returns YAML + sidecar."""
    from dataclasses import dataclass

    @dataclass
    class _FakeResult:
        output: str
        _messages: list

        def all_messages(self):
            return self._messages

    fake = MagicMock()
    fake.run_sync.return_value = _FakeResult(
        output=f"```yaml\n{_VALID_YAML}```",
        _messages=[],
    )
    mock_agent_cls.return_value = fake

    resp = builder_client.post(
        "/api/builder/seed",
        json={
            "mode": "pydanticai",
            "name": "greeter",
            "pydanticai_source": _PAI_SOURCE_WITH_TOOLS,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "apiVersion" in data["yaml_text"]
    assert data["sidecar_source"] is not None
    assert "def greet" in data["sidecar_source"]
    assert isinstance(data["import_warnings"], list)


def test_seed_pydanticai_missing_source_400(builder_client):
    """POST /api/builder/seed with mode=pydanticai but no source returns 400."""
    resp = builder_client.post(
        "/api/builder/seed",
        json={
            "mode": "pydanticai",
            "name": "test",
            "provider": "openai",
        },
    )
    assert resp.status_code == 400
    assert "pydanticai_source" in resp.json()["detail"]
