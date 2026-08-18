"""Tests for A2A 1.0: compat, invoker, schema, server, CLI."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

a2a = pytest.importorskip("a2a", reason="a2a extras not installed")

import httpx  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.responses import JSONResponse, Response  # noqa: E402
from starlette.routing import Route  # noqa: E402

from initrunner.agent.delegation import A2AInvoker, reset_context  # noqa: E402
from initrunner.agent.schema.role import SkillDefinition, SkillFrontmatter  # noqa: E402
from initrunner.agent.skills import ResolvedSkill  # noqa: E402
from tests.conftest import make_role  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_context():
    reset_context()
    yield
    reset_context()


def _rpc(method: str, params: dict[str, Any], *, rpc_id: int = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}


def _user_message(
    text: str, *, message_id: str = "m1", context_id: str | None = None
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "role": "ROLE_USER",
        "messageId": message_id,
        "parts": [{"text": text}],
    }
    if context_id is not None:
        msg["contextId"] = context_id
    return msg


def _run_result(*, output: Any = "Hello back!", success: bool = True, error: str | None = None):
    result = MagicMock()
    result.success = success
    result.output = output
    result.error = error
    return result


def _minimal_card(url: str = "http://test/") -> dict[str, Any]:
    return {
        "name": "stub",
        "description": "stub",
        "version": "1.0.0",
        "supportedInterfaces": [
            {"url": url, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
        ],
        "capabilities": {"streaming": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [],
    }


def _completed_send_result(text: str = "ok") -> dict[str, Any]:
    return {
        "task": {
            "id": "task-1",
            "contextId": "ctx-1",
            "status": {
                "state": "TASK_STATE_COMPLETED",
                "message": {
                    "role": "ROLE_AGENT",
                    "messageId": "m2",
                    "parts": [{"text": text}],
                },
            },
            "artifacts": [
                {
                    "artifactId": "a1",
                    "name": "result",
                    "parts": [{"text": text}],
                }
            ],
            "history": [],
        }
    }


def _stub_app(
    *,
    rpc_handler,
    card: dict[str, Any] | None = None,
    card_status: int = 200,
) -> Starlette:
    async def get_card(_request):
        if card_status != 200:
            return Response("nope", status_code=card_status)
        return JSONResponse(card or _minimal_card())

    return Starlette(
        routes=[
            Route("/.well-known/agent-card.json", get_card, methods=["GET"]),
            Route("/", rpc_handler, methods=["POST"]),
        ]
    )


# ---------------------------------------------------------------------------
# Compat / dependency
# ---------------------------------------------------------------------------


class TestCompat:
    def test_require_a2a_when_missing(self):
        from initrunner._compat import MissingExtraError, require_a2a

        with patch("initrunner._compat.importlib.import_module", side_effect=ImportError):
            with pytest.raises(MissingExtraError, match="initrunner\\[a2a\\]"):
                require_a2a()

    def test_a2a_in_extra_packages(self):
        from initrunner._compat import _EXTRA_PACKAGES

        assert "a2a" in _EXTRA_PACKAGES
        assert _EXTRA_PACKAGES["a2a"] == ("a2a", "a2a-sdk")


# ---------------------------------------------------------------------------
# Card / convert
# ---------------------------------------------------------------------------


class TestBuildAgentCard:
    def test_card_fields_and_skills(self):
        from a2a.server.request_handlers.response_helpers import agent_card_to_dict

        from initrunner.a2a.card import build_agent_card

        role = make_role(name="researcher")
        role.metadata.description = "Gathers research"
        role.metadata.version = "1.2.3"
        role.metadata.tags = ["research"]
        skill = ResolvedSkill(
            definition=SkillDefinition(
                frontmatter=SkillFrontmatter(name="web-search", description="Search the web"),
                prompt="do research",
            ),
            source_path=Path("/tmp/skill"),
        )
        card = build_agent_card(
            role,
            url="http://example:8000",
            require_auth=True,
            skills=[skill],
        )
        data = agent_card_to_dict(card)
        assert data["name"] == "researcher"
        assert data["version"] == "1.2.3"
        assert data["supportedInterfaces"][0]["protocolVersion"] == "1.0"
        assert data["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
        assert data["skills"][0]["id"] == "researcher"
        assert data["skills"][1]["id"] == "web-search"
        assert data["securitySchemes"]["bearer"]["httpAuthSecurityScheme"]["scheme"] == "bearer"

    def test_output_to_parts_text_and_structured(self):
        from pydantic import BaseModel

        from initrunner.a2a.convert import output_to_parts

        text_parts = output_to_parts("hello")
        assert len(text_parts) == 1
        assert text_parts[0].text == "hello"

        class Score(BaseModel):
            score: float

        data_parts = output_to_parts(Score(score=0.95))
        assert data_parts[0].HasField("data")
        assert "json_schema" in data_parts[0].metadata


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class TestA2AServer:
    def test_build_a2a_app(self):
        from initrunner.a2a.server import build_a2a_app

        app = build_a2a_app(MagicMock(), make_role(name="test-agent"), url="http://127.0.0.1:9000")
        assert isinstance(app, Starlette)
        paths = {route.path for route in app.routes}  # type: ignore[attr-defined]
        assert "/.well-known/agent-card.json" in paths
        assert "/" in paths

    def test_build_a2a_app_with_api_key_and_cors(self):
        from initrunner.a2a.server import build_a2a_app

        app = build_a2a_app(
            MagicMock(),
            make_role(name="test-agent"),
            url="http://127.0.0.1:8000",
            api_key="secret",
            cors_origins=["http://localhost:3000"],
        )
        assert app is not None


class TestA2AProtocol:
    async def _client(self, app: Starlette, **headers: str):
        merged = {"A2A-Version": "1.0", **headers}
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers=merged,
        )

    @pytest.mark.anyio
    async def test_card_get_without_auth(self):
        from initrunner.a2a.server import build_a2a_app

        role = make_role(name="researcher")
        role.metadata.description = "A test agent"
        role.metadata.version = "9.9.9"
        skill = ResolvedSkill(
            definition=SkillDefinition(
                frontmatter=SkillFrontmatter(name="web-search", description="Search"),
                prompt="p",
            ),
            source_path=Path("/tmp/s"),
        )
        app = build_a2a_app(
            MagicMock(),
            role,
            url="http://test",
            api_key="secret",
            skills=[skill],
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200
        card = resp.json()
        assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
        assert card["version"] == "9.9.9"
        assert any(s["id"] == "web-search" for s in card["skills"])
        assert card["securitySchemes"]["bearer"]["httpAuthSecurityScheme"]["scheme"] == "bearer"

    @pytest.mark.anyio
    async def test_send_message_blocking_success(self):
        from initrunner.a2a.server import build_a2a_app

        role = make_role(name="researcher")
        result = _run_result(output="Hello back!")
        with patch(
            "initrunner.a2a.server.execute_run_async",
            new_callable=AsyncMock,
            return_value=(result, []),
        ):
            app = build_a2a_app(MagicMock(), role, url="http://test")
            async with await self._client(app) as client:
                resp = await client.post(
                    "/", json=_rpc("SendMessage", {"message": _user_message("Hello")})
                )
        assert resp.status_code == 200
        task = resp.json()["result"]["task"]
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert task["artifacts"][0]["parts"][0]["text"] == "Hello back!"
        assert task["status"]["message"]["parts"][0]["text"] == "Hello back!"
        assert task["history"][0]["role"] == "ROLE_USER"
        assert task["history"][0]["parts"][0]["text"] == "Hello"

    @pytest.mark.anyio
    async def test_structured_output_is_data_part(self):
        from pydantic import BaseModel

        from initrunner.a2a.server import build_a2a_app

        class Score(BaseModel):
            score: float

        role = make_role(name="scorer")
        result = _run_result(output=Score(score=0.95))
        with patch(
            "initrunner.a2a.server.execute_run_async",
            new_callable=AsyncMock,
            return_value=(result, []),
        ):
            app = build_a2a_app(MagicMock(), role, url="http://test")
            async with await self._client(app) as client:
                resp = await client.post(
                    "/", json=_rpc("SendMessage", {"message": _user_message("score")})
                )
        part = resp.json()["result"]["task"]["artifacts"][0]["parts"][0]
        assert "text" not in part
        assert part["data"]["score"] == 0.95
        assert "jsonSchema" in part["metadata"] or "json_schema" in part["metadata"]

    @pytest.mark.anyio
    async def test_failed_run_carries_error(self):
        from initrunner.a2a.server import build_a2a_app

        role = make_role(name="researcher")
        result = _run_result(success=False, error="model error")
        with patch(
            "initrunner.a2a.server.execute_run_async",
            new_callable=AsyncMock,
            return_value=(result, []),
        ):
            app = build_a2a_app(MagicMock(), role, url="http://test")
            async with await self._client(app) as client:
                resp = await client.post(
                    "/", json=_rpc("SendMessage", {"message": _user_message("Hello")})
                )
        task = resp.json()["result"]["task"]
        assert task["status"]["state"] == "TASK_STATE_FAILED"
        assert "model error" in task["status"]["message"]["parts"][0]["text"]

    @pytest.mark.anyio
    async def test_multi_turn_reuses_message_history(self):
        from initrunner.a2a.server import build_a2a_app

        role = make_role(name="researcher")
        prior = [object()]
        first = _run_result(output="turn-1")
        second = _run_result(output="turn-2")
        mock_run = AsyncMock(side_effect=[(first, prior), (second, prior)])
        with patch("initrunner.a2a.server.execute_run_async", new=mock_run):
            app = build_a2a_app(MagicMock(), role, url="http://test")
            async with await self._client(app) as client:
                first_resp = await client.post(
                    "/",
                    json=_rpc("SendMessage", {"message": _user_message("one", context_id="ctx-a")}),
                )
                context_id = first_resp.json()["result"]["task"]["contextId"]
                await client.post(
                    "/",
                    json=_rpc(
                        "SendMessage",
                        {"message": _user_message("two", message_id="m2", context_id=context_id)},
                    ),
                )
        assert mock_run.await_count == 2
        second_kwargs = mock_run.await_args_list[1].kwargs
        assert second_kwargs["message_history"] is prior

    @pytest.mark.anyio
    async def test_get_task(self):
        from initrunner.a2a.server import build_a2a_app

        role = make_role(name="researcher")
        result = _run_result(output="done")
        with patch(
            "initrunner.a2a.server.execute_run_async",
            new_callable=AsyncMock,
            return_value=(result, []),
        ):
            app = build_a2a_app(MagicMock(), role, url="http://test")
            async with await self._client(app) as client:
                sent = await client.post(
                    "/", json=_rpc("SendMessage", {"message": _user_message("Hello")})
                )
                task_id = sent.json()["result"]["task"]["id"]
                got = await client.post("/", json=_rpc("GetTask", {"id": task_id}))
        assert got.json()["result"]["status"]["state"] == "TASK_STATE_COMPLETED"
        assert got.json()["result"]["id"] == task_id

    @pytest.mark.anyio
    async def test_cancel_task(self):
        from initrunner.a2a.server import build_a2a_app

        role = make_role(name="researcher")
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def _blocked(*_args, **_kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return _run_result(), []

        with patch("initrunner.a2a.server.execute_run_async", new=_blocked):
            app = build_a2a_app(MagicMock(), role, url="http://test")
            async with await self._client(app) as client:
                sent = await client.post(
                    "/",
                    json=_rpc(
                        "SendMessage",
                        {
                            "message": _user_message("Hello"),
                            "configuration": {"returnImmediately": True},
                        },
                    ),
                )
                task_id = sent.json()["result"]["task"]["id"]
                await started.wait()
                canceled = await client.post("/", json=_rpc("CancelTask", {"id": task_id}))

        assert canceled.json()["result"]["status"]["state"] == "TASK_STATE_CANCELED"
        assert cancelled.is_set()

    @pytest.mark.anyio
    async def test_missing_a2a_version_rejected(self):
        from initrunner.a2a.server import build_a2a_app

        app = build_a2a_app(MagicMock(), make_role(name="researcher"), url="http://test")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/", json=_rpc("SendMessage", {"message": _user_message("hi")})
            )
        assert resp.status_code == 200
        assert resp.json()["error"]["code"] == -32009

    @pytest.mark.anyio
    async def test_unknown_method(self):
        from initrunner.a2a.server import build_a2a_app

        app = build_a2a_app(MagicMock(), make_role(name="researcher"), url="http://test")
        async with await self._client(app) as client:
            resp = await client.post("/", json=_rpc("nope", {}))
        assert resp.json()["error"]["code"] == -32601

    @pytest.mark.anyio
    async def test_auth_required(self):
        from initrunner.a2a.server import build_a2a_app

        app = build_a2a_app(
            MagicMock(), make_role(name="researcher"), url="http://test", api_key="secret"
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"A2A-Version": "1.0"},
        ) as client:
            missing = await client.post(
                "/", json=_rpc("SendMessage", {"message": _user_message("hi")})
            )
            wrong = await client.post(
                "/",
                headers={"Authorization": "Bearer nope"},
                json=_rpc("SendMessage", {"message": _user_message("hi")}),
            )
        assert missing.status_code == 401
        assert wrong.status_code == 401

    @pytest.mark.anyio
    async def test_return_immediately_then_get_task(self):
        from initrunner.a2a.server import build_a2a_app

        role = make_role(name="researcher")
        gate = asyncio.Event()

        async def _slow(*_args, **_kwargs):
            await gate.wait()
            return _run_result(output="later"), []

        with patch("initrunner.a2a.server.execute_run_async", new=_slow):
            app = build_a2a_app(MagicMock(), role, url="http://test")
            async with await self._client(app) as client:
                sent = await client.post(
                    "/",
                    json=_rpc(
                        "SendMessage",
                        {
                            "message": _user_message("Hello"),
                            "configuration": {"returnImmediately": True},
                        },
                    ),
                )
                task = sent.json()["result"]["task"]
                assert task["status"]["state"] in {
                    "TASK_STATE_SUBMITTED",
                    "TASK_STATE_WORKING",
                }
                task_id = task["id"]
                gate.set()
                state = None
                for _ in range(50):
                    got = await client.post("/", json=_rpc("GetTask", {"id": task_id}))
                    state = got.json()["result"]["status"]["state"]
                    if state == "TASK_STATE_COMPLETED":
                        break
                    await asyncio.sleep(0.01)
        assert state == "TASK_STATE_COMPLETED"


# ---------------------------------------------------------------------------
# A2AInvoker
# ---------------------------------------------------------------------------


def _make_invoker(**kwargs: Any) -> A2AInvoker:
    return A2AInvoker(
        base_url=kwargs.get("base_url", "http://test"),
        agent_name=kwargs.get("agent_name", "researcher"),
        timeout=kwargs.get("timeout", 30),
        headers_env=kwargs.get("headers_env"),
        source_metadata=kwargs.get("source_metadata"),
        _httpx_client_factory=kwargs.get("_httpx_client_factory"),
    )


def _factory_for(app: Starlette, **client_kwargs: Any):
    def _factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            **client_kwargs,
        )

    return _factory


class TestA2AInvokerSuccess:
    def test_completed_against_real_app_and_reuses_context(self):
        from initrunner.a2a.server import build_a2a_app

        role = make_role(name="researcher")
        mock_run = AsyncMock(
            side_effect=[
                (_run_result(output="first"), ["hist"]),
                (_run_result(output="second"), ["hist", "more"]),
            ]
        )
        with patch("initrunner.a2a.server.execute_run_async", new=mock_run):
            app = build_a2a_app(MagicMock(), role, url="http://test")
            invoker = _make_invoker(_httpx_client_factory=_factory_for(app))
            assert invoker.invoke("one") == "first"
            assert invoker.invoke("two") == "second"
        assert mock_run.await_count == 2
        assert mock_run.await_args_list[1].kwargs["message_history"] == ["hist"]

    def test_completed_data_artifact(self):
        async def rpc(request):
            body = await request.json()
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {
                        "task": {
                            "id": "t1",
                            "contextId": "c1",
                            "status": {"state": "TASK_STATE_COMPLETED"},
                            "artifacts": [
                                {
                                    "artifactId": "a1",
                                    "parts": [{"data": {"score": 0.95}}],
                                }
                            ],
                        }
                    },
                }
            )

        invoker = _make_invoker(_httpx_client_factory=_factory_for(_stub_app(rpc_handler=rpc)))
        result = invoker.invoke("score this")
        assert '"score": 0.95' in result


class TestA2AInvokerErrors:
    def test_failed_task(self):
        async def rpc(request):
            body = await request.json()
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {
                        "task": {
                            "id": "t1",
                            "contextId": "c1",
                            "status": {
                                "state": "TASK_STATE_FAILED",
                                "message": {
                                    "role": "ROLE_AGENT",
                                    "messageId": "m2",
                                    "parts": [{"text": "boom"}],
                                },
                            },
                        }
                    },
                }
            )

        result = _make_invoker(
            _httpx_client_factory=_factory_for(_stub_app(rpc_handler=rpc))
        ).invoke("hello")
        assert "[DELEGATION ERROR]" in result
        assert "failed" in result.lower()
        assert "boom" in result

    def test_rejected_task(self):
        async def rpc(request):
            body = await request.json()
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {
                        "task": {
                            "id": "t1",
                            "contextId": "c1",
                            "status": {"state": "TASK_STATE_REJECTED"},
                        }
                    },
                }
            )

        result = _make_invoker(
            _httpx_client_factory=_factory_for(_stub_app(rpc_handler=rpc))
        ).invoke("hello")
        assert "[DELEGATION ERROR]" in result
        assert "rejected" in result

    def test_jsonrpc_error(self):
        async def rpc(request):
            body = await request.json()
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {"code": -32600, "message": "Invalid request"},
                }
            )

        result = _make_invoker(
            _httpx_client_factory=_factory_for(_stub_app(rpc_handler=rpc))
        ).invoke("hello")
        assert "[DELEGATION ERROR]" in result
        assert "Invalid request" in result

    def test_http_error(self):
        async def rpc(_request):
            return Response("Internal Server Error", status_code=500)

        result = _make_invoker(
            _httpx_client_factory=_factory_for(_stub_app(rpc_handler=rpc))
        ).invoke("hello")
        assert "[DELEGATION ERROR]" in result
        assert "500" in result

    def test_unauthorized(self):
        async def rpc(_request):
            return Response("no", status_code=401)

        result = _make_invoker(
            _httpx_client_factory=_factory_for(_stub_app(rpc_handler=rpc))
        ).invoke("hello")
        assert "[DELEGATION ERROR]" in result
        assert "401" in result

    def test_malformed_json(self):
        async def rpc(_request):
            return Response("{not-json", media_type="application/json")

        result = _make_invoker(
            _httpx_client_factory=_factory_for(_stub_app(rpc_handler=rpc))
        ).invoke("hello")
        assert "[DELEGATION ERROR]" in result

    def test_timeout(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/.well-known/agent-card.json"):
                return httpx.Response(200, json=_minimal_card())
            raise httpx.TimeoutException("timed out")

        def factory() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://test",
            )

        result = _make_invoker(timeout=1, _httpx_client_factory=factory).invoke("hello")
        assert "[DELEGATION ERROR]" in result
        assert "timed out" in result.lower()

    def test_no_output_returns_error(self):
        async def rpc(request):
            body = await request.json()
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {
                        "task": {
                            "id": "t1",
                            "contextId": "c1",
                            "status": {"state": "TASK_STATE_COMPLETED"},
                            "artifacts": [],
                            "history": [],
                        }
                    },
                }
            )

        result = _make_invoker(
            _httpx_client_factory=_factory_for(_stub_app(rpc_handler=rpc))
        ).invoke("hello")
        assert "[DELEGATION ERROR]" in result
        assert "No output" in result


class TestA2AInvokerPolling:
    def test_polling_flow(self):
        states = iter(["TASK_STATE_SUBMITTED", "TASK_STATE_WORKING", "TASK_STATE_COMPLETED"])

        async def rpc(request):
            body = await request.json()
            method = body.get("method")
            state = "TASK_STATE_SUBMITTED" if method == "SendMessage" else next(states)
            result: dict[str, Any] = {
                "id": "task-1",
                "contextId": "c1",
                "status": {"state": state},
            }
            if state == "TASK_STATE_COMPLETED":
                result["artifacts"] = [{"artifactId": "a1", "parts": [{"text": "done"}]}]
            payload: dict[str, Any] = {"jsonrpc": "2.0", "id": body.get("id")}
            payload["result"] = {"task": result} if method == "SendMessage" else result
            return JSONResponse(payload)

        with patch("anyio.sleep", new=AsyncMock()):
            result = _make_invoker(
                _httpx_client_factory=_factory_for(_stub_app(rpc_handler=rpc))
            ).invoke("hello")
        assert result == "done"

    def test_polling_timeout(self):
        async def rpc(request):
            body = await request.json()
            method = body.get("method")
            result = {
                "id": "task-1",
                "contextId": "c1",
                "status": {"state": "TASK_STATE_WORKING"},
            }
            payload: dict[str, Any] = {"jsonrpc": "2.0", "id": body.get("id")}
            payload["result"] = {"task": result} if method == "SendMessage" else result
            return JSONResponse(payload)

        times = iter([0.0, 0.0, 10.0])

        async def _sleep(_delay):
            return None

        with (
            patch("anyio.current_time", side_effect=lambda: next(times)),
            patch("anyio.sleep", new=_sleep),
        ):
            result = _make_invoker(
                timeout=5,
                _httpx_client_factory=_factory_for(_stub_app(rpc_handler=rpc)),
            ).invoke("hello")
        assert "[DELEGATION ERROR]" in result
        assert "timed out" in result.lower()


class TestA2AInvokerPolicy:
    def test_policy_denial(self):
        from unittest.mock import PropertyMock

        metadata = MagicMock()
        type(metadata).name = PropertyMock(return_value="coordinator")

        invoker = _make_invoker(source_metadata=metadata)
        with patch(
            "initrunner.agent.delegation.check_delegation_policy",
            return_value=False,
        ):
            result = invoker.invoke("hello")

        assert "[DELEGATION ERROR]" in result
        assert "Delegation denied by policy" in result


class TestA2AInvokerHeaders:
    def test_headers_from_env(self):
        import os

        captured: dict[str, httpx.AsyncClient] = {}

        async def rpc(request):
            body = await request.json()
            return JSONResponse(
                {"jsonrpc": "2.0", "id": body.get("id"), "result": _completed_send_result()}
            )

        app = _stub_app(rpc_handler=rpc)

        def factory() -> httpx.AsyncClient:
            client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            )
            captured["client"] = client
            return client

        invoker = _make_invoker(
            headers_env={"Authorization": "MY_API_KEY"},
            _httpx_client_factory=factory,
        )
        with patch.dict(os.environ, {"MY_API_KEY": "Bearer secret123"}):
            invoker.invoke("hello")

        assert captured["client"].headers.get("Authorization") == "Bearer secret123"
        assert captured["client"].headers.get("A2A-Version") == "1.0"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestDelegateToolConfigA2A:
    def test_a2a_mode_requires_url(self):
        from initrunner.agent.schema.tools._integration import (
            DelegateAgentRef,
            DelegateToolConfig,
        )

        with pytest.raises(ValueError, match="A2A mode requires 'url'"):
            DelegateToolConfig(
                type="delegate",
                mode="a2a",
                agents=[DelegateAgentRef(name="remote-agent")],
            )

    def test_a2a_mode_valid_with_url(self):
        from initrunner.agent.schema.tools._integration import (
            DelegateAgentRef,
            DelegateToolConfig,
        )

        config = DelegateToolConfig(
            type="delegate",
            mode="a2a",
            agents=[DelegateAgentRef(name="remote-agent", url="http://agent:8000")],
        )
        assert config.mode == "a2a"
        assert config.agents[0].url == "http://agent:8000"

    def test_summary_includes_mode(self):
        from initrunner.agent.schema.tools._integration import (
            DelegateAgentRef,
            DelegateToolConfig,
        )

        config = DelegateToolConfig(
            type="delegate",
            mode="a2a",
            agents=[DelegateAgentRef(name="remote-agent", url="http://agent:8000")],
        )
        assert "a2a" in config.summary()


# ---------------------------------------------------------------------------
# Tool builder
# ---------------------------------------------------------------------------


class TestBuildDelegateA2A:
    def test_a2a_mode_creates_a2a_invoker(self):
        from initrunner.agent.schema.tools._integration import (
            DelegateAgentRef,
            DelegateToolConfig,
        )
        from initrunner.agent.tools.custom import build_delegate_toolset

        config = DelegateToolConfig(
            type="delegate",
            mode="a2a",
            agents=[
                DelegateAgentRef(
                    name="remote",
                    url="http://remote:8000",
                    description="Remote A2A agent",
                )
            ],
        )

        mock_ctx = MagicMock()
        mock_ctx.role_dir = None
        mock_ctx.role.metadata = MagicMock()

        toolset = build_delegate_toolset(config, mock_ctx)
        assert toolset is not None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestA2ACLI:
    def test_help(self):
        from typer.testing import CliRunner

        from initrunner.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["a2a", "serve", "--help"])
        assert result.exit_code == 0
        assert "A2A" in result.output or "a2a" in result.output
        assert "ROLE_FILE" in result.output
        assert "--url" in result.output

    def test_default_advertise_url(self):
        from initrunner.cli.a2a_cmd import _default_advertise_url

        assert _default_advertise_url("127.0.0.1", 8000) == "http://127.0.0.1:8000"
        assert _default_advertise_url("::1", 9000) == "http://[::1]:9000"
