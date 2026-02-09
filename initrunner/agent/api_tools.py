"""Declarative API tool builder: generates PydanticAI tools from YAML config."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import httpx
from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._env import resolve_env_vars
from initrunner.agent._urls import SSRFBlocked, SSRFSafeTransport
from initrunner.agent.schema import ApiEndpoint, ApiToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

_JSON_SCHEMA_TO_PYTHON: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


def _resolve_headers(headers: dict[str, str]) -> dict[str, str]:
    """Resolve environment variable references in header values (${VAR} syntax)."""
    return {key: resolve_env_vars(value) for key, value in headers.items()}


def _safe_substitute(template_str: str, values: dict[str, Any]) -> str:
    """Replace ``{key}`` placeholders with values using str.replace (no format injection)."""
    result = template_str
    for k, v in values.items():
        result = result.replace(f"{{{k}}}", str(v))
    return result


def _format_template(template: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Recursively format string values in a template dict with provided values."""
    result: dict[str, Any] = {}
    for key, val in template.items():
        if isinstance(val, str):
            result[key] = _safe_substitute(val, values)
        elif isinstance(val, dict):
            result[key] = _format_template(val, values)
        else:
            result[key] = val
    return result


def _extract_response(response: httpx.Response, extract: str | None) -> str:
    """Extract data from response using simple JSONPath ($.field.subfield)."""
    if extract is None:
        return response.text

    try:
        data = response.json()
    except Exception:
        return response.text

    # Simple JSONPath: $.field.subfield
    if extract.startswith("$."):
        parts = extract[2:].split(".")
        current: Any = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit():
                current = current[int(part)]
            else:
                return f"JSONPath '{extract}' not found in response"
        return str(current)

    return response.text


def _make_endpoint_fn(
    endpoint: ApiEndpoint, base_url: str, base_headers: dict[str, str]
) -> Callable:
    """Build a callable with proper inspect.Signature for PydanticAI."""
    # Build inspect.Parameter list
    params: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}
    for p in endpoint.parameters:
        py_type = _JSON_SCHEMA_TO_PYTHON[p.type]
        annotations[p.name] = py_type
        default = inspect.Parameter.empty if p.required else p.default
        params.append(
            inspect.Parameter(
                p.name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=py_type,
            )
        )
    annotations["return"] = str

    sig = inspect.Signature(params, return_annotation=str)

    # Capture in closure
    _endpoint = endpoint
    _base_url = base_url
    _base_headers = base_headers

    def endpoint_fn(**kwargs: Any) -> str:
        path = _safe_substitute(_endpoint.path, kwargs)
        url = f"{_base_url.rstrip('/')}/{path.lstrip('/')}"

        request_kwargs: dict[str, Any] = {
            "method": _endpoint.method,
            "url": url,
            "headers": {**_resolve_headers(_base_headers), **_resolve_headers(_endpoint.headers)},
            "timeout": _endpoint.timeout,
        }
        if _endpoint.body_template is not None:
            request_kwargs["json"] = _format_template(_endpoint.body_template, kwargs)
        if _endpoint.query_params:
            request_kwargs["params"] = _format_template(_endpoint.query_params, kwargs)

        try:
            with httpx.Client(transport=SSRFSafeTransport()) as client:
                response = client.request(**request_kwargs)
                response.raise_for_status()
                return _extract_response(response, _endpoint.response_extract)
        except SSRFBlocked as e:
            return str(e)
        except httpx.HTTPStatusError as e:
            return f"HTTP {e.response.status_code}: {e.response.text[:500]}"
        except httpx.HTTPError as e:
            return f"HTTP error: {e}"

    endpoint_fn.__name__ = endpoint.name
    endpoint_fn.__qualname__ = endpoint.name
    endpoint_fn.__doc__ = endpoint.description or f"{endpoint.method} {endpoint.path}"
    endpoint_fn.__signature__ = sig  # type: ignore[attr-defined]
    endpoint_fn.__annotations__ = annotations

    return endpoint_fn


@register_tool("api", ApiToolConfig)
def build_api_toolset(config: ApiToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset from an ApiToolConfig."""
    # Merge auth into base headers
    base_headers = {**config.headers}
    for key, value in config.auth.items():
        base_headers[key] = value

    toolset = FunctionToolset()
    for endpoint in config.endpoints:
        fn = _make_endpoint_fn(endpoint, config.base_url, base_headers)
        toolset.tool(fn)

    return toolset
