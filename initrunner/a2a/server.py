"""A2A 1.0 server -- expose an InitRunner agent over JSON-RPC."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from a2a.helpers.proto_helpers import new_task, new_text_part  # type: ignore[import-not-found]
from a2a.server.agent_execution import (  # type: ignore[import-not-found]
    AgentExecutor,
    RequestContext,
)
from a2a.server.events.event_queue import EventQueue  # type: ignore[import-not-found]
from a2a.server.request_handlers import DefaultRequestHandlerV2  # type: ignore[import-not-found]
from a2a.server.routes import (  # type: ignore[import-not-found]
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater  # type: ignore[import-not-found]
from a2a.types import TaskState  # type: ignore[import-not-found]
from a2a.utils.constants import (  # type: ignore[import-not-found]
    AGENT_CARD_WELL_KNOWN_PATH,
    DEFAULT_RPC_URL,
)
from starlette.applications import Starlette

from initrunner.a2a.card import build_agent_card
from initrunner.a2a.convert import output_to_parts
from initrunner.services.execution import execute_run_async

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelMessage

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.agent.skills import ResolvedSkill
    from initrunner.audit.logger import AuditLogger

_logger = logging.getLogger(__name__)

_CONTEXT_LRU_MAX = 1000


class InitRunnerAgentExecutor(AgentExecutor):
    """Route every A2A task through ``execute_run_async()``.

    Conversation context is an in-process LRU keyed by A2A ``context_id``.
    It has the same durability as the old FastA2A in-memory store: lost on
    process restart. Tasks themselves live in the SDK ``InMemoryTaskStore``.
    """

    def __init__(
        self,
        agent: Agent,
        role: RoleDefinition,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.agent = agent
        self.role = role
        self.audit_logger = audit_logger
        self._contexts: OrderedDict[str, list[ModelMessage]] = OrderedDict()

    def _history_for(self, context_id: str) -> list[ModelMessage] | None:
        history = self._contexts.get(context_id)
        if history is not None:
            self._contexts.move_to_end(context_id)
        return history

    def _store_history(self, context_id: str, messages: list[ModelMessage]) -> None:
        if context_id in self._contexts:
            self._contexts.move_to_end(context_id)
        self._contexts[context_id] = messages
        while len(self._contexts) > _CONTEXT_LRU_MAX:
            self._contexts.popitem(last=False)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id
        context_id = context.context_id
        if not task_id or not context_id:
            raise ValueError("A2A request is missing task_id or context_id")

        if context.current_task is None:
            if context.message is None:
                raise ValueError("A2A request is missing a user message")
            await event_queue.enqueue_event(
                new_task(
                    task_id,
                    context_id,
                    TaskState.TASK_STATE_SUBMITTED,
                    history=[context.message],
                )
            )

        updater = TaskUpdater(event_queue, task_id, context_id)
        await updater.start_work()

        prompt = context.get_user_input()
        message_history = self._history_for(context_id)

        try:
            result, messages = await execute_run_async(
                self.agent,
                self.role,
                prompt,
                audit_logger=self.audit_logger,
                message_history=message_history if message_history else None,
            )
            self._store_history(context_id, messages)

            if not result.success:
                await updater.failed(
                    message=updater.new_agent_message(
                        [new_text_part(result.error or "agent run failed")]
                    )
                )
                return

            parts = output_to_parts(result.output)
            await updater.add_artifact(parts, name="result")
            await updater.complete(message=updater.new_agent_message(parts))
        except Exception as exc:
            _logger.exception("A2A agent execution failed for task %s", task_id)
            await updater.failed(
                message=updater.new_agent_message([new_text_part(str(exc) or "agent run failed")])
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id
        context_id = context.context_id
        if not task_id or not context_id:
            raise ValueError("A2A cancel is missing task_id or context_id")
        await TaskUpdater(event_queue, task_id, context_id).cancel()


@asynccontextmanager
async def _handler_lifespan(
    app: Starlette,
    handler: DefaultRequestHandlerV2,
) -> AsyncIterator[None]:
    """Drain in-flight A2A tasks on shutdown."""
    try:
        yield
    finally:
        await handler.aclose()


def build_a2a_app(
    agent: Agent,
    role: RoleDefinition,
    *,
    url: str,
    audit_logger: AuditLogger | None = None,
    api_key: str | None = None,
    cors_origins: list[str] | None = None,
    skills: list[ResolvedSkill] | None = None,
) -> Starlette:
    """Build a Starlette app that speaks A2A 1.0 JSON-RPC."""
    from functools import partial

    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware

    executor = InitRunnerAgentExecutor(
        agent=agent,
        role=role,
        audit_logger=audit_logger,
    )
    card = build_agent_card(
        role,
        url=url,
        require_auth=bool(api_key),
        streaming=False,
        skills=skills,
    )
    handler = DefaultRequestHandlerV2(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    middleware: list[Middleware] = []

    if cors_origins:
        middleware.append(
            Middleware(
                CORSMiddleware,  # type: ignore[arg-type]
                allow_origins=cors_origins,
                allow_methods=["*"],
                allow_headers=["*"],
            )
        )

    if api_key:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse

        from initrunner.middleware import (
            all_paths_predicate,
            make_auth_dispatch,
        )

        def _a2a_error_response(status_code: int, message: str) -> JSONResponse:
            return JSONResponse(
                {"error": {"message": message, "code": status_code}},
                status_code=status_code,
            )

        middleware.append(
            Middleware(
                BaseHTTPMiddleware,  # type: ignore[arg-type]
                dispatch=make_auth_dispatch(
                    api_key=api_key,
                    applies_to=all_paths_predicate(exclude={AGENT_CARD_WELL_KNOWN_PATH}),
                    error_response=_a2a_error_response,
                ),
            )
        )

    return Starlette(
        routes=[
            *create_agent_card_routes(card),
            *create_jsonrpc_routes(handler, DEFAULT_RPC_URL),
        ],
        middleware=middleware,
        lifespan=partial(_handler_lifespan, handler=handler),
    )


def run_a2a_server(
    app: Starlette,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Blocking entry point -- starts uvicorn with the A2A app."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")
