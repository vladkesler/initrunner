"""The dashboard's doctor checks include the optional Jev row."""

from __future__ import annotations

from unittest.mock import patch

from initrunner.dashboard.routers.system import _run_doctor_checks


def _checks() -> dict:
    with (
        patch("initrunner.agent.loader._load_dotenv"),
        patch("initrunner.services.providers.is_ollama_running", return_value=False),
        patch("initrunner.agent.docker_sandbox.check_docker_available", return_value=False),
    ):
        return {c.name: c for c in _run_doctor_checks()}


def test_jev_not_configured():
    jev = _checks()["jev"]  # the autouse fixture leaves no key
    assert jev.status in ("fail", "warn")


def test_jev_ready(monkeypatch):
    import initrunner.jev as jev_mod

    monkeypatch.setattr(jev_mod, "api_key", lambda: "ts_test")
    monkeypatch.setattr("initrunner._compat.is_extra_installed", lambda extra: True)
    jev = _checks()["jev"]
    assert jev.status == "ok"
    assert jev.message.startswith("Ready")
