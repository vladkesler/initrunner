"""Tests for the static dry-run plan service."""

from __future__ import annotations

import dataclasses
import json

from initrunner.services.plan import (
    SandboxDecision,
    _probe_sandbox,
    plan_role_from_path,
)

_CUSTOM_TOOL = '''
async def my_fn(x: int) -> str:
    """Do a thing with x."""
    return str(x)
'''


def _write_role(tmp_path, *, with_tool=True, backend="none", memory=False):
    if with_tool:
        (tmp_path / "mytool.py").write_text(_CUSTOM_TOOL)
    tools = "  tools:\n    - type: custom\n      module: mytool\n" if with_tool else ""
    mem = "  memory:\n    max_sessions: 5\n" if memory else ""
    (tmp_path / "role.yaml").write_text(
        "apiVersion: initrunner/v1\n"
        "kind: Agent\n"
        "metadata:\n  name: plan-agent\n"
        "spec:\n"
        '  role: "You help."\n'
        "  model:\n    provider: openai\n    name: gpt-5-mini\n"
        f"{tools}{mem}"
        "  security:\n    sandbox:\n"
        f"      backend: {backend}\n"
    )
    return tmp_path / "role.yaml"


class TestEnumeration:
    def test_custom_tool_resolves_to_function_name(self, tmp_path, monkeypatch):
        monkeypatch.syspath_prepend(str(tmp_path))
        plan = plan_role_from_path(_write_role(tmp_path))
        spec_tools = [t for t in plan.tools if t.source == "spec"]
        assert spec_tools and spec_tools[0].name == "my_fn"
        assert spec_tools[0].tool_type == "custom"

    def test_no_introspect_falls_back_to_type_level(self, tmp_path, monkeypatch):
        monkeypatch.syspath_prepend(str(tmp_path))
        plan = plan_role_from_path(_write_role(tmp_path), introspect=False)
        spec_tools = [t for t in plan.tools if t.source == "spec"]
        assert spec_tools and spec_tools[0].name == "custom"  # type, not function

    def test_json_round_trips(self, tmp_path, monkeypatch):
        monkeypatch.syspath_prepend(str(tmp_path))
        plan = plan_role_from_path(_write_role(tmp_path))
        # Must serialize cleanly for --json, including nested RoleCostEstimate.
        assert json.loads(json.dumps(dataclasses.asdict(plan)))["role_name"] == "plan-agent"


class TestPolicy:
    def test_inactive_without_policy_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("INITRUNNER_POLICY_DIR", raising=False)
        monkeypatch.syspath_prepend(str(tmp_path))
        plan = plan_role_from_path(_write_role(tmp_path))
        assert plan.policy.active is False
        assert plan.policy.note
        assert all(t.policy is None for t in plan.tools)

    def test_active_with_policy_dir_populates_decisions(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INITRUNNER_POLICY_DIR", "examples/policies/agent")
        monkeypatch.syspath_prepend(str(tmp_path))
        plan = plan_role_from_path(_write_role(tmp_path))
        assert plan.policy.active is True
        # Default-deny example policy: tools carry an explicit decision.
        decided = [t for t in plan.tools if t.policy is not None]
        assert decided and all(d.policy is not None for d in decided)
        assert any(d.policy.allowed is False for d in decided)


class TestSandbox:
    def test_none_backend_available(self, tmp_path, monkeypatch):
        monkeypatch.syspath_prepend(str(tmp_path))
        plan = plan_role_from_path(_write_role(tmp_path, backend="none"))
        assert plan.sandbox.available is True
        assert plan.sandbox.requested_backend == "none"

    def test_unavailable_backend_is_caught_not_raised(self, tmp_path, monkeypatch):
        from initrunner.agent.runtime_sandbox import SandboxUnavailableError

        role_path = _write_role(tmp_path, with_tool=False, backend="docker")

        def _boom(*a, **k):
            raise SandboxUnavailableError("docker", "no daemon", "start docker")

        monkeypatch.setattr("initrunner.agent.runtime_sandbox.resolve_backend", _boom)
        plan = plan_role_from_path(role_path)  # must not raise
        assert plan.sandbox.available is False
        assert "docker" in (plan.sandbox.reason or "")

    def test_probe_skipped(self, tmp_path):
        from tests.conftest import make_role

        role = make_role()
        decision = _probe_sandbox(role, tmp_path, probe=True)
        assert isinstance(decision, SandboxDecision)


class TestToolSearchSurfacing:
    def test_surfaced_subset_with_prompt(self, tmp_path, monkeypatch):
        monkeypatch.syspath_prepend(str(tmp_path))
        (tmp_path / "mytool.py").write_text(_CUSTOM_TOOL)
        (tmp_path / "role.yaml").write_text(
            "apiVersion: initrunner/v1\nkind: Agent\n"
            "metadata:\n  name: ts-agent\n"
            'spec:\n  role: "You help."\n'
            "  model:\n    provider: openai\n    name: gpt-5-mini\n"
            "  tools:\n    - type: custom\n      module: mytool\n"
            "  tool_search:\n    enabled: true\n"
        )
        plan = plan_role_from_path(tmp_path / "role.yaml", prompt="do a thing with a number")
        assert plan.tool_search_surfaced is not None
        # Surfaced names are a subset of the listed tool names.
        listed = {t.name for t in plan.tools}
        assert set(plan.tool_search_surfaced).issubset(listed)


def test_triggers_classified(tmp_path):
    (tmp_path / "role.yaml").write_text(
        "apiVersion: initrunner/v1\nkind: Agent\n"
        "metadata:\n  name: trig-agent\n"
        'spec:\n  role: "You help."\n'
        "  model:\n    provider: openai\n    name: gpt-5-mini\n"
        "  triggers:\n"
        '    - type: cron\n      schedule: "0 * * * *"\n      prompt: "tick"\n'
    )
    plan = plan_role_from_path(tmp_path / "role.yaml")
    assert plan.triggers and plan.triggers[0].type == "cron"
    assert plan.triggers[0].predictability == "scheduled"
