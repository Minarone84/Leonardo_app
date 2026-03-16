from __future__ import annotations

from typing import Any, Optional, Awaitable, TypeVar, Callable
from concurrent.futures import Future
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal, Slot, Qt, QTimer

from leonardo.core.context import AppContext
from leonardo.gui.core_runner import CoreRunner

T = TypeVar("T")


class _GuiDispatcher(QObject):
    """
    Lives in the GUI thread. Receives requests and executes callables on GUI thread.
    """
    _invoke = Signal(object, object, object)  # fn, args(tuple), kwargs(dict)

    def __init__(self) -> None:
        super().__init__()
        self._invoke.connect(self._on_invoke, Qt.QueuedConnection)

    @Slot(object, object, object)
    def _on_invoke(self, fn_obj: object, args_obj: object, kwargs_obj: object) -> None:
        fn = fn_obj  # type: ignore[assignment]
        args = args_obj  # type: ignore[assignment]
        kwargs = kwargs_obj  # type: ignore[assignment]
        try:
            fn(*args, **kwargs)  # type: ignore[misc]
        except Exception as e:
            # Keep GUI alive. You can also emit status_changed here.
            # Avoid raising across Qt signal boundary.
            print(f"[CoreBridge.gui_call] GUI callable raised: {e!r}")


class CoreBridge(QObject):
    """
    GUI-facing integration seam.
    - submit(): schedule coroutine on core event loop (CoreRunner thread)
    - gui_call(): schedule callable on Qt GUI thread (thread-safe)
    """
    status_changed = Signal(str)

    # payload: ChartSnapshot / ChartPatch from leonardo.common.market_types
    chart_snapshot = Signal(object)
    chart_patch = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._runner: Optional[CoreRunner] = None
        self._gui = _GuiDispatcher()

        # Ensure dispatcher lives in the GUI thread even if CoreBridge is created early.
        # This schedules the move after the event loop starts.
        QTimer.singleShot(0, self._ensure_gui_thread)

    @Slot()
    def _ensure_gui_thread(self) -> None:
        # Move dispatcher to the thread that owns CoreBridge (should be GUI thread).
        self._gui.moveToThread(self.thread())

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

    def gui_call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """
        Thread-safe: schedule fn(*args, **kwargs) to run on the Qt GUI thread.
        Safe to call from core thread, websocket thread, etc.
        """
        # Ensure we always queue into GUI event loop:
        self._gui._invoke.emit(fn, args, kwargs)

    def try_get_audit_snapshot(self) -> Optional[dict[str, Any]]:
        if self._runner is None:
            return None
        snap = self._runner.get_audit_snapshot()
        if snap is None:
            return None
        events = getattr(snap, "events", [])
        return {"count": getattr(snap, "count", len(events)), "events": list(events)}
    
    @property
    def context(self) -> AppContext:
        if self._runner is None or self._runner.context is None:
            raise RuntimeError("Core not started or context not available")
        return self._runner.context