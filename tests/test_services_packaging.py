"""Tests for packaging services layer."""

import textwrap
from unittest.mock import MagicMock, patch

import pytest

MINIMAL_ROLE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: test-agent
      description: A test agent
      version: "1.0.0"
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
""")


class TestPublishRole:
    def test_publish_creates_bundle_and_pushes(self, tmp_path, monkeypatch):
        from initrunner.services.packaging import publish_role

        role_file = tmp_path / "role.yaml"
        role_file.write_text(MINIMAL_ROLE_YAML)

        cache_dir = tmp_path / "cache" / "bundles"
        monkeypatch.setattr(
            "initrunner.config.get_bundles_cache_dir",
            lambda: cache_dir,
        )

        mock_client = MagicMock()
        mock_client.push.return_value = "sha256:abc123"

        with patch(
            "initrunner.packaging.oci.OCIClient",
            return_value=mock_client,
        ):
            digest = publish_role(role_file, "oci://ghcr.io/org/my-agent", tag="1.0.0")

        assert digest == "sha256:abc123"
        mock_client.push.assert_called_once()

    def test_publish_with_custom_tag(self, tmp_path, monkeypatch):
        from initrunner.services.packaging import publish_role

        role_file = tmp_path / "role.yaml"
        role_file.write_text(MINIMAL_ROLE_YAML)

        cache_dir = tmp_path / "cache"
        monkeypatch.setattr(
            "initrunner.config.get_bundles_cache_dir",
            lambda: cache_dir,
        )

        mock_client = MagicMock()
        mock_client.push.return_value = "sha256:def456"

        with patch(
            "initrunner.packaging.oci.OCIClient",
            return_value=mock_client,
        ):
            digest = publish_role(role_file, "oci://ghcr.io/org/agent", tag="v2.0")

        assert digest == "sha256:def456"


class TestPullRole:
    def test_pull_creates_directory(self, tmp_path, monkeypatch):
        from initrunner.services.packaging import pull_role

        roles_dir = tmp_path / "roles"
        monkeypatch.setattr("initrunner.config.get_roles_dir", lambda: roles_dir)

        mock_client = MagicMock()

        def fake_pull(target_dir):
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "role.yaml").write_text(MINIMAL_ROLE_YAML)
            return target_dir

        mock_client.pull.side_effect = fake_pull

        with patch(
            "initrunner.packaging.oci.OCIClient",
            return_value=mock_client,
        ):
            result = pull_role("oci://ghcr.io/org/my-agent:1.0")

        assert result.exists()
        assert (result / "role.yaml").exists()

    def test_pull_existing_without_force(self, tmp_path, monkeypatch):
        from initrunner.registry import RoleExistsError
        from initrunner.services.packaging import pull_role

        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()

        # Create existing directory
        existing = roles_dir / "oci__ghcr.io__org__my-agent"
        existing.mkdir()

        monkeypatch.setattr("initrunner.config.get_roles_dir", lambda: roles_dir)

        with pytest.raises(RoleExistsError, match="already installed"):
            pull_role("oci://ghcr.io/org/my-agent:1.0")
