"""Starlette application factory for the OpenAI-compatible API server."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from pydantic_ai import Agent
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from initrunner.agent.executor import execute_run, execute_run_stream
from initrunner.agent.policies import validate_input
from initrunner.agent.schema import RoleDefinition
from initrunner.audit.logger import AuditLogger
from initrunner.server.conversations import ConversationStore
from initrunner.server.convert import openai_messages_to_pydantic
from initrunner.server.models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    DeltaMessage,
    ModelInfo,
    ModelListResponse,
    StreamChoice,
    Usage,
)

_logger = logging.getLogger(__name__)


def _error_response(status: int, error_type: str, message: str) -> JSONResponse:
    """Return an OpenAI-style error JSON response."""
    return JSONResponse(
        {"error": {"message": message, "type": error_type, "code": status}},
        status_code=status,
    )


def _classify_error(error: str) -> tuple[int, str, str]:
    """Classify a RunResult error into (status_code, error_type, safe_message).

    Error strings come from executor._handle_run_error and _apply_output_validation.
    Only safe, pre-defined messages are returned — never raw model API errors.
    """
    _USAGE_LIMIT_PREFIX = "Usage limit exceeded"
    _TIMEOUT_PREFIX = "TimeoutError:"
    _OUTPUT_BLOCKED_MARKER = "blocked pattern"

    if error.startswith(_USAGE_LIMIT_PREFIX):
        return 400, "context_length_exceeded", error
    if error.lower().startswith(_TIMEOUT_PREFIX.lower()):
        return 504, "timeout", "Request timed out"
    if _OUTPUT_BLOCKED_MARKER in error.lower():
        return 400, "content_filter", "Response blocked by content policy"
    return 500, "server_error", "Internal server error"


_MAX_CONVERSATION_HISTORY = 40  # Match dashboard's limit


def _trim_history(messages: list, max_messages: int) -> list:
    """Trim conversation history, preserving the first message if it has a system prompt."""
    if len(messages) <= max_messages:
        return messages
    from pydantic_ai.messages import ModelRequest, SystemPromptPart

    first = messages[0]
    if isinstance(first, ModelRequest) and any(
        isinstance(p, SystemPromptPart) for p in first.parts
    ):
        return [first, *messages[-(max_messages - 1) :]]
    return messages[-max_messages:]


def _make_id() -> str:
    from initrunner._ids import generate_id

    return "chatcmpl-" + generate_id()


def _now_ts() -> int:
    return int(time.time())


def create_app(
    agent: Agent,
    role: RoleDefinition,
    *,
    audit_logger: AuditLogger | None = None,
    api_key: str | None = None,
    conversation_ttl: float | None = None,
    cors_origins: list[str] | None = None,
) -> Starlette:
    """Build and return the Starlette ASGI application."""
    from initrunner.server.rate_limiter import TokenBucketRateLimiter

    security = role.spec.security
    server_cfg = security.server
    rate_cfg = security.rate_limit

    conversations = ConversationStore(
        ttl_seconds=conversation_ttl if conversation_ttl is not None else 3600,
        max_conversations=server_cfg.max_conversations,
    )
    rate_limiter = TokenBucketRateLimiter(
        rate=rate_cfg.requests_per_minute / 60.0,
        burst=rate_cfg.burst_size,
    )
    model_name = role.metadata.name

    # --- Handlers ---

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def list_models(request: Request) -> JSONResponse:
        resp = ModelListResponse(
            data=[ModelInfo(id=model_name, created=_now_ts())],
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
        try:
            body = await request.json()
        except Exception:
            return _error_response(400, "invalid_request_error", "invalid JSON body")

        try:
            req = ChatCompletionRequest.model_validate(body)
        except Exception as e:
            return _error_response(400, "invalid_request_error", str(e))

        # Resolve conversation history
        conv_id = request.headers.get("x-conversation-id") or secrets.token_urlsafe(24)
        server_history = conversations.get(conv_id)

        try:
            if server_history is not None:
                # Use server-side history; prompt is just the last user message
                last_user = ""
                for msg in reversed(req.messages):
                    if msg.role == "user":
                        last_user = msg.content or ""
                        break
                if not last_user:
                    return _error_response(
                        400, "invalid_request_error", "no user message found in messages"
                    )
                prompt = last_user
                message_history = server_history
            else:
                prompt, message_history = openai_messages_to_pydantic(req.messages)
        except ValueError as e:
            return _error_response(400, "invalid_request_error", str(e))

        if req.stream:
            return await _handle_stream(
                agent,
                role,
                prompt,
                message_history,
                model_name,
                conv_id,
                conversations,
                audit_logger,
            )

        return await _handle_non_stream(
            agent,
            role,
            prompt,
            message_history,
            model_name,
            conv_id,
            conversations,
            audit_logger,
        )

    # --- Non-streaming handler ---

    async def _handle_non_stream(
        agent: Agent,
        role: RoleDefinition,
        prompt: str,
        message_history: list | None,
        model_name: str,
        conv_id: str,
        conversations: ConversationStore,
        audit_logger: AuditLogger | None,
    ) -> JSONResponse:
        content_policy = role.spec.security.content
        validation = validate_input(prompt, content_policy)
        if not validation.valid:
            return _error_response(400, "invalid_request_error", validation.reason)

        try:
            result, new_messages = await asyncio.to_thread(
                execute_run,
                agent,
                role,
                prompt,
                audit_logger=audit_logger,
                message_history=message_history,
                skip_input_validation=True,
            )
        except Exception:
            return _error_response(500, "server_error", "Internal server error")

        if not result.success:
            status, error_type, message = _classify_error(result.error or "")
            return _error_response(status, error_type, message)

        conversations.save(conv_id, _trim_history(new_messages, _MAX_CONVERSATION_HISTORY))

        resp = ChatCompletionResponse(
            id=_make_id(),
            created=_now_ts(),
            model=model_name,
            choices=[Choice(message=ChatMessage(role="assistant", content=result.output))],
            usage=Usage(
                prompt_tokens=result.tokens_in,
                completion_tokens=result.tokens_out,
                total_tokens=result.total_tokens,
            ),
        )
        return JSONResponse(
            resp.model_dump(exclude_none=True),
            headers={"X-Conversation-Id": conv_id},
        )

    # --- Streaming handler ---

    _TOKEN_QUEUE_MAX = 65_536
    _HEARTBEAT_INTERVAL = 100  # iterations (~10s at 0.1s poll)

    async def _handle_stream(
        agent: Agent,
        role: RoleDefinition,
        prompt: str,
        message_history: list | None,
        model_name: str,
        conv_id: str,
        conversations: ConversationStore,
        audit_logger: AuditLogger | None,
    ) -> JSONResponse | StreamingResponse:
        # Pre-flight input validation — reject before streaming starts so the
        # client gets a proper HTTP 400, not a 200 SSE stream with an error.
        content_policy = role.spec.security.content
        validation = validate_input(prompt, content_policy)
        if not validation.valid:
            return _error_response(400, "invalid_request_error", validation.reason)

        completion_id = _make_id()
        created = _now_ts()

        token_queue: asyncio.Queue[str | None] = asyncio.Queue(
            maxsize=_TOKEN_QUEUE_MAX,
        )
        loop = asyncio.get_running_loop()

        def on_token(chunk: str) -> None:
            try:
                loop.call_soon_threadsafe(token_queue.put_nowait, chunk)
            except RuntimeError:
                # Event loop closed — stream is being torn down
                pass

        def run_stream():
            # AuditLogger is thread-safe — the non-streaming path already
            # invokes execute_run via asyncio.to_thread which calls
            # audit_logger.log() from the thread pool.
            try:
                return execute_run_stream(
                    agent,
                    role,
                    prompt,
                    audit_logger=audit_logger,
                    message_history=message_history,
                    on_token=on_token,
                    skip_input_validation=True,
                )
            finally:
                loop.call_soon_threadsafe(token_queue.put_nowait, None)

        async def event_generator():
            stream_task = loop.run_in_executor(None, run_stream)

            # Send initial chunk with role
            initial = ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=model_name,
                choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
            )
            yield f"data: {initial.model_dump_json(exclude_none=True)}\n\n"

            # Forward tokens as SSE data events
            heartbeat_counter = 0
            while not stream_task.done():
                try:
                    token = await asyncio.wait_for(token_queue.get(), timeout=0.1)
                    if token is None:
                        break
                    chunk = ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=model_name,
                        choices=[StreamChoice(delta=DeltaMessage(content=token))],
                    )
                    yield f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"
                    heartbeat_counter = 0
                except TimeoutError:
                    heartbeat_counter += 1
                    if heartbeat_counter >= _HEARTBEAT_INTERVAL:
                        yield ": heartbeat\n\n"
                        heartbeat_counter = 0

            # Drain remaining tokens
            while not token_queue.empty():
                token = token_queue.get_nowait()
                if token is None:
                    break
                chunk = ChatCompletionChunk(
                    id=completion_id,
                    created=created,
                    model=model_name,
                    choices=[StreamChoice(delta=DeltaMessage(content=token))],
                )
                yield f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"

            # Get result from executor
            try:
                result, new_messages = await stream_task

                if result.success:
                    conversations.save(
                        conv_id,
                        _trim_history(new_messages, _MAX_CONVERSATION_HISTORY),
                    )

                    finish = ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=model_name,
                        choices=[StreamChoice(delta=DeltaMessage(), finish_reason="stop")],
                        usage=Usage(
                            prompt_tokens=result.tokens_in,
                            completion_tokens=result.tokens_out,
                            total_tokens=result.total_tokens,
                        ),
                    )
                    yield f"data: {finish.model_dump_json(exclude_none=True)}\n\n"
                else:
                    # Classify the error using the same logic as non-streaming
                    status, error_type, message = _classify_error(result.error or "")
                    if error_type == "content_filter":
                        finish = ChatCompletionChunk(
                            id=completion_id,
                            created=created,
                            model=model_name,
                            choices=[
                                StreamChoice(
                                    delta=DeltaMessage(),
                                    finish_reason="content_filter",
                                )
                            ],
                        )
                        yield f"data: {finish.model_dump_json(exclude_none=True)}\n\n"
                    else:
                        err = {
                            "message": message,
                            "type": error_type,
                            "code": status,
                        }
                        yield f"data: {json.dumps({'error': err})}\n\n"
            except Exception:
                _logger.exception("Error during SSE streaming")
                err = {
                    "message": "Internal server error",
                    "type": "server_error",
                    "code": 500,
                }
                yield f"data: {json.dumps({'error': err})}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Conversation-Id": conv_id,
            },
        )

    # --- Build app ---

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/v1/models", list_models, methods=["GET"]),
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
    ]

    middleware: list[Middleware] = []

    # CORS: merge CLI origins with role YAML origins (supplement, not replace)
    all_origins: list[str] = list(server_cfg.cors_origins or [])
    for origin in cors_origins or []:
        if origin not in all_origins:
            all_origins.append(origin)

    if all_origins:
        middleware.append(
            Middleware(
                CORSMiddleware,  # type: ignore[arg-type]
                allow_origins=all_origins,
                allow_methods=["*"],
                allow_headers=["*"],
                expose_headers=["X-Conversation-Id"],
            )
        )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        yield
        conversations.clear()
        if audit_logger is not None:
            audit_logger.close()

    app = Starlette(
        routes=routes,
        middleware=middleware,
        lifespan=lifespan,
    )

    from starlette.middleware.base import BaseHTTPMiddleware

    from initrunner.middleware import (
        all_paths_predicate,
        make_auth_dispatch,
        make_body_size_dispatch,
        make_https_dispatch,
        make_rate_limit_dispatch,
        openai_error_response,
        prefix_predicate,
    )

    v1_predicate = prefix_predicate("/v1/")

    # Order matters: outermost middleware runs first
    # HTTPS check -> Body size -> Rate limit -> Auth
    if api_key:
        app.add_middleware(
            BaseHTTPMiddleware,  # type: ignore[arg-type]
            dispatch=make_auth_dispatch(
                api_key=api_key,
                applies_to=v1_predicate,
                error_response=openai_error_response,
                error_message="invalid API key",
            ),
        )
    app.add_middleware(
        BaseHTTPMiddleware,  # type: ignore[arg-type]
        dispatch=make_rate_limit_dispatch(
            rate_limiter=rate_limiter,
            applies_to=v1_predicate,
            error_response=openai_error_response,
        ),
    )
    app.add_middleware(
        BaseHTTPMiddleware,  # type: ignore[arg-type]
        dispatch=make_body_size_dispatch(
            max_bytes=server_cfg.max_request_body_bytes,
            error_response=openai_error_response,
        ),
    )
    if server_cfg.require_https:
        app.add_middleware(
            BaseHTTPMiddleware,  # type: ignore[arg-type]
            dispatch=make_https_dispatch(
                applies_to=all_paths_predicate(exclude={"/health"}),
                error_response=openai_error_response,
            ),
        )

    return app


def run_server(
    agent: Agent,
    role: RoleDefinition,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    audit_logger: AuditLogger | None = None,
    api_key: str | None = None,
    conversation_ttl: float | None = None,
    cors_origins: list[str] | None = None,
) -> None:
    """Blocking entry point — starts uvicorn with the OpenAI-compatible app."""
    app = create_app(
        agent,
        role,
        audit_logger=audit_logger,
        api_key=api_key,
        conversation_ttl=conversation_ttl,
        cors_origins=cors_origins,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")
