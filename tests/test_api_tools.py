"""Tests for declarative API tools."""

from __future__ import annotations

import inspect
import os
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from initrunner.agent.api_tools import (
    _extract_response,
    _format_template,
    _make_endpoint_fn,
    _resolve_headers,
    build_api_toolset,
)
from initrunner.agent.schema.tools import ApiEndpoint, ApiParameter, ApiToolConfig
from initrunner.agent.tools._registry import ToolBuildContext


def _make_ctx(role_dir=None):
    """Build a minimal ToolBuildContext for tests."""
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-4o-mini"},
            },
        }
    )
    return ToolBuildContext(role=role, role_dir=role_dir)


class TestApiParameterValidation:
    def test_valid_identifier(self):
        p = ApiParameter(name="city", type="string")
        assert p.name == "city"

    def test_invalid_identifier_raises(self):
        with pytest.raises(ValidationError, match="not a valid Python identifier"):
            ApiParameter(name="my-param", type="string")

    def test_reserved_word_allowed(self):
        # Python identifiers like 'type' are valid identifiers
        p = ApiParameter(name="count", type="integer")
        assert p.name == "count"


class TestApiToolConfigParsing:
    def test_minimal_config(self):
        config = ApiToolConfig(
            name="test-api",
            base_url="https://api.example.com",
            endpoints=[
                ApiEndpoint(name="get_data", path="/data"),
            ],
        )
        assert config.name == "test-api"
        assert len(config.endpoints) == 1

    def test_summary(self):
        config = ApiToolConfig(
            name="weather",
            base_url="https://api.weather.com",
            endpoints=[
                ApiEndpoint(name="current", path="/current"),
                ApiEndpoint(name="forecast", path="/forecast"),
            ],
        )
        assert config.summary() == "api: weather (2 endpoints)"

    def test_full_config(self):
        config = ApiToolConfig(
            name="github",
            description="GitHub API",
            base_url="https://api.github.com",
            headers={"Accept": "application/json"},
            auth={"Authorization": "Bearer ${GITHUB_TOKEN}"},
            endpoints=[
                ApiEndpoint(
                    name="get_repo",
                    method="GET",
                    path="/repos/{owner}/{repo}",
                    description="Get repository info",
                    parameters=[
                        ApiParameter(name="owner", type="string", required=True),
                        ApiParameter(name="repo", type="string", required=True),
                    ],
                    timeout=60,
                ),
            ],
        )
        assert config.headers["Accept"] == "application/json"
        assert len(config.endpoints[0].parameters) == 2


class TestBuildApiToolset:
    def test_tool_count_matches_endpoints(self):
        config = ApiToolConfig(
            name="test",
            base_url="https://example.com",
            endpoints=[
                ApiEndpoint(name="endpoint_a", path="/a"),
                ApiEndpoint(name="endpoint_b", path="/b"),
                ApiEndpoint(name="endpoint_c", path="/c"),
            ],
        )
        toolset = build_api_toolset(config, _make_ctx())
        assert len(toolset.tools) == 3
        assert "endpoint_a" in toolset.tools
        assert "endpoint_b" in toolset.tools
        assert "endpoint_c" in toolset.tools


class TestApiToolsetSsrf:
    @patch("initrunner.agent._urls.socket.getaddrinfo")
    def test_ssrf_blocked_for_private_base_url(self, mock_dns):
        mock_dns.side_effect = lambda *a, **kw: [(2, 1, 6, "", ("10.0.0.1", 443))]
        config = ApiToolConfig(
            name="internal",
            base_url="https://10.0.0.1",
            endpoints=[
                ApiEndpoint(name="get_secret", path="/secret"),
            ],
        )
        toolset = build_api_toolset(config, _make_ctx())
        fn = toolset.tools["get_secret"].function
        result = fn()
        assert "SSRF blocked" in result


class TestMakeEndpointFn:
    def test_signature_matches_parameters(self):
        endpoint = ApiEndpoint(
            name="search",
            path="/search",
            parameters=[
                ApiParameter(name="query", type="string", required=True),
                ApiParameter(name="limit", type="integer", required=False, default=10),
            ],
        )
        fn = _make_endpoint_fn(endpoint, "https://example.com", {})
        sig = inspect.signature(fn)

        assert "query" in sig.parameters
        assert "limit" in sig.parameters
        assert sig.parameters["query"].default is inspect.Parameter.empty
        assert sig.parameters["limit"].default == 10
        assert sig.return_annotation is str

    def test_annotations_match_types(self):
        endpoint = ApiEndpoint(
            name="calc",
            path="/calc",
            parameters=[
                ApiParameter(name="x", type="number", required=True),
                ApiParameter(name="flag", type="boolean", required=False, default=False),
            ],
        )
        fn = _make_endpoint_fn(endpoint, "https://example.com", {})

        assert fn.__annotations__["x"] is float
        assert fn.__annotations__["flag"] is bool
        assert fn.__annotations__["return"] is str

    def test_function_metadata(self):
        endpoint = ApiEndpoint(
            name="get_user",
            path="/users/{id}",
            description="Fetch a user by ID",
        )
        fn = _make_endpoint_fn(endpoint, "https://example.com", {})

        assert fn.__name__ == "get_user"  # type: ignore[attr-defined]
        assert fn.__doc__ == "Fetch a user by ID"

    def test_default_doc_from_method_path(self):
        endpoint = ApiEndpoint(name="delete_item", method="DELETE", path="/items/{id}")
        fn = _make_endpoint_fn(endpoint, "https://example.com", {})
        assert fn.__doc__ == "DELETE /items/{id}"

    @patch("initrunner.agent.api_tools.httpx.Client")
    def test_makes_correct_request(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.text = '{"status": "ok"}'
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        endpoint = ApiEndpoint(
            name="create_item",
            method="POST",
            path="/items/{category}",
            parameters=[
                ApiParameter(name="category", type="string", required=True),
                ApiParameter(name="name", type="string", required=True),
            ],
            body_template={"item_name": "{name}"},
        )
        fn = _make_endpoint_fn(endpoint, "https://api.test.com", {"X-Key": "abc"})
        fn(category="books", name="Python 101")

        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs["method"] == "POST"
        assert call_kwargs.kwargs["url"] == "https://api.test.com/items/books"
        assert call_kwargs.kwargs["headers"]["X-Key"] == "abc"
        assert call_kwargs.kwargs["json"] == {"item_name": "Python 101"}

    @patch("initrunner.agent.api_tools.httpx.Client")
    def test_query_params(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.text = "ok"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        endpoint = ApiEndpoint(
            name="search",
            path="/search",
            parameters=[
                ApiParameter(name="q", type="string", required=True),
            ],
            query_params={"query": "{q}"},
        )
        fn = _make_endpoint_fn(endpoint, "https://example.com", {})
        fn(q="test query")

        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs["params"] == {"query": "test query"}


class TestResolveHeaders:
    def test_env_var_resolution(self):
        with patch.dict(os.environ, {"MY_TOKEN": "secret123"}):
            result = _resolve_headers({"Authorization": "Bearer ${MY_TOKEN}"})
        assert result["Authorization"] == "Bearer secret123"

    def test_unset_env_var_kept_as_is(self):
        env = dict(os.environ)
        env.pop("UNSET_VAR_XYZ", None)
        with patch.dict(os.environ, env, clear=True):
            result = _resolve_headers({"Auth": "${UNSET_VAR_XYZ}"})
        assert result["Auth"] == "${UNSET_VAR_XYZ}"

    def test_no_env_vars(self):
        result = _resolve_headers({"Content-Type": "application/json"})
        assert result["Content-Type"] == "application/json"


class TestFormatTemplate:
    def test_simple_substitution(self):
        result = _format_template({"name": "{user}", "age": 30}, {"user": "Alice"})
        assert result == {"name": "Alice", "age": 30}

    def test_nested_dict(self):
        result = _format_template(
            {"data": {"name": "{user}"}},
            {"user": "Bob"},
        )
        assert result == {"data": {"name": "Bob"}}

    def test_missing_key_preserved(self):
        result = _format_template({"msg": "{missing}"}, {})
        assert result == {"msg": "{missing}"}


class TestExtractResponse:
    def test_no_extract_returns_text(self):
        resp = MagicMock()
        resp.text = "hello world"
        assert _extract_response(resp, None) == "hello world"

    def test_jsonpath_simple(self):
        resp = MagicMock()
        resp.json.return_value = {"data": {"id": 42}}
        assert _extract_response(resp, "$.data.id") == "42"

    def test_jsonpath_nested(self):
        resp = MagicMock()
        resp.json.return_value = {"a": {"b": {"c": "deep"}}}
        assert _extract_response(resp, "$.a.b.c") == "deep"

    def test_jsonpath_not_found(self):
        resp = MagicMock()
        resp.json.return_value = {"data": {}}
        result = _extract_response(resp, "$.data.missing")
        assert "not found" in result

    def test_non_json_response_returns_text(self):
        resp = MagicMock()
        resp.json.side_effect = ValueError("not json")
        resp.text = "plain text"
        assert _extract_response(resp, "$.data") == "plain text"


class TestApiToolConfigInRoleYaml:
    def test_parses_from_dict(self):
        """API tool config parses correctly via the field_validator."""
        from initrunner.agent.schema.role import AgentSpec

        spec_data = {
            "role": "test",
            "model": {"provider": "openai", "name": "gpt-4o-mini"},
            "tools": [
                {
                    "type": "api",
                    "name": "weather",
                    "base_url": "https://api.weather.com",
                    "endpoints": [
                        {
                            "name": "get_weather",
                            "path": "/weather/{city}",
                            "parameters": [
                                {"name": "city", "type": "string", "required": True},
                            ],
                        },
                    ],
                }
            ],
        }
        spec = AgentSpec.model_validate(spec_data)
        assert len(spec.tools) == 1
        tool = spec.tools[0]
        assert isinstance(tool, ApiToolConfig)
        assert tool.name == "weather"
