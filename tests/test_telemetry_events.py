"""Event property construction: allowlist, scrubbing, bucketing, normalization."""

from __future__ import annotations

import pytest

from initrunner.telemetry import _events


def test_only_allowlisted_keys_survive():
    props = _events.command_properties(
        command="run", status="ok", exit_code=0, error_kind=None, duration_ms=10, is_tty=True
    )
    assert set(props).issubset(_events._ALLOWED_PROPERTY_KEYS)


def test_anonymous_control_properties_present():
    props = _events.command_properties(
        command="run", status="ok", exit_code=0, error_kind=None, duration_ms=10, is_tty=True
    )
    assert props["$process_person_profile"] is False
    assert props["$geoip_disable"] is True


def test_first_run_properties_allowlisted():
    props = _events.first_run_properties()
    assert set(props).issubset(_events._ALLOWED_PROPERTY_KEYS)
    assert "install_method" in props


@pytest.mark.parametrize(
    "ms,bucket",
    [
        (0, "<1s"),
        (999, "<1s"),
        (1000, "1-5s"),
        (4999, "1-5s"),
        (5000, "5-30s"),
        (29999, "5-30s"),
        (30000, "30s+"),
        (None, "unknown"),
    ],
)
def test_duration_buckets(ms, bucket):
    assert _events.duration_bucket(ms) == bucket


def test_unknown_command_maps_to_other():
    assert _events.normalize_command("definitely-not-a-command") == "other"
    assert _events.normalize_command("run") == "run"
    assert _events.normalize_command(None) == "other"


def test_error_kind_allowlist():
    assert _events.normalize_error_kind("FileNotFoundError") == "FileNotFoundError"
    assert _events.normalize_error_kind("SomeThirdPartyLibError") == "OtherError"
    assert _events.normalize_error_kind(None) is None


def test_error_kind_omitted_when_none():
    props = _events.command_properties(
        command="run", status="ok", exit_code=0, error_kind=None, duration_ms=10, is_tty=False
    )
    assert "error_kind" not in props


def test_exit_code_omitted_when_none():
    props = _events.command_properties(
        command="run", status="ok", exit_code=None, error_kind=None, duration_ms=10, is_tty=False
    )
    assert "exit_code" not in props


def test_string_values_are_scrubbed():
    # A secret-shaped string in an allowlisted string field must be redacted by
    # the defense-in-depth scrub pass.
    secret = "sk-ant-" + "A" * 40
    props = _events.command_properties(
        command="run", status=secret, exit_code=0, error_kind=None, duration_ms=10, is_tty=False
    )
    status_value = str(props["status"])
    assert "sk-ant-" not in status_value
    assert "[REDACTED]" in status_value
