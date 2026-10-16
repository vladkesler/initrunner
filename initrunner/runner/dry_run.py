"""TestModel used by ``--dry-run``.

PydanticAI 2.56 rejects a request that carries native tools. Roles that declare
WebSearch or ImageGeneration still need a simulated answer, so those tools are
dropped for the dry run only.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings


def dry_run_model(output_text: str) -> TestModel:
    """Return a TestModel that answers *output_text* and ignores native tools."""

    class _DryRunModel(TestModel):
        def _request(
            self,
            messages: list[ModelMessage],
            model_settings: ModelSettings | None,
            model_request_parameters: ModelRequestParameters,
        ):
            if model_request_parameters.native_tools:
                model_request_parameters = replace(model_request_parameters, native_tools=[])
            return super()._request(messages, model_settings, model_request_parameters)

    return _DryRunModel(custom_output_text=output_text, call_tools=[])
