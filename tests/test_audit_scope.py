"""The per-run audit scope used by screening and judged approval."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from initrunner.audit.scope import audit_scope, log_security_event


def test_outside_a_scope_nothing_happens():
    log_security_event("jev.input", "{}")  # no error, nowhere to write


def test_inside_a_scope_the_event_reaches_the_logger():
    audit = MagicMock()
    with audit_scope(audit, "agent-a"):
        log_security_event("jev.approval", '{"decision": "approve"}')
    audit.log_security_event.assert_called_once_with(
        event_type="jev.approval", agent_name="agent-a", details='{"decision": "approve"}'
    )


def test_scope_without_a_logger_is_a_no_op():
    with audit_scope(None, "agent-a"):
        log_security_event("jev.input", "{}")


def test_scope_is_reset_on_exit():
    audit = MagicMock()
    with audit_scope(audit, "agent-a"):
        pass
    log_security_event("jev.input", "{}")
    audit.log_security_event.assert_not_called()


def test_scope_reaches_tasks_and_worker_threads():
    audit = MagicMock()

    async def _log_in_task():
        await asyncio.sleep(0)
        log_security_event("b", "{}")

    async def _run():
        with audit_scope(audit, "agent-a"):
            task = asyncio.create_task(_log_in_task())
            await asyncio.gather(asyncio.to_thread(log_security_event, "a", "{}"), task)

    asyncio.run(_run())
    assert audit.log_security_event.call_count == 2
