"""Convert InitRunner agent output to A2A 1.0 Parts."""

from __future__ import annotations

from typing import Any

from a2a.helpers.proto_helpers import new_data_part, new_text_part  # type: ignore[import-not-found]
from a2a.types import Part  # type: ignore[import-not-found]
from google.protobuf.json_format import ParseDict


def output_to_parts(output: Any) -> list[Part]:
    """Serialize agent output as A2A parts for both the artifact and status message.

    Strings become a single text part. Structured values become a data part
    whose ``metadata.json_schema`` is the Pydantic serialization schema.
    """
    if isinstance(output, str):
        return [new_text_part(output)]

    from pydantic import TypeAdapter

    adapter = TypeAdapter(type(output))
    part = new_data_part(adapter.dump_python(output, mode="json"))
    ParseDict(
        {"json_schema": adapter.json_schema(mode="serialization")},
        part.metadata,
    )
    return [part]
