"""Custom sink — call a user-provided Python function."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from initrunner._log import get_logger
from initrunner.sinks.base import SinkBase, SinkPayload

logger = get_logger("sink.custom")


class CustomSink(SinkBase):
    def __init__(self, module: str, function: str, role_dir: Path | None = None) -> None:
        self._module_name = module
        self._function_name = function
        self._role_dir = role_dir

    def send(self, payload: SinkPayload) -> None:
        try:
            if self._role_dir and str(self._role_dir) not in sys.path:
                sys.path.insert(0, str(self._role_dir))

            mod = importlib.import_module(self._module_name)
            func = getattr(mod, self._function_name)
            func(payload.to_dict())
        except Exception as exc:
            logger.error("Failed calling %s.%s: %s", self._module_name, self._function_name, exc)
