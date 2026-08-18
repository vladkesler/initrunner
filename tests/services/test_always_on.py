"""Tests for always-on service lifecycle."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import yaml

from initrunner.agent.schema.service import ProcessIdentity, ServiceStatus
from initrunner.services.always_on import (
    ProcessObservation,
    ServiceError,
    _prompt_from_role,
    check_requires,
    discover_catalog,
    forced_run,
    get_catalog_entry,
    instance_dir,
    list_services,
    load_state,
    materialize_instance_role,
    observe_process,
    parse_sink_specs,
    resolve_every,
    resolve_params,
    runtime_agent_name,
    set_daemon_launcher,
    start_service,
    status,
    stop_service,
    validate_slug,
)


def test_prompt_from_flat_role(tmp_path: Path) -> None:
    role = tmp_path / "role.yaml"
    role.write_text(
        "name: service-probe\n"
        "prompt: monitor things\n"
        "triggers:\n"
        "  - type: cron\n"
        "    schedule: '0 * * * *'\n"
        "    prompt: run the hourly check\n"
        "    autonomous: true\n"
        "autonomy: {}\n"
    )

    assert _prompt_from_role(role) == ("run the hourly check", True)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path / "home"))
    from initrunner.config import get_home_dir

    get_home_dir.cache_clear()
    yield tmp_path / "home"
    get_home_dir.cache_clear()
    set_daemon_launcher(None)


@pytest.fixture
def catalog(tmp_path: Path) -> Path:
    """Minimal fake catalog with one service."""
    root = tmp_path / "catalog" / "probe"
    root.mkdir(parents=True)
    (root / "service.yaml").write_text(
        """
apiVersion: initrunner/v1
kind: Service
metadata:
  name: probe
  version: "0.1.0"
  description: Test service
spec:
  entry:
    kind: Agent
    path: role.yaml
  primary_param: target
  every: hourly
  params:
    target:
      type: string
      required: true
    alert_severity:
      type: enum
      values: [low, medium, high]
      default: medium
  defaults:
    autonomy: false
    sinks:
      - type: file
        path: out.md
        format: text
    guardrails:
      max_tokens_per_run: 1000
    timezone: UTC
  requires:
    env: []
    extras: []
  schedule_prompt: "Check {{ params.target }}"
""",
        encoding="utf-8",
    )
    (root / "role.yaml").write_text(
        """
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: probe
  description: test
spec:
  role: |
    You monitor {{ params.target }}.
  tools:
    - type: datetime
  triggers:
    - type: cron
      schedule: "0 * * * *"
      prompt: "tick"
  guardrails:
    max_tokens_per_run: 1000
""",
        encoding="utf-8",
    )
    return tmp_path / "catalog"


def _fake_launcher_factory(identity_hook=None):
    """Return a launcher that spawns `sleep 60` and records the role path in argv."""

    def launcher(role_path: Path, log_path: Path, cwd: Path, env: dict) -> int:
        # Put role path in cmdline so collect_process_identity can match.
        proc = __import__("subprocess").Popen(
            ["sleep", "60", str(role_path.resolve())],
            stdout=open(log_path, "ab"),
            stderr=__import__("subprocess").STDOUT,
            cwd=str(cwd),
            env=env,
            start_new_session=True,
        )
        if identity_hook:
            identity_hook(proc.pid, role_path)
        return proc.pid

    return launcher


@pytest.fixture
def fake_daemon(monkeypatch: pytest.MonkeyPatch):
    """Use sleep child + patched identity collection for Linux tests."""

    def launcher(role_path: Path, log_path: Path, cwd: Path, env: dict) -> int:
        import sys

        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab") as log_f:
            # Put role path in argv so real identity checks can match; sleep
            # must not treat it as a duration (GNU sleep does).
            proc = __import__("subprocess").Popen(
                [
                    sys.executable,
                    "-c",
                    "import time,sys; time.sleep(120)",
                    str(role_path.resolve()),
                ],
                stdout=log_f,
                stderr=__import__("subprocess").STDOUT,
                cwd=str(cwd),
                env=env,
                start_new_session=True,
            )
        return proc.pid

    set_daemon_launcher(launcher)

    def fake_collect(pid: int, role_path: str) -> ProcessIdentity | None:
        if not Path(f"/proc/{pid}").exists() and os.name == "posix":
            # still try kill 0
            try:
                os.kill(pid, 0)
            except OSError:
                return None
        return ProcessIdentity(
            pid=pid,
            boot_id="test-boot",
            proc_start_ticks=1,
            role_path=str(Path(role_path).resolve()),
            started_at="2026-01-01T00:00:00+00:00",
        )

    def fake_observe(identity: ProcessIdentity | None) -> ProcessObservation:
        if identity is None:
            return ProcessObservation.VERIFIED_DEAD
        from initrunner.services.always_on import _pid_alive

        if _pid_alive(identity.pid):
            return ProcessObservation.VERIFIED_RUNNING
        return ProcessObservation.VERIFIED_DEAD

    monkeypatch.setattr("initrunner.services.always_on.collect_process_identity", fake_collect)
    monkeypatch.setattr("initrunner.services.always_on.observe_process", fake_observe)
    monkeypatch.setattr("initrunner.services.always_on.require_linux_supervision", lambda: None)
    yield
    set_daemon_launcher(None)


def test_validate_slug() -> None:
    assert validate_slug("collector") == "collector"
    with pytest.raises(ServiceError):
        validate_slug("../etc")
    with pytest.raises(ServiceError):
        validate_slug("/tmp/x")
    with pytest.raises(ServiceError):
        validate_slug("foo/bar")
    with pytest.raises(ServiceError):
        validate_slug("UPPER")


def test_instance_dir_containment(home: Path) -> None:
    d = instance_dir("collector")
    assert d.name == "collector"
    assert "services" in d.parts


def test_discover_shipped_collector() -> None:
    entries = discover_catalog()
    slugs = {e.slug for e in entries}
    assert "collector" in slugs
    assert "researcher" not in slugs


def test_discover_extra_catalog(catalog: Path, home: Path) -> None:
    entries = discover_catalog(extra_dirs=[catalog])
    assert any(e.slug == "probe" for e in entries)
    entry = get_catalog_entry("probe", extra_dirs=[catalog])
    assert entry.definition.metadata.version == "0.1.0"
    assert entry.definition.spec.primary_param == "target"


def test_resolve_params_and_every(catalog: Path) -> None:
    entry = get_catalog_entry("probe", extra_dirs=[catalog])
    with pytest.raises(ServiceError, match="Missing required"):
        resolve_params(entry.definition, {})
    resolved = resolve_params(entry.definition, {"target": "acme.com"})
    assert resolved["target"] == "acme.com"
    assert resolved["alert_severity"] == "medium"
    assert resolve_every("daily") == "0 6 * * *"
    assert resolve_every("0 */2 * * *") == "0 */2 * * *"
    with pytest.raises(ServiceError, match="Invalid schedule"):
        resolve_every("not-a-schedule")


def test_parse_sink_specs() -> None:
    sinks = parse_sink_specs(["file:/tmp/a.md", "webhook:https://example.com/h"])
    assert sinks[0] == {"type": "file", "path": "/tmp/a.md", "format": "text"}
    assert sinks[1]["type"] == "webhook"
    with pytest.raises(ServiceError, match="Unknown sink"):
        parse_sink_specs(["slack:#ops"])


def test_materialize_runtime_name_and_sinks(catalog: Path, home: Path, tmp_path: Path) -> None:
    entry = get_catalog_entry("probe", extra_dirs=[catalog])
    dest = tmp_path / "role.1.yaml"
    params = resolve_params(entry.definition, {"target": "acme.com"})
    digest, sinks = materialize_instance_role(
        entry,
        params,
        [{"type": "file", "path": "brief.md", "format": "text"}],
        every="hourly",
        resolved_cron="0 * * * *",
        timezone="UTC",
        dest=dest,
    )
    assert digest
    text = dest.read_text(encoding="utf-8")
    assert "acme.com" in text
    data = yaml.safe_load(text)
    assert data["metadata"]["name"] == "service-probe"
    assert runtime_agent_name("probe") == "service-probe"
    cron = data["spec"]["triggers"][0]
    assert cron["schedule"] == "0 * * * *"
    assert "brief.md" in sinks[0]["path"]
    assert "data" in sinks[0]["path"]


def test_materialize_rejects_dotdot_sink(catalog: Path, home: Path, tmp_path: Path) -> None:
    entry = get_catalog_entry("probe", extra_dirs=[catalog])
    dest = tmp_path / "role.1.yaml"
    params = resolve_params(entry.definition, {"target": "x"})
    with pytest.raises(ServiceError, match="\\.\\."):
        materialize_instance_role(
            entry,
            params,
            [{"type": "file", "path": "../escape.md", "format": "text"}],
            every="daily",
            resolved_cron="0 6 * * *",
            timezone="UTC",
            dest=dest,
        )


def test_start_stop_purge(catalog: Path, home: Path, fake_daemon) -> None:
    result = start_service(
        "probe",
        params={"target": "example.com"},
        extra_dirs=[catalog],
    )
    assert result.state.status == ServiceStatus.RUNNING
    assert result.state.process is not None
    pid = result.state.process.pid
    assert result.state.params["target"] == "example.com"
    assert result.state.every == "hourly"

    # Idempotent start
    again = start_service("probe", extra_dirs=[catalog])
    assert again.idempotent

    # Reconfig while running rejected
    with pytest.raises(ServiceError, match="already running"):
        start_service(
            "probe",
            params={"target": "other.com"},
            extra_dirs=[catalog],
        )

    stop_service("probe")
    st = load_state("probe")
    assert st is not None
    assert st.status == ServiceStatus.STOPPED
    # child should be dead (brief wait for reaping)
    deadline = time.time() + 2.0
    alive = True
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            alive = False
            break
        time.sleep(0.05)
    assert not alive

    # Restart without overrides
    resumed = start_service("probe", extra_dirs=[catalog])
    assert resumed.state.status == ServiceStatus.RUNNING

    stop_service("probe", purge=True)
    assert load_state("probe") is None
    assert not instance_dir("probe").exists()


def test_list_healed_status(catalog: Path, home: Path, fake_daemon) -> None:
    start_service(
        "probe",
        params={"target": "z"},
        extra_dirs=[catalog],
    )
    items = list_services(extra_dirs=[catalog])
    probe = next(i for i in items if i.slug == "probe")
    assert probe.status == ServiceStatus.RUNNING


def test_status_not_started(home: Path) -> None:
    with pytest.raises(ServiceError, match="not started"):
        status("nope")


def test_check_requires_search_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = get_catalog_entry("collector")
    real_import = __import__

    def fake_import(name: str, *args: object, **kwargs: object):
        if name == "ddgs":
            raise ImportError("nope")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("builtins.__import__", fake_import)
    missing = check_requires(entry.definition)
    assert any("search" in m for m in missing)


def test_shipped_collector_role_validates(home: Path, tmp_path: Path) -> None:
    from initrunner.agent.loader import load_role

    entry = get_catalog_entry("collector")
    dest = tmp_path / "role.1.yaml"
    params = resolve_params(entry.definition, {"target": "example.com", "alert_severity": "high"})
    materialize_instance_role(
        entry,
        params,
        None,
        every="daily",
        resolved_cron="0 6 * * *",
        timezone="UTC",
        dest=dest,
    )
    role = load_role(dest)
    assert role.metadata.name == "service-collector"
    assert "example.com" in role.spec.role
    assert role.spec.triggers


def test_observe_dead_when_none() -> None:
    assert observe_process(None) is ProcessObservation.VERIFIED_DEAD


def test_forced_run_stopped(
    catalog: Path, home: Path, fake_daemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    start_service("probe", params={"target": "t"}, extra_dirs=[catalog])
    stop_service("probe")

    def fake_run(cmd, check=False):
        class R:
            returncode = 0

        return R()

    monkeypatch.setattr("initrunner.services.always_on.subprocess.run", fake_run)
    result = forced_run("probe", extra_dirs=[catalog])
    assert result.exit_code == 0
    assert result.was_running is False
    st = load_state("probe")
    assert st is not None
    assert st.status == ServiceStatus.STOPPED


def test_forced_run_running_restarts(
    catalog: Path, home: Path, fake_daemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    start_service("probe", params={"target": "t"}, extra_dirs=[catalog])

    def fake_run(cmd, check=False):
        class R:
            returncode = 0

        return R()

    monkeypatch.setattr("initrunner.services.always_on.subprocess.run", fake_run)
    result = forced_run("probe", extra_dirs=[catalog])
    assert result.exit_code == 0
    assert result.was_running is True
    st = load_state("probe")
    assert st is not None
    assert st.status == ServiceStatus.RUNNING
    stop_service("probe", purge=True)


def test_purge_refuses_bad_slug(home: Path) -> None:
    with pytest.raises(ServiceError):
        stop_service("../x", purge=True)
