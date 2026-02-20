from __future__ import annotations

from typing import Optional, Awaitable

from PySide6.QtCore import Qt, QObject

from leonardo.core.context import AppContext
from leonardo.core.state import StateStore
from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.windows.signals_window import SignalsWindow
from leonardo.gui.windows.windows_inspector_window import WindowsInspectorWindow


class WindowManager(QObject):
    """
    GUI Window Manager (singleton; stored as a service).
    Keeps window instances internally; registry stores only metadata via ctx.state.

    ctx.state methods are async and must run on the CORE asyncio loop.
    Therefore we submit them via CoreBridge.submit().

    Safety:
    During shutdown, core may stop before a window destruction callback fires.
    In that case, submitting state updates should be best-effort.
    """

    def __init__(self, *, ctx: AppContext, core_bridge: CoreBridge, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._core = core_bridge
        self._state: StateStore = ctx.state
        self._parent = parent

        self._signals: Optional[SignalsWindow] = None
        self._inspector: Optional[WindowsInspectorWindow] = None

    def _safe_submit(self, coro: Awaitable[object]) -> None:
        try:
            self._core.submit(coro)
        except RuntimeError:
            pass

    # ---------- Signals ----------

    def get_signals(self) -> Optional[SignalsWindow]:
        return self._signals

    def open_signals(self) -> SignalsWindow:
        if self._signals is None:
            self._signals = SignalsWindow(parent=self._parent)
            self._signals.setAttribute(Qt.WA_DeleteOnClose, True)
            self._signals.destroyed.connect(self._on_signals_destroyed)
            self._safe_submit(self._state.window_open("signals", "SignalsWindow", where="gui"))

        self._signals.show()
        self._signals.raise_()
        self._signals.activateWindow()
        return self._signals

    def close_signals(self) -> None:
        if self._signals is not None:
            self._signals.close()

    def _on_signals_destroyed(self) -> None:
        self._signals = None
        self._safe_submit(self._state.window_close("signals", where="gui"))

    # ---------- Windows Inspector ----------

    def get_windows_inspector(self) -> Optional[WindowsInspectorWindow]:
        return self._inspector

    def open_windows_inspector(self) -> WindowsInspectorWindow:
        if self._inspector is None:
            self._inspector = WindowsInspectorWindow(ctx=self._ctx, core_bridge=self._core, parent=self._parent)
            self._inspector.setAttribute(Qt.WA_DeleteOnClose, True)
            self._inspector.destroyed.connect(self._on_inspector_destroyed)
            self._safe_submit(self._state.window_open("windows_inspector", "WindowsInspectorWindow", where="gui"))

        self._inspector.show()
        self._inspector.raise_()
        self._inspector.activateWindow()
        return self._inspector

    def close_windows_inspector(self) -> None:
        if self._inspector is not None:
            self._inspector.close()

    def _on_inspector_destroyed(self) -> None:
        self._inspector = None
        self._safe_submit(self._state.window_close("windows_inspector", where="gui"))
