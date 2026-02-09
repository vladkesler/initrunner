"""File sink — append results to a local file."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from initrunner._log import get_logger
from initrunner.sinks.base import SinkBase, SinkPayload

logger = get_logger("sink.file")


class FileSink(SinkBase):
    def __init__(self, path: str, fmt: str = "json") -> None:
        self._path = Path(os.path.expandvars(path))
        self._format = fmt

    def send(self, payload: SinkPayload) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)

            # Use os.open() with restrictive permissions so the file is
            # never world-readable, even briefly.
            fd = os.open(
                str(self._path),
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            try:
                if self._format == "json":
                    os.write(fd, (json.dumps(payload.to_dict()) + "\n").encode())
                else:
                    ts = payload.timestamp or datetime.now(UTC).isoformat()
                    status = "OK" if payload.success else f"ERROR: {payload.error}"
                    os.write(
                        fd,
                        f"[{ts}] {payload.agent_name} | {status} | {payload.output}\n".encode(),
                    )
            finally:
                os.close(fd)
        except Exception as exc:
            logger.error("Failed to write to %s: %s", self._path, exc)
