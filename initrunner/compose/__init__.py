"""Compose module: multi-agent orchestration."""

from initrunner.compose.loader import ComposeLoadError, load_compose
from initrunner.compose.schema import (
    ComposeDefinition,
    ComposeMetadata,
    ComposeServiceConfig,
    ComposeSpec,
    DelegateSinkConfig,
    HealthCheckConfig,
    RestartPolicy,
    SharedMemoryConfig,
)
from initrunner.compose.systemd import (
    SystemdError,
    UnitInfo,
    install_unit,
    uninstall_unit,
    unit_name_for,
)

__all__ = [
    "ComposeDefinition",
    "ComposeLoadError",
    "ComposeMetadata",
    "ComposeServiceConfig",
    "ComposeSpec",
    "DelegateSinkConfig",
    "HealthCheckConfig",
    "RestartPolicy",
    "SharedMemoryConfig",
    "SystemdError",
    "UnitInfo",
    "install_unit",
    "load_compose",
    "uninstall_unit",
    "unit_name_for",
]
