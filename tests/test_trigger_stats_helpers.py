"""Tests for trigger stats helper functions in services.operations."""

from initrunner.services.operations import next_cron_check, next_heartbeat_check


class TestNextCronCheck:
    def test_returns_iso_string(self):
        result = next_cron_check("0 9 * * *")
        assert result is not None
        assert "T" in result  # ISO format

    def test_invalid_schedule_returns_none(self):
        assert next_cron_check("not a cron") is None

    def test_next_is_in_future(self):
        from datetime import UTC, datetime

        result = next_cron_check("* * * * *")  # every minute
        assert result is not None
        next_time = datetime.fromisoformat(result)
        assert next_time > datetime.now(UTC)


class TestNextHeartbeatCheck:
    def test_returns_none_when_no_last_fire(self):
        assert next_heartbeat_check(None, 3600) is None

    def test_computes_from_last_fire(self):
        result = next_heartbeat_check("2025-06-15T09:00:00+00:00", 3600)
        assert result is not None
        assert "2025-06-15T10:00:00" in result

    def test_handles_naive_timestamp(self):
        result = next_heartbeat_check("2025-06-15T09:00:00", 7200)
        assert result is not None
        assert "2025-06-15T11:00:00" in result

    def test_invalid_timestamp_returns_none(self):
        assert next_heartbeat_check("not-a-date", 3600) is None
