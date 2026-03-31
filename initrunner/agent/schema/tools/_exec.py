"""Execution tool configurations: Python, shell, script, SQL, git."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from initrunner.agent.schema.tools._base import ToolConfigBase


class PythonToolConfig(ToolConfigBase):
    type: Literal["python"] = "python"
    timeout_seconds: int = 30
    max_output_bytes: int = 102_400
    working_dir: str | None = None
    require_confirmation: bool = True
    network_disabled: bool = True

    def summary(self) -> str:
        confirm = ", confirm" if self.require_confirmation else ""
        net = ", no-network" if self.network_disabled else ""
        return f"python: timeout={self.timeout_seconds}s{confirm}{net}"


class ShellToolConfig(ToolConfigBase):
    type: Literal["shell"] = "shell"
    allowed_commands: list[str] = []
    blocked_commands: list[str] = Field(
        default_factory=lambda: [
            "rm",
            "mkfs",
            "dd",
            "fdisk",
            "parted",
            "mount",
            "umount",
            "shutdown",
            "reboot",
            "halt",
            "poweroff",
            "chmod",
            "chown",
            "passwd",
            "useradd",
            "userdel",
            "sudo",
            "su",
        ]
    )
    working_dir: str | None = None
    timeout_seconds: int = 30
    max_output_bytes: int = 102_400
    require_confirmation: bool = True

    def summary(self) -> str:
        confirm = ", confirm" if self.require_confirmation else ""
        return f"shell: timeout={self.timeout_seconds}s{confirm}"


class ScriptParameter(BaseModel):
    """A parameter for a script tool, injected as an uppercase env var."""

    name: str
    description: str = ""
    required: bool = False
    default: str = ""

    @field_validator("name")
    @classmethod
    def _valid_identifier(cls, v: str) -> str:
        if not v.isidentifier():
            raise ValueError(f"'{v}' is not a valid Python identifier")
        return v


class ScriptDefinition(BaseModel):
    """A single inline script that becomes a tool function."""

    name: str
    description: str = ""
    body: str
    interpreter: str | None = None  # None → inherit from parent
    parameters: list[ScriptParameter] = []
    timeout_seconds: int | None = None  # None → inherit from parent
    allowed_commands: list[str] = []  # optional: when set, validate first token per line

    @field_validator("name")
    @classmethod
    def _valid_identifier(cls, v: str) -> str:
        if not v.isidentifier():
            raise ValueError(f"'{v}' is not a valid Python identifier")
        return v

    @field_validator("body")
    @classmethod
    def _non_empty_body(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("script body must not be empty")
        return v


class ScriptToolConfig(ToolConfigBase):
    type: Literal["script"] = "script"
    scripts: list[ScriptDefinition]
    interpreter: str = "/bin/sh"
    timeout_seconds: int = 30
    max_output_bytes: int = 102_400
    working_dir: str | None = None

    @field_validator("scripts")
    @classmethod
    def _at_least_one(cls, v: list[ScriptDefinition]) -> list[ScriptDefinition]:
        if not v:
            raise ValueError("at least one script must be defined")
        return v

    @model_validator(mode="after")
    def _unique_names(self) -> ScriptToolConfig:
        names = [s.name for s in self.scripts]
        if len(names) != len(set(names)):
            raise ValueError("script names must be unique")
        return self

    def summary(self) -> str:
        names = ", ".join(s.name for s in self.scripts[:3])
        suffix = f" +{len(self.scripts) - 3} more" if len(self.scripts) > 3 else ""
        return f"script: {names}{suffix}"


class SqlToolConfig(ToolConfigBase):
    type: Literal["sql"] = "sql"
    database: str
    read_only: bool = True
    max_rows: int = 100
    max_result_bytes: int = 102_400
    timeout_seconds: int = 10

    def summary(self) -> str:
        return f"sql: {self.database} (ro={self.read_only})"


class GitToolConfig(ToolConfigBase):
    type: Literal["git"] = "git"
    repo_path: str = "."
    read_only: bool = True
    timeout_seconds: int = 30
    max_output_bytes: int = 102_400

    def summary(self) -> str:
        return f"git: {self.repo_path} (ro={self.read_only})"
