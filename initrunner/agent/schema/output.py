"""Structured output configuration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OutputMode = Literal["auto", "tool", "native", "prompted", "text"]
"""How structured output is requested from the model.

``auto`` (the default) defers to PydanticAI, which picks a mode from the
model's ``ModelProfile.default_structured_output_mode``. The explicit modes
force a specific strategy:

- ``tool``: structured output via a tool call (the most widely compatible mode).
- ``native``: the provider's native structured-output API (faster and cheaper
  on models that support it, e.g. OpenAI Structured Outputs).
- ``prompted``: the schema is described in the prompt and the model is asked to
  reply with matching JSON (a fallback for providers without native support).
- ``text``: plain unstructured text; only valid with ``type: text``.
"""


class OutputConfig(BaseModel):
    type: Literal["text", "json_schema"] = "text"
    schema_: dict[str, Any] | None = Field(None, alias="schema")
    schema_file: str | None = None
    mode: OutputMode = "auto"

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _validate_output(self) -> OutputConfig:
        if self.type == "json_schema":
            if self.schema_ is None and self.schema_file is None:
                raise ValueError("json_schema output requires 'schema' or 'schema_file'")
            if self.schema_ is not None and self.schema_file is not None:
                raise ValueError("'schema' and 'schema_file' are mutually exclusive")
        self._validate_mode()
        return self

    def _validate_mode(self) -> None:
        if self.type == "text" and self.mode not in ("auto", "text"):
            raise ValueError(
                f"mode must be 'text' or 'auto' when output type is 'text', got '{self.mode}'"
            )
        if self.mode == "text" and self.type != "text":
            raise ValueError("type must be 'text' when mode is 'text'")
        if self.mode in ("tool", "native", "prompted") and self.type != "json_schema":
            raise ValueError(f"mode '{self.mode}' requires json_schema output")
