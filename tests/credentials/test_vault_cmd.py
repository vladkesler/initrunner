"""CLI-level tests for ``initrunner vault``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from initrunner.cli.vault_cmd import app


def _runner() -> CliRunner:
    return CliRunner()


def _init(pw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INITRUNNER_VAULT_PASSPHRASE", pw)
    result = _runner().invoke(app, ["init", "--no-prompt"])
    assert result.exit_code == 0, result.stdout


def test_init_then_set_get(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init("pw", monkeypatch)
    r = _runner().invoke(app, ["set", "OPENAI_API_KEY", "sk-1", "--no-prompt"])
    assert r.exit_code == 0, r.stdout

    r = _runner().invoke(app, ["get", "OPENAI_API_KEY", "--no-prompt"])
    assert r.exit_code == 0
    assert r.stdout.strip() == "sk-1"


def test_init_refuses_second_time(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init("pw", monkeypatch)
    r = _runner().invoke(app, ["init", "--no-prompt"])
    assert r.exit_code == 1
    assert "already exists" in (r.stdout + (r.stderr if r.stderr_bytes else ""))


def test_list_shows_keys_not_values(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init("pw", monkeypatch)
    _runner().invoke(app, ["set", "A", "1", "--no-prompt"])
    _runner().invoke(app, ["set", "B", "2", "--no-prompt"])

    r = _runner().invoke(app, ["list"])
    assert r.exit_code == 0
    assert "A" in r.stdout and "B" in r.stdout
    assert "1" not in r.stdout and "2" not in r.stdout


def test_rm(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init("pw", monkeypatch)
    _runner().invoke(app, ["set", "K", "v", "--no-prompt"])
    r = _runner().invoke(app, ["rm", "K", "--no-prompt"])
    assert r.exit_code == 0
    r = _runner().invoke(app, ["get", "K", "--no-prompt"])
    assert r.exit_code == 1


def test_export_json_to_stdout(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init("pw", monkeypatch)
    _runner().invoke(app, ["set", "A", "1", "--no-prompt"])
    _runner().invoke(app, ["set", "B", "2", "--no-prompt"])

    r = _runner().invoke(app, ["export", "--json", "--no-prompt"])
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)
    assert data == {"A": "1", "B": "2"}


def test_export_env_format(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init("pw", monkeypatch)
    _runner().invoke(app, ["set", "A", "hello", "--no-prompt"])

    r = _runner().invoke(app, ["export", "--env", "--no-prompt"])
    assert r.exit_code == 0
    assert 'A="hello"' in r.stdout


def test_export_requires_exactly_one_format(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init("pw", monkeypatch)
    r = _runner().invoke(app, ["export", "--no-prompt"])
    assert r.exit_code == 2

    r = _runner().invoke(app, ["export", "--env", "--json", "--no-prompt"])
    assert r.exit_code == 2


def test_import_json_file(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init("pw", monkeypatch)
    src = isolated_home / "import.json"
    src.write_text(json.dumps({"A": "1", "B": "2"}))

    r = _runner().invoke(app, ["import", str(src), "--no-prompt"])
    assert r.exit_code == 0, r.stdout

    r = _runner().invoke(app, ["get", "A", "--no-prompt"])
    assert r.stdout.strip() == "1"


def test_import_dotenv_file(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init("pw", monkeypatch)
    src = isolated_home / "import.env"
    src.write_text("FOO=bar\nBAZ=qux\n")

    r = _runner().invoke(app, ["import", str(src), "--no-prompt"])
    assert r.exit_code == 0, r.stdout

    r = _runner().invoke(app, ["get", "FOO", "--no-prompt"])
    assert r.stdout.strip() == "bar"


def test_verify_rejects_wrong_passphrase(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init("right", monkeypatch)
    monkeypatch.setenv("INITRUNNER_VAULT_PASSPHRASE", "wrong")
    r = _runner().invoke(app, ["verify", "--no-prompt"])
    assert r.exit_code == 1


def test_status_before_init(isolated_home: Path) -> None:
    r = _runner().invoke(app, ["status"])
    assert r.exit_code == 0
    assert "uninitialized" in r.stdout


def test_status_after_init(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init("pw", monkeypatch)
    _runner().invoke(app, ["set", "K", "v", "--no-prompt"])
    r = _runner().invoke(app, ["status"])
    assert r.exit_code == 0
    assert "entries:      1" in r.stdout


def test_no_prompt_without_passphrase_exits_cleanly(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init("pw", monkeypatch)
    monkeypatch.delenv("INITRUNNER_VAULT_PASSPHRASE", raising=False)
    from initrunner.credentials import keyring_cache

    monkeypatch.setattr(keyring_cache, "load_passphrase", lambda: None)

    r = _runner().invoke(app, ["get", "K", "--no-prompt"])
    assert r.exit_code == 2
