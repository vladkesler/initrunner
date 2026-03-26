"""Tests for GET /api/agents/{id}/trigger-stats."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from initrunner.agent.schema.triggers import CronTriggerConfig, HeartbeatTriggerConfig
from initrunner.dashboard.deps import _role_id, get_role_cache
from initrunner.services.operations import TriggerStat
from tests.test_dashboard.conftest import MockRoleCache


def _make_trigger_role(path: str, name: str, triggers):
    """Create a mock DiscoveredRole with trigger configs."""
    from initrunner.agent.schema.base import ModelConfig
    from initrunner.agent.schema.guardrails import Guardrails
    from initrunner.agent.schema.output import OutputConfig

    dr = MagicMock()
    dr.path = Path(path)
    dr.error = None
    dr.role.metadata.name = name
    dr.role.metadata.description = f"Description of {name}"
    dr.role.metadata.tags = ["test"]
    dr.role.metadata.author = ""
    dr.role.metadata.team = ""
    dr.role.metadata.version = ""
    dr.role.spec.model = ModelConfig(provider="openai", name="gpt-4o")
    dr.role.spec.output = OutputConfig()
    dr.role.spec.guardrails = Guardrails()
    dr.role.spec.memory = None
    dr.role.spec.ingest = None
    dr.role.spec.reasoning = None
    dr.role.spec.autonomy = None
    dr.role.spec.tools = []
    dr.role.spec.triggers = triggers
    dr.role.spec.sinks = []
    dr.role.spec.capabilities = []
    dr.role.spec.skills = []
    dr.role.spec.features = []
    return dr


class TestTriggerStatsEndpoint:
    def test_agent_not_found(self, client):
        resp = client.get("/api/agents/doesnotexist/trigger-stats")
        assert resp.status_code == 404

    def test_agent_no_triggers(self, client):
        """Agent with no triggers returns empty list."""
        resp = client.get("/api/agents/doesnotexist/trigger-stats")
        assert resp.status_code == 404

    def test_returns_stats_for_triggers(self, client):
        triggers = [
            CronTriggerConfig(schedule="0 9 * * *", prompt="daily report"),
        ]
        role = _make_trigger_role("/tmp/roles/cron-agent.yaml", "cron-agent", triggers)
        cache = MockRoleCache([role])
        client.app.dependency_overrides[get_role_cache] = lambda: cache
        agent_id = _role_id(Path("/tmp/roles/cron-agent.yaml"))

        mock_stats = [
            TriggerStat(
                trigger_type="cron",
                fire_count=5,
                success_count=4,
                fail_count=1,
                last_fire_time="2025-06-15T09:00:00Z",
                avg_duration_ms=1200,
                last_error="timeout",
            ),
        ]

        with patch(
            "initrunner.services.operations.trigger_stats_sync",
            return_value=mock_stats,
        ):
            resp = client.get(f"/api/agents/{agent_id}/trigger-stats")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        stat = data[0]
        assert stat["trigger_type"] == "cron"
        assert stat["summary"] == "cron: 0 9 * * *"
        assert stat["fire_count"] == 5
        assert stat["success_count"] == 4
        assert stat["fail_count"] == 1
        assert stat["last_fire_time"] == "2025-06-15T09:00:00Z"
        assert stat["avg_duration_ms"] == 1200
        assert stat["last_error"] == "timeout"
        assert stat["next_check_time"] is not None  # cron computes next check

    def test_trigger_with_no_audit_records(self, client):
        triggers = [
            CronTriggerConfig(schedule="0 9 * * *", prompt="daily report"),
        ]
        role = _make_trigger_role("/tmp/roles/new-agent.yaml", "new-agent", triggers)
        cache = MockRoleCache([role])
        client.app.dependency_overrides[get_role_cache] = lambda: cache
        agent_id = _role_id(Path("/tmp/roles/new-agent.yaml"))

        with patch(
            "initrunner.services.operations.trigger_stats_sync",
            return_value=[],
        ):
            resp = client.get(f"/api/agents/{agent_id}/trigger-stats")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        stat = data[0]
        assert stat["fire_count"] == 0
        assert stat["last_fire_time"] is None
        assert stat["next_check_time"] is not None  # cron still computes next

    def test_heartbeat_next_check(self, client):
        triggers = [
            HeartbeatTriggerConfig(file="/tmp/checklist.md", interval_seconds=3600),
        ]
        role = _make_trigger_role("/tmp/roles/hb-agent.yaml", "hb-agent", triggers)
        cache = MockRoleCache([role])
        client.app.dependency_overrides[get_role_cache] = lambda: cache
        agent_id = _role_id(Path("/tmp/roles/hb-agent.yaml"))

        mock_stats = [
            TriggerStat(
                trigger_type="heartbeat",
                fire_count=1,
                success_count=1,
                fail_count=0,
                last_fire_time="2025-06-15T09:00:00+00:00",
                avg_duration_ms=500,
                last_error=None,
            ),
        ]

        with patch(
            "initrunner.services.operations.trigger_stats_sync",
            return_value=mock_stats,
        ):
            resp = client.get(f"/api/agents/{agent_id}/trigger-stats")

        data = resp.json()
        assert len(data) == 1
        assert data[0]["next_check_time"] is not None
        # next check = last fire + interval = 2025-06-15T10:00:00+00:00
        assert "2025-06-15T10:00:00" in data[0]["next_check_time"]

    def test_heartbeat_no_last_fire(self, client):
        """Heartbeat with no prior fires has no next_check_time."""
        triggers = [
            HeartbeatTriggerConfig(file="/tmp/checklist.md", interval_seconds=3600),
        ]
        role = _make_trigger_role("/tmp/roles/hb2-agent.yaml", "hb2-agent", triggers)
        cache = MockRoleCache([role])
        client.app.dependency_overrides[get_role_cache] = lambda: cache
        agent_id = _role_id(Path("/tmp/roles/hb2-agent.yaml"))

        with patch(
            "initrunner.services.operations.trigger_stats_sync",
            return_value=[],
        ):
            resp = client.get(f"/api/agents/{agent_id}/trigger-stats")

        data = resp.json()
        assert len(data) == 1
        assert data[0]["next_check_time"] is None
