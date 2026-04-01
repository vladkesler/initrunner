"""Tests for LangChain import via /api/builder routes."""

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


_LC_SOURCE_WITH_TOOLS = textwrap.dedent("""\
    import json
    from langchain.agents import create_agent
    from langchain.tools import tool

    @tool
    def greet(name: str) -> str:
        \"\"\"Greet someone.\"\"\"
        return f"Hello {name}"

    agent = create_agent(
        model="openai:gpt-5",
        tools=[greet],
        system_prompt="You are friendly.",
    )
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
          module: _langchain_tools
""")


# ---------------------------------------------------------------------------
# Seed tests
# ---------------------------------------------------------------------------


@patch("initrunner.agent.loader._build_model", return_value=MagicMock())
@patch("pydantic_ai.Agent")
def test_seed_langchain_success(mock_agent_cls, mock_build_model, builder_client):
    """POST /api/builder/seed with mode=langchain returns YAML + sidecar."""
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
            "mode": "langchain",
            "name": "greeter",
            "langchain_source": _LC_SOURCE_WITH_TOOLS,
            "provider": "openai",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "apiVersion" in data["yaml_text"]
    assert data["sidecar_source"] is not None
    assert "def greet" in data["sidecar_source"]
    assert isinstance(data["import_warnings"], list)


def test_seed_langchain_missing_source_400(builder_client):
    """POST /api/builder/seed with mode=langchain but no source returns 400."""
    resp = builder_client.post(
        "/api/builder/seed",
        json={
            "mode": "langchain",
            "name": "test",
            "provider": "openai",
        },
    )
    assert resp.status_code == 400
    assert "langchain_source" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Save tests
# ---------------------------------------------------------------------------


def test_save_with_sidecar(builder_client, role_dir):
    """POST /api/builder/save with sidecar_source writes the sidecar file."""
    yaml_text = textwrap.dedent("""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: sidecar-test
        spec:
          role: You are helpful.
          model:
            provider: openai
            name: gpt-5
          tools:
            - type: custom
              module: _langchain_tools
    """)
    sidecar_source = textwrap.dedent("""\
        def greet(name: str) -> str:
            \"\"\"Greet someone.\"\"\"
            return f"Hello {name}"
    """)

    resp = builder_client.post(
        "/api/builder/save",
        json={
            "yaml_text": yaml_text,
            "directory": str(role_dir),
            "filename": "sidecar-test.yaml",
            "sidecar_source": sidecar_source,
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    # YAML file written
    yaml_path = role_dir / "sidecar-test.yaml"
    assert yaml_path.exists()

    # Sidecar file written (hyphens -> underscores for valid Python module)
    sidecar_path = role_dir / "sidecar_test_tools.py"
    assert sidecar_path.exists()
    assert "def greet" in sidecar_path.read_text()

    # Module name in YAML resolved from placeholder
    yaml_content = yaml_path.read_text()
    assert "sidecar_test_tools" in yaml_content
    assert "_langchain_tools" not in yaml_content

    # Response includes generated assets
    assert len(data["generated_assets"]) == 1
    assert "sidecar_test_tools.py" in data["generated_assets"][0]


def test_save_without_sidecar_no_extra_files(builder_client, role_dir):
    """POST /api/builder/save without sidecar_source writes only YAML."""
    yaml_text = textwrap.dedent("""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: no-sidecar
        spec:
          role: You are helpful.
          model:
            provider: openai
            name: gpt-5
    """)

    resp = builder_client.post(
        "/api/builder/save",
        json={
            "yaml_text": yaml_text,
            "directory": str(role_dir),
            "filename": "no-sidecar.yaml",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["generated_assets"] == []
    # No sidecar file
    py_files = list(role_dir.glob("*.py"))
    assert len(py_files) == 0
