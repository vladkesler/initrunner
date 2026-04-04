"""Tests for flow schema and loader."""

import textwrap

import pytest
from pydantic import ValidationError

from initrunner.flow.loader import FlowLoadError, load_flow
from initrunner.flow.schema import (
    DelegateSinkConfig,
    FlowAgentConfig,
    FlowDefinition,
    FlowSpec,
    HealthCheckConfig,
    RestartPolicy,
    SharedMemoryConfig,
)


def _minimal_flow_data() -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Flow",
        "metadata": {"name": "test-flow"},
        "spec": {
            "agents": {
                "agent-a": {"role": "roles/a.yaml"},
                "agent-b": {"role": "roles/b.yaml"},
            }
        },
    }


def _flow_with_delegate() -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Flow",
        "metadata": {"name": "delegating"},
        "spec": {
            "agents": {
                "producer": {
                    "role": "roles/producer.yaml",
                    "sink": {
                        "type": "delegate",
                        "target": "consumer",
                    },
                },
                "consumer": {"role": "roles/consumer.yaml"},
            }
        },
    }


class TestDelegateSinkConfig:
    def test_defaults(self):
        c = DelegateSinkConfig(target="downstream")
        assert c.type == "delegate"
        assert c.target == "downstream"
        assert c.keep_existing_sinks is False
        assert c.queue_size == 100
        assert c.timeout_seconds == 60

    def test_list_target(self):
        c = DelegateSinkConfig(target=["a", "b"])
        assert c.target == ["a", "b"]

    def test_summary_single(self):
        c = DelegateSinkConfig(target="downstream")
        assert c.summary() == "delegate: downstream"

    def test_summary_multi(self):
        c = DelegateSinkConfig(target=["x", "y"])
        assert c.summary() == "delegate: x, y"

    def test_custom_queue_size(self):
        c = DelegateSinkConfig(target="t", queue_size=50, timeout_seconds=30)
        assert c.queue_size == 50
        assert c.timeout_seconds == 30


class TestHealthCheckConfig:
    def test_defaults(self):
        h = HealthCheckConfig()
        assert h.interval_seconds == 30
        assert h.timeout_seconds == 10
        assert h.retries == 3


class TestRestartPolicy:
    def test_defaults(self):
        r = RestartPolicy()
        assert r.condition == "none"
        assert r.max_retries == 3
        assert r.delay_seconds == 5

    def test_on_failure(self):
        r = RestartPolicy(condition="on-failure", max_retries=5)
        assert r.condition == "on-failure"
        assert r.max_retries == 5

    def test_always(self):
        r = RestartPolicy(condition="always")
        assert r.condition == "always"


class TestSharedMemoryConfig:
    def test_defaults(self):
        s = SharedMemoryConfig()
        assert s.enabled is False
        assert s.store_path is None
        assert s.max_memories == 1000

    def test_enabled(self):
        s = SharedMemoryConfig(enabled=True, store_path="/tmp/shared.db")
        assert s.enabled is True
        assert s.store_path == "/tmp/shared.db"

    def test_custom_max_memories(self):
        s = SharedMemoryConfig(enabled=True, store_path="/tmp/s.db", max_memories=500)
        assert s.max_memories == 500

    def test_enabled_in_flow_spec_valid(self):
        """shared_memory.enabled: true no longer raises validation error."""
        spec = FlowSpec(
            agents={
                "a": FlowAgentConfig(role="a.yaml"),
            },
            shared_memory=SharedMemoryConfig(enabled=True, store_path="/tmp/shared.db"),
        )
        assert spec.shared_memory.enabled is True


class TestFlowAgentConfig:
    def test_minimal(self):
        c = FlowAgentConfig(role="role.yaml")
        assert c.role == "role.yaml"
        assert c.trigger is None
        assert c.sink is None
        assert c.needs == []
        assert c.environment == {}

    def test_with_delegate_sink(self):
        c = FlowAgentConfig(
            role="role.yaml",
            sink=DelegateSinkConfig(target="other"),
        )
        assert c.sink is not None
        assert c.sink.target == "other"

    def test_with_needs(self):
        c = FlowAgentConfig(role="role.yaml", needs=["a", "b"])
        assert c.needs == ["a", "b"]

    def test_with_environment(self):
        c = FlowAgentConfig(role="role.yaml", environment={"FOO": "bar"})
        assert c.environment == {"FOO": "bar"}


class TestFlowSpec:
    def test_valid_minimal(self):
        spec = FlowSpec(
            agents={
                "a": FlowAgentConfig(role="a.yaml"),
                "b": FlowAgentConfig(role="b.yaml"),
            }
        )
        assert len(spec.agents) == 2

    def test_valid_with_delegate(self):
        spec = FlowSpec(
            agents={
                "producer": FlowAgentConfig(
                    role="p.yaml",
                    sink=DelegateSinkConfig(target="consumer"),
                ),
                "consumer": FlowAgentConfig(role="c.yaml"),
            }
        )
        assert spec.agents["producer"].sink is not None

    def test_valid_with_needs(self):
        spec = FlowSpec(
            agents={
                "a": FlowAgentConfig(role="a.yaml"),
                "b": FlowAgentConfig(role="b.yaml", needs=["a"]),
            }
        )
        assert spec.agents["b"].needs == ["a"]

    def test_empty_agents_rejected(self):
        with pytest.raises(ValidationError, match="at least 1"):
            FlowSpec(agents={})

    def test_unknown_needs_rejected(self):
        with pytest.raises(ValidationError, match="unknown agent"):
            FlowSpec(
                agents={
                    "a": FlowAgentConfig(role="a.yaml", needs=["nope"]),
                }
            )

    def test_self_dependency_rejected(self):
        with pytest.raises(ValidationError, match="cannot need itself"):
            FlowSpec(
                agents={
                    "a": FlowAgentConfig(role="a.yaml", needs=["a"]),
                }
            )

    def test_unknown_delegate_target_rejected(self):
        with pytest.raises(ValidationError, match="unknown agent"):
            FlowSpec(
                agents={
                    "a": FlowAgentConfig(
                        role="a.yaml",
                        sink=DelegateSinkConfig(target="nope"),
                    ),
                }
            )

    def test_self_delegate_rejected(self):
        with pytest.raises(ValidationError, match="cannot delegate to itself"):
            FlowSpec(
                agents={
                    "a": FlowAgentConfig(
                        role="a.yaml",
                        sink=DelegateSinkConfig(target="a"),
                    ),
                }
            )

    def test_dependency_cycle_rejected(self):
        with pytest.raises(ValidationError, match="dependency cycle"):
            FlowSpec(
                agents={
                    "a": FlowAgentConfig(role="a.yaml", needs=["b"]),
                    "b": FlowAgentConfig(role="b.yaml", needs=["a"]),
                }
            )

    def test_delegate_cycle_rejected(self):
        with pytest.raises(ValidationError, match="delegate cycle"):
            FlowSpec(
                agents={
                    "a": FlowAgentConfig(
                        role="a.yaml",
                        sink=DelegateSinkConfig(target="b"),
                    ),
                    "b": FlowAgentConfig(
                        role="b.yaml",
                        sink=DelegateSinkConfig(target="a"),
                    ),
                }
            )

    def test_three_node_delegate_cycle_rejected(self):
        with pytest.raises(ValidationError, match="delegate cycle"):
            FlowSpec(
                agents={
                    "a": FlowAgentConfig(
                        role="a.yaml",
                        sink=DelegateSinkConfig(target="b"),
                    ),
                    "b": FlowAgentConfig(
                        role="b.yaml",
                        sink=DelegateSinkConfig(target="c"),
                    ),
                    "c": FlowAgentConfig(
                        role="c.yaml",
                        sink=DelegateSinkConfig(target="a"),
                    ),
                }
            )

    def test_multi_target_delegate_valid(self):
        spec = FlowSpec(
            agents={
                "router": FlowAgentConfig(
                    role="r.yaml",
                    sink=DelegateSinkConfig(target=["a", "b"]),
                ),
                "a": FlowAgentConfig(role="a.yaml"),
                "b": FlowAgentConfig(role="b.yaml"),
            }
        )
        assert spec.agents["router"].sink is not None
        assert spec.agents["router"].sink.target == ["a", "b"]

    def test_linear_chain_valid(self):
        spec = FlowSpec(
            agents={
                "first": FlowAgentConfig(
                    role="f.yaml",
                    sink=DelegateSinkConfig(target="second"),
                ),
                "second": FlowAgentConfig(
                    role="s.yaml",
                    sink=DelegateSinkConfig(target="third"),
                ),
                "third": FlowAgentConfig(role="t.yaml"),
            }
        )
        assert len(spec.agents) == 3


class TestFlowDefinition:
    def test_valid(self):
        data = _minimal_flow_data()
        defn = FlowDefinition.model_validate(data)
        assert defn.kind == "Flow"
        assert defn.metadata.name == "test-flow"
        assert len(defn.spec.agents) == 2

    def test_with_delegate(self):
        data = _flow_with_delegate()
        defn = FlowDefinition.model_validate(data)
        assert defn.spec.agents["producer"].sink is not None

    def test_wrong_kind_rejected(self):
        data = _minimal_flow_data()
        data["kind"] = "Pipeline"
        with pytest.raises(ValidationError, match="kind"):
            FlowDefinition.model_validate(data)


class TestFlowLoader:
    def test_load_valid(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Flow
            metadata:
              name: test-flow
            spec:
              agents:
                svc-a:
                  role: roles/a.yaml
                svc-b:
                  role: roles/b.yaml
                  sink:
                    type: delegate
                    target: svc-a
        """)
        f = tmp_path / "flow.yaml"
        f.write_text(yaml_content)
        defn = load_flow(f)
        assert defn.metadata.name == "test-flow"
        assert len(defn.spec.agents) == 2

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(FlowLoadError, match="Cannot read"):
            load_flow(tmp_path / "nope.yaml")

    def test_load_invalid_yaml(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text(": invalid: yaml: [")
        with pytest.raises(FlowLoadError, match="Invalid YAML"):
            load_flow(f)

    def test_load_not_mapping(self, tmp_path):
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        with pytest.raises(FlowLoadError, match="Expected a YAML mapping"):
            load_flow(f)

    def test_load_validation_error(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("apiVersion: initrunner/v1\nkind: Flow\n")
        with pytest.raises(FlowLoadError, match="Validation failed"):
            load_flow(f)


class TestComposeHardBreak:
    """Verify that old compose-format YAML is rejected with migration guidance."""

    def test_kind_compose_raises(self):
        from initrunner.deprecations import validate_flow_dict

        data = {
            "apiVersion": "initrunner/v1",
            "kind": "Compose",
            "metadata": {"name": "old"},
            "spec": {
                "agents": {
                    "a": {"role": "a.yaml"},
                }
            },
        }
        with pytest.raises(ValueError, match="kind: Compose has been renamed to kind: Flow"):
            validate_flow_dict(data)

    def test_services_key_raises(self):
        from initrunner.deprecations import validate_flow_dict

        data = {
            "apiVersion": "initrunner/v1",
            "kind": "Flow",
            "metadata": {"name": "old"},
            "spec": {
                "services": {
                    "a": {"role": "a.yaml"},
                }
            },
        }
        with pytest.raises(ValueError, match=r"spec\.services -> spec\.agents"):
            validate_flow_dict(data)

    def test_depends_on_key_raises(self):
        from initrunner.deprecations import validate_flow_dict

        data = {
            "apiVersion": "initrunner/v1",
            "kind": "Compose",
            "metadata": {"name": "old"},
            "spec": {
                "services": {
                    "a": {"role": "a.yaml", "depends_on": ["b"]},
                    "b": {"role": "b.yaml"},
                }
            },
        }
        with pytest.raises(ValueError, match="depends_on -> needs"):
            validate_flow_dict(data)
