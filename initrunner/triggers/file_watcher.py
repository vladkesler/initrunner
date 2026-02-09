"""File watch trigger using watchfiles."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from watchfiles import watch

from initrunner.agent.schema import FileWatchTriggerConfig
from initrunner.triggers.base import TriggerBase, TriggerEvent


class FileWatchTrigger(TriggerBase):
    """Fires when files change in watched paths."""

    def __init__(
        self, config: FileWatchTriggerConfig, callback: Callable[[TriggerEvent], None]
    ) -> None:
        super().__init__(callback)
        self._config = config

    def _run(self) -> None:
        extensions = set(self._config.extensions) if self._config.extensions else None

        def _filter(_, path: str) -> bool:
            if extensions is None:
                return True
            return any(path.endswith(ext) for ext in extensions)

        if self._config.process_existing:
            for watch_path in self._config.paths:
                p = Path(watch_path)
                if not p.is_dir():
                    continue
                for child in sorted(p.iterdir()):
                    if self._stop_event.is_set():
                        return
                    if not child.is_file():
                        continue
                    if extensions and not any(child.name.endswith(ext) for ext in extensions):
                        continue
                    prompt = self._config.prompt_template.format(path=str(child))
                    self._callback(
                        TriggerEvent(
                            trigger_type="file_watch",
                            prompt=prompt,
                            metadata={"path": str(child)},
                        )
                    )

        for changes in watch(
            *self._config.paths,
            watch_filter=_filter,
            stop_event=self._stop_event,
            debounce=int(self._config.debounce_seconds * 1000),
        ):
            if self._stop_event.is_set():
                break
            for _change_type, path in changes:
                prompt = self._config.prompt_template.format(path=path)
                event = TriggerEvent(
                    trigger_type="file_watch",
                    prompt=prompt,
                    metadata={"path": path},
                )
                self._callback(event)
