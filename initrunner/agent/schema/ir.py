"""Canonical composition IR.

Public YAML (envelope or flat) normalizes into this. Team presets and Flow
graphs keep distinct ``handoff`` modes so the first ship can wrap the existing
executors instead of pretending they are the same runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Shape = Literal["solo", "preset", "graph", "roster"]
Handoff = Literal["team", "flow"]
RunPreset = Literal["sequential", "parallel", "debate", "ensemble"]


@dataclass(frozen=True)
class ThenIR:
    to: tuple[str, ...]
    strategy: str = "all"
    ensemble: dict[str, Any] | None = None
    loop_back: dict[str, Any] | None = None
    keep_existing_sinks: bool = False
    queue_size: int = 100
    timeout_seconds: int = 60
    circuit_breaker_threshold: int | None = None
    circuit_breaker_reset_seconds: int = 60


@dataclass(frozen=True)
class ChildIR:
    name: str
    prompt: str | None = None
    use: str | None = None
    model: dict[str, Any] | None = None
    tools: tuple[dict[str, Any], ...] = ()
    tools_mode: str = "extend"
    environment: tuple[tuple[str, str], ...] = ()
    triggers: tuple[dict[str, Any], ...] = ()
    then: ThenIR | None = None
    needs: tuple[str, ...] = ()  # envelope Flow only; not a public v3 field


@dataclass(frozen=True)
class CompositionIR:
    name: str
    shape: Shape
    prompt: str | None = None
    model: dict[str, Any] | None = None
    tools: tuple[dict[str, Any], ...] = ()
    run: RunPreset | None = None
    children: tuple[ChildIR, ...] = ()
    handoff: Handoff | None = None
    description: str = ""
    tags: tuple[str, ...] = ()
    author: str = ""
    team: str = ""
    version: str = ""
    dependencies: tuple[str, ...] = ()
    spec_version: int | None = None
    handoff_max_chars: int | None = None
    warnings: tuple[str, ...] = ()
    extras: dict[str, Any] = field(default_factory=dict)
