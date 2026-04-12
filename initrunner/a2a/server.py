"""A2A server -- expose an InitRunner agent as an A2A server."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fasta2a.applications import FastA2A  # type: ignore[import-not-found]
from fasta2a.broker import InMemoryBroker  # type: ignore[import-not-found]
from fasta2a.schema import (  # type: ignore[import-not-found]
    Artifact,
    DataPart,
    FilePart,
    Message,
    TaskIdParams,
    TaskSendParams,
    TextPart,
)
from fasta2a.storage import InMemoryStorage  # type: ignore[import-not-found]
from fasta2a.worker import Worker  # type: ignore[import-not-found]
from pydantic_ai import ModelMessage

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.audit.logger import AuditLogger

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom worker that routes through InitRunner's executor
# ---------------------------------------------------------------------------


@dataclass
class InitRunnerWorker(Worker[list[ModelMessage]]):
    """Worker that calls ``execute_run_async()`` instead of ``agent.run()``.

    This preserves InitRunner's executor semantics: input validation, usage
    limits, retry/timeout wrapping, output processing, audit logging, and
    agent-principal context.
    """

    agent: Agent = field(repr=False)
    role: RoleDefinition = field(repr=False)
    audit_logger: AuditLogger | None = field(default=None, repr=False)

    async def run_task(self, params: TaskSendParams) -> None:
        task = await self.storage.load_task(params["id"])
        if task is None:
            raise ValueError(f"Task {params['id']} not found")

        if task["status"]["state"] != "submitted":
            raise ValueError(
                f"Task {params['id']} already processed (state: {task['status']['state']})"
            )

        await self.storage.update_task(task["id"], state="working")

        # Load conversation context from previous tasks in this thread
        message_history = await self.storage.load_context(task["context_id"]) or []

        # Extract prompt text from the incoming A2A message parts
        prompt = self._extract_prompt(task.get("history", []))

        try:
            from initrunner.services.execution import execute_run_async

            result, messages = await execute_run_async(
                self.agent,
                self.role,
                prompt,
                audit_logger=self.audit_logger,
                message_history=message_history if message_history else None,
            )

            # Store full message history for conversation continuity
            await self.storage.update_context(task["context_id"], messages)

            if not result.success:
                await self.storage.update_task(task["id"], state="failed")
                return

            artifacts = self.build_artifacts(result.output)
            # Build agent response message for task history
            msg_parts: list[TextPart | FilePart | DataPart] = [
                TextPart(kind="text", text=result.output),
            ]
            a2a_messages: list[Message] = [
                Message(
                    role="agent",
                    parts=msg_parts,
                    kind="message",
                    message_id=str(uuid.uuid4()),
                )
            ]
        except Exception:
            await self.storage.update_task(task["id"], state="failed")
            raise
        else:
            await self.storage.update_task(
                task["id"],
                state="completed",
                new_artifacts=artifacts,
                new_messages=a2a_messages,
            )

    async def cancel_task(self, params: TaskIdParams) -> None:
        pass

    def build_message_history(self, history: list[Message]) -> list[ModelMessage]:
        """Convert A2A messages to PydanticAI format for context continuity."""
        from pydantic_ai import ModelRequest, ModelResponse, UserPromptPart
        from pydantic_ai import TextPart as PydanticTextPart

        model_messages: list[ModelMessage] = []
        for message in history:
            if message["role"] == "user":
                parts_text = []
                for part in message["parts"]:
                    if part["kind"] == "text":
                        parts_text.append(part["text"])
                if parts_text:
                    model_messages.append(
                        ModelRequest(parts=[UserPromptPart(content="\n".join(parts_text))])
                    )
            else:
                parts_text = []
                for part in message["parts"]:
                    if part["kind"] == "text":
                        parts_text.append(part["text"])
                if parts_text:
                    model_messages.append(
                        ModelResponse(parts=[PydanticTextPart(content=t) for t in parts_text])
                    )
        return model_messages

    def build_artifacts(self, result: Any) -> list[Artifact]:
        """Convert agent output to A2A artifacts."""
        artifact_id = str(uuid.uuid4())
        if isinstance(result, str):
            part: TextPart | DataPart = TextPart(kind="text", text=result)
        else:
            from pydantic import TypeAdapter

            output_type = type(result)
            adapter = TypeAdapter(output_type)
            data = adapter.dump_python(result, mode="json")
            json_schema = adapter.json_schema(mode="serialization")
            part = DataPart(
                kind="data",
                data={"result": data},
                metadata={"json_schema": json_schema},
            )
        artifact_parts: list[TextPart | FilePart | DataPart] = [part]
        return [Artifact(artifact_id=artifact_id, name="result", parts=artifact_parts)]

    def _extract_prompt(self, history: list[Message]) -> str:
        """Extract text prompt from the most recent user message in task history."""
        for message in reversed(history):
            if message["role"] == "user":
                texts = []
                for part in message["parts"]:
                    if part["kind"] == "text":
                        texts.append(part["text"])
                if texts:
                    return "\n".join(texts)
        return ""


# ---------------------------------------------------------------------------
# App construction and server entry point
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _worker_lifespan(
    app: FastA2A,
    worker: InitRunnerWorker,
) -> AsyncIterator[None]:
    """Start the worker during application startup."""
    async with app.task_manager:
        async with worker.run():
            yield


def build_a2a_app(
    agent: Agent,
    role: RoleDefinition,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    audit_logger: AuditLogger | None = None,
    api_key: str | None = None,
    cors_origins: list[str] | None = None,
) -> FastA2A:
    """Build a FastA2A application for an InitRunner agent."""
    from functools import partial

    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware

    storage: InMemoryStorage[list[ModelMessage]] = InMemoryStorage()
    broker = InMemoryBroker()
    worker = InitRunnerWorker(
        broker=broker,
        storage=storage,
        agent=agent,
        role=role,
        audit_logger=audit_logger,
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
                    applies_to=all_paths_predicate(exclude={"/.well-known/agent-card.json"}),
                    error_response=_a2a_error_response,
                ),
            )
        )

    url = f"http://{host}:{port}"
    lifespan = partial(_worker_lifespan, worker=worker)

    return FastA2A(
        storage=storage,
        broker=broker,
        name=role.metadata.name,
        url=url,
        description=role.metadata.description,
        middleware=middleware,
        lifespan=lifespan,
    )


def run_a2a_server(
    app: FastA2A,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Blocking entry point -- starts uvicorn with the A2A app."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")
