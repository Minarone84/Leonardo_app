from __future__ import annotations

from typing import Any, Optional, Awaitable, TypeVar, Generic
from concurrent.futures import Future

from PySide6.QtCore import QObject, Signal

from leonardo.core.context import AppContext
from leonardo.gui.core_runner import CoreRunner

T = TypeVar("T")


class CoreBridge(QObject):
    """
    GUI-facing integration seam.
    """
    status_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._runner: Optional[CoreRunner] = None

    @property
    def is_running(self) -> bool:
        return self._runner is not None

    def start(self) -> None:
        if self._runner is not None:
            return
        self.status_changed.emit("Starting core...")
        self._runner = CoreRunner(on_status=self.status_changed.emit)
        self._runner.start()
        self.status_changed.emit("Ready")

    def stop(self) -> None:
        if self._runner is None:
            return
        self.status_changed.emit("Stopping core...")
        self._runner.stop()
        self._runner = None
        self.status_changed.emit("Stopped")

    def submit(self, coro: Awaitable[T]) -> Future[T]:
        if self._runner is None:
            raise RuntimeError("Core not started")
        return self._runner.submit(coro)  # type: ignore[arg-type]

    def try_get_audit_snapshot(self) -> Optional[dict[str, Any]]:
        if self._runner is None:
            return None
        snap = self._runner.get_audit_snapshot()
        if snap is None:
            return None
        return {"count": snap.count}

    @property
    def context(self) -> AppContext:
        if self._runner is None or self._runner.context is None:
            raise RuntimeError("Core not started or context not available")
        return self._runner.context
