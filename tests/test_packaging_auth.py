"""Tests for OCI auth credential resolution."""

import base64
import json

from initrunner.packaging.auth import (
    _decode_auth_entry,
    load_docker_config_auth,
    resolve_auth,
    save_auth,
)


class TestDecodeAuthEntry:
    def test_valid_entry(self):
        encoded = base64.b64encode(b"user:pass").decode()
        result = _decode_auth_entry({"auth": encoded})
        assert result is not None
        assert result.username == "user"
        assert result.password == "pass"

    def test_password_with_colon(self):
        encoded = base64.b64encode(b"user:pass:word:extra").decode()
        result = _decode_auth_entry({"auth": encoded})
        assert result is not None
        assert result.username == "user"
        assert result.password == "pass:word:extra"

    def test_missing_auth_field(self):
        result = _decode_auth_entry({})
        assert result is None

    def test_empty_auth_field(self):
        result = _decode_auth_entry({"auth": ""})
        assert result is None

    def test_invalid_base64(self):
        result = _decode_auth_entry({"auth": "not-valid-base64!!!"})
        assert result is None


class TestSaveAuth:
    def test_save_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "initrunner.packaging.auth._get_oci_auth_path",
            lambda: tmp_path / "oci-auth.json",
        )
        save_auth("ghcr.io", "myuser", "mytoken")

        auth_path = tmp_path / "oci-auth.json"
        assert auth_path.exists()

        data = json.loads(auth_path.read_text())
        assert "ghcr.io" in data["auths"]

        decoded = base64.b64decode(data["auths"]["ghcr.io"]["auth"]).decode()
        assert decoded == "myuser:mytoken"

    def test_save_preserves_existing(self, tmp_path, monkeypatch):
        auth_path = tmp_path / "oci-auth.json"
        auth_path.write_text(
            json.dumps({"auths": {"docker.io": {"auth": base64.b64encode(b"old:cred").decode()}}})
        )

        monkeypatch.setattr(
            "initrunner.packaging.auth._get_oci_auth_path",
            lambda: auth_path,
        )
        save_auth("ghcr.io", "myuser", "mytoken")

        data = json.loads(auth_path.read_text())
        assert "docker.io" in data["auths"]
        assert "ghcr.io" in data["auths"]


class TestResolveAuth:
    def test_env_vars_take_priority(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_OCI_USERNAME", "envuser")
        monkeypatch.setenv("INITRUNNER_OCI_PASSWORD", "envpass")

        result = resolve_auth("any-registry.io")
        assert result is not None
        assert result.username == "envuser"
        assert result.password == "envpass"

    def test_oci_auth_json(self, tmp_path, monkeypatch):
        monkeypatch.delenv("INITRUNNER_OCI_USERNAME", raising=False)
        monkeypatch.delenv("INITRUNNER_OCI_PASSWORD", raising=False)

        auth_path = tmp_path / "oci-auth.json"
        encoded = base64.b64encode(b"fileuser:filepass").decode()
        auth_path.write_text(json.dumps({"auths": {"ghcr.io": {"auth": encoded}}}))

        monkeypatch.setattr(
            "initrunner.packaging.auth._get_oci_auth_path",
            lambda: auth_path,
        )

        result = resolve_auth("ghcr.io")
        assert result is not None
        assert result.username == "fileuser"

    def test_no_auth_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.delenv("INITRUNNER_OCI_USERNAME", raising=False)
        monkeypatch.delenv("INITRUNNER_OCI_PASSWORD", raising=False)
        monkeypatch.setattr(
            "initrunner.packaging.auth._get_oci_auth_path",
            lambda: tmp_path / "nonexistent.json",
        )
        monkeypatch.setattr(
            "initrunner.packaging.auth.load_docker_config_auth",
            lambda _: None,
        )

        result = resolve_auth("unknown-registry.io")
        assert result is None


class TestDockerConfigAuth:
    def test_base64_auth(self, tmp_path, monkeypatch):
        docker_dir = tmp_path / ".docker"
        docker_dir.mkdir()
        config = docker_dir / "config.json"

        encoded = base64.b64encode(b"dockeruser:dockerpass").decode()
        config.write_text(json.dumps({"auths": {"https://index.docker.io/v1/": {"auth": encoded}}}))

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        result = load_docker_config_auth("https://index.docker.io/v1/")
        assert result is not None
        assert result.username == "dockeruser"

    def test_cred_helpers_warning(self, tmp_path, monkeypatch, caplog):
        docker_dir = tmp_path / ".docker"
        docker_dir.mkdir()
        config = docker_dir / "config.json"
        config.write_text(json.dumps({"credsStore": "desktop", "auths": {}}))

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        import logging

        with caplog.at_level(logging.WARNING, logger="initrunner.packaging.auth"):
            result = load_docker_config_auth("ghcr.io")

        assert result is None
        assert "credential helpers not supported" in caplog.text

    def test_missing_docker_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        result = load_docker_config_auth("ghcr.io")
        assert result is None

    def test_registry_without_https_prefix(self, tmp_path, monkeypatch):
        docker_dir = tmp_path / ".docker"
        docker_dir.mkdir()
        config = docker_dir / "config.json"

        encoded = base64.b64encode(b"user:pass").decode()
        config.write_text(json.dumps({"auths": {"ghcr.io": {"auth": encoded}}}))

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        result = load_docker_config_auth("ghcr.io")
        assert result is not None
        assert result.username == "user"
