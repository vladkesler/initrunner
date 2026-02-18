"""Structured output configuration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OutputConfig(BaseModel):
    type: Literal["text", "json_schema"] = "text"
    schema_: dict[str, Any] | None = Field(None, alias="schema")
    schema_file: str | None = None

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _validate_output(self) -> OutputConfig:
        if self.type == "json_schema":
            if self.schema_ is None and self.schema_file is None:
                raise ValueError("json_schema output requires 'schema' or 'schema_file'")
            if self.schema_ is not None and self.schema_file is not None:
                raise ValueError("'schema' and 'schema_file' are mutually exclusive")
        return self
