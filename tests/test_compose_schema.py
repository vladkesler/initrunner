"""Tests for compose schema and loader."""

import textwrap

import pytest
from pydantic import ValidationError

from initrunner.compose.loader import ComposeLoadError, load_compose
from initrunner.compose.schema import (
    ComposeDefinition,
    ComposeServiceConfig,
    ComposeSpec,
    DelegateSinkConfig,
    HealthCheckConfig,
    RestartPolicy,
    SharedMemoryConfig,
)


def _minimal_compose_data() -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Compose",
        "metadata": {"name": "test-compose"},
        "spec": {
            "services": {
                "agent-a": {"role": "roles/a.yaml"},
                "agent-b": {"role": "roles/b.yaml"},
            }
        },
    }


def _compose_with_delegate() -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Compose",
        "metadata": {"name": "delegating"},
        "spec": {
            "services": {
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

    def test_enabled_in_compose_spec_valid(self):
        """shared_memory.enabled: true no longer raises validation error."""
        spec = ComposeSpec(
            services={
                "a": ComposeServiceConfig(role="a.yaml"),
            },
            shared_memory=SharedMemoryConfig(enabled=True, store_path="/tmp/shared.db"),
        )
        assert spec.shared_memory.enabled is True


class TestComposeServiceConfig:
    def test_minimal(self):
        c = ComposeServiceConfig(role="role.yaml")
        assert c.role == "role.yaml"
        assert c.trigger is None
        assert c.sink is None
        assert c.depends_on == []
        assert c.environment == {}

    def test_with_delegate_sink(self):
        c = ComposeServiceConfig(
            role="role.yaml",
            sink=DelegateSinkConfig(target="other"),
        )
        assert c.sink is not None
        assert c.sink.target == "other"

    def test_with_depends_on(self):
        c = ComposeServiceConfig(role="role.yaml", depends_on=["a", "b"])
        assert c.depends_on == ["a", "b"]

    def test_with_environment(self):
        c = ComposeServiceConfig(role="role.yaml", environment={"FOO": "bar"})
        assert c.environment == {"FOO": "bar"}


class TestComposeSpec:
    def test_valid_minimal(self):
        spec = ComposeSpec(
            services={
                "a": ComposeServiceConfig(role="a.yaml"),
                "b": ComposeServiceConfig(role="b.yaml"),
            }
        )
        assert len(spec.services) == 2

    def test_valid_with_delegate(self):
        spec = ComposeSpec(
            services={
                "producer": ComposeServiceConfig(
                    role="p.yaml",
                    sink=DelegateSinkConfig(target="consumer"),
                ),
                "consumer": ComposeServiceConfig(role="c.yaml"),
            }
        )
        assert spec.services["producer"].sink is not None

    def test_valid_with_depends_on(self):
        spec = ComposeSpec(
            services={
                "a": ComposeServiceConfig(role="a.yaml"),
                "b": ComposeServiceConfig(role="b.yaml", depends_on=["a"]),
            }
        )
        assert spec.services["b"].depends_on == ["a"]

    def test_empty_services_rejected(self):
        with pytest.raises(ValidationError, match="at least 1"):
            ComposeSpec(services={})

    def test_unknown_depends_on_rejected(self):
        with pytest.raises(ValidationError, match="unknown service"):
            ComposeSpec(
                services={
                    "a": ComposeServiceConfig(role="a.yaml", depends_on=["nope"]),
                }
            )

    def test_self_dependency_rejected(self):
        with pytest.raises(ValidationError, match="cannot depend on itself"):
            ComposeSpec(
                services={
                    "a": ComposeServiceConfig(role="a.yaml", depends_on=["a"]),
                }
            )

    def test_unknown_delegate_target_rejected(self):
        with pytest.raises(ValidationError, match="unknown service"):
            ComposeSpec(
                services={
                    "a": ComposeServiceConfig(
                        role="a.yaml",
                        sink=DelegateSinkConfig(target="nope"),
                    ),
                }
            )

    def test_self_delegate_rejected(self):
        with pytest.raises(ValidationError, match="cannot delegate to itself"):
            ComposeSpec(
                services={
                    "a": ComposeServiceConfig(
                        role="a.yaml",
                        sink=DelegateSinkConfig(target="a"),
                    ),
                }
            )

    def test_dependency_cycle_rejected(self):
        with pytest.raises(ValidationError, match="dependency cycle"):
            ComposeSpec(
                services={
                    "a": ComposeServiceConfig(role="a.yaml", depends_on=["b"]),
                    "b": ComposeServiceConfig(role="b.yaml", depends_on=["a"]),
                }
            )

    def test_delegate_cycle_rejected(self):
        with pytest.raises(ValidationError, match="delegate cycle"):
            ComposeSpec(
                services={
                    "a": ComposeServiceConfig(
                        role="a.yaml",
                        sink=DelegateSinkConfig(target="b"),
                    ),
                    "b": ComposeServiceConfig(
                        role="b.yaml",
                        sink=DelegateSinkConfig(target="a"),
                    ),
                }
            )

    def test_three_node_delegate_cycle_rejected(self):
        with pytest.raises(ValidationError, match="delegate cycle"):
            ComposeSpec(
                services={
                    "a": ComposeServiceConfig(
                        role="a.yaml",
                        sink=DelegateSinkConfig(target="b"),
                    ),
                    "b": ComposeServiceConfig(
                        role="b.yaml",
                        sink=DelegateSinkConfig(target="c"),
                    ),
                    "c": ComposeServiceConfig(
                        role="c.yaml",
                        sink=DelegateSinkConfig(target="a"),
                    ),
                }
            )

    def test_multi_target_delegate_valid(self):
        spec = ComposeSpec(
            services={
                "router": ComposeServiceConfig(
                    role="r.yaml",
                    sink=DelegateSinkConfig(target=["a", "b"]),
                ),
                "a": ComposeServiceConfig(role="a.yaml"),
                "b": ComposeServiceConfig(role="b.yaml"),
            }
        )
        assert spec.services["router"].sink is not None
        assert spec.services["router"].sink.target == ["a", "b"]

    def test_linear_chain_valid(self):
        spec = ComposeSpec(
            services={
                "first": ComposeServiceConfig(
                    role="f.yaml",
                    sink=DelegateSinkConfig(target="second"),
                ),
                "second": ComposeServiceConfig(
                    role="s.yaml",
                    sink=DelegateSinkConfig(target="third"),
                ),
                "third": ComposeServiceConfig(role="t.yaml"),
            }
        )
        assert len(spec.services) == 3


class TestComposeDefinition:
    def test_valid(self):
        data = _minimal_compose_data()
        defn = ComposeDefinition.model_validate(data)
        assert defn.kind == "Compose"
        assert defn.metadata.name == "test-compose"
        assert len(defn.spec.services) == 2

    def test_with_delegate(self):
        data = _compose_with_delegate()
        defn = ComposeDefinition.model_validate(data)
        assert defn.spec.services["producer"].sink is not None

    def test_wrong_kind_rejected(self):
        data = _minimal_compose_data()
        data["kind"] = "Pipeline"
        with pytest.raises(ValidationError, match="kind"):
            ComposeDefinition.model_validate(data)


class TestComposeLoader:
    def test_load_valid(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Compose
            metadata:
              name: test-compose
            spec:
              services:
                svc-a:
                  role: roles/a.yaml
                svc-b:
                  role: roles/b.yaml
                  sink:
                    type: delegate
                    target: svc-a
        """)
        f = tmp_path / "compose.yaml"
        f.write_text(yaml_content)
        defn = load_compose(f)
        assert defn.metadata.name == "test-compose"
        assert len(defn.spec.services) == 2

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(ComposeLoadError, match="Cannot read"):
            load_compose(tmp_path / "nope.yaml")

    def test_load_invalid_yaml(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text(": invalid: yaml: [")
        with pytest.raises(ComposeLoadError, match="Invalid YAML"):
            load_compose(f)

    def test_load_not_mapping(self, tmp_path):
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        with pytest.raises(ComposeLoadError, match="Expected a YAML mapping"):
            load_compose(f)

    def test_load_validation_error(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("apiVersion: initrunner/v1\nkind: Compose\n")
        with pytest.raises(ComposeLoadError, match="Validation failed"):
            load_compose(f)
