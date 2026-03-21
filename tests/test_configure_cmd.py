"""Tests for the `initrunner configure` command."""

import textwrap

import pytest
import yaml

from initrunner.cli.role_cmd import _update_role_yaml

ROLE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: test-agent
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
        temperature: 0.3
""")


@pytest.fixture()
def local_role(tmp_path):
    """Write a local role YAML and return its path."""
    p = tmp_path / "role.yaml"
    p.write_text(ROLE_YAML)
    return p


class TestUpdateRoleYaml:
    def test_updates_provider_and_model(self, local_role):
        _update_role_yaml(local_role, "anthropic", "claude-sonnet-4-5-20250929")
        data = yaml.safe_load(local_role.read_text())
        assert data["spec"]["model"]["provider"] == "anthropic"
        assert data["spec"]["model"]["name"] == "claude-sonnet-4-5-20250929"

    def test_preserves_other_fields(self, local_role):
        _update_role_yaml(local_role, "groq", "llama-3.3-70b")
        data = yaml.safe_load(local_role.read_text())
        assert data["spec"]["model"]["temperature"] == 0.3
        assert data["metadata"]["name"] == "test-agent"

    def test_clears_base_url_and_api_key_env(self, tmp_path):
        yaml_with_custom = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: custom-agent
            spec:
              role: You are helpful.
              model:
                provider: openai
                name: gpt-4o
                base_url: https://custom.example.com/v1
                api_key_env: CUSTOM_KEY
        """)
        p = tmp_path / "role.yaml"
        p.write_text(yaml_with_custom)
        _update_role_yaml(p, "anthropic", "claude-sonnet-4-5-20250929")
        data = yaml.safe_load(p.read_text())
        assert "base_url" not in data["spec"]["model"]
        assert "api_key_env" not in data["spec"]["model"]


class TestConfigureNonInteractive:
    def test_configure_local_file(self, local_role):
        """Non-interactive configure updates the YAML file."""
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["configure", str(local_role), "--provider", "groq"])
        assert result.exit_code == 0
        assert "groq" in result.output

        data = yaml.safe_load(local_role.read_text())
        assert data["spec"]["model"]["provider"] == "groq"

    def test_configure_with_provider_and_model(self, local_role):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["configure", str(local_role), "--provider", "ollama", "--model", "deepseek-coder"],
        )
        assert result.exit_code == 0

        data = yaml.safe_load(local_role.read_text())
        assert data["spec"]["model"]["provider"] == "ollama"
        assert data["spec"]["model"]["name"] == "deepseek-coder"
