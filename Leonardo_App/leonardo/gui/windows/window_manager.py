from __future__ import annotations

from typing import Optional, Awaitable

from PySide6.QtCore import Qt, QObject
from PySide6.QtWidgets import QWidget

from leonardo.core.context import AppContext
from leonardo.core.state import StateStore
from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.windows.signals_window import SignalsWindow
from leonardo.gui.windows.windows_inspector_window import WindowsInspectorWindow
from leonardo.gui.windows.historical_download_window import HistoricalDownloadWindow
from leonardo.gui.windows.historical_chart_window import HistoricalChartWindow

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

        # ---- Historical windows ----
        self._historical_download: Optional[HistoricalDownloadWindow] = None
        self._historical_chart: Optional[HistoricalChartWindow] = None

    def _safe_submit(self, coro: Awaitable[object]) -> None:
        try:
            self._core.submit(coro)
        except RuntimeError:
            # Core already stopped / shutting down.
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

    # ---------- Historical Download Manager ----------

    def get_historical_download_manager(self) -> Optional[HistoricalDownloadWindow]:
        return self._historical_download

    def open_historical_download_manager(self, *, core_bridge: CoreBridge, parent: Optional[QObject] = None) -> HistoricalDownloadWindow:
        """
        Opens (or raises) the Historical Download Manager.
        parent arg exists so MainWindow can pass itself, but we still default to WindowManager parent.
        """
        if self._historical_download is None:
            # Until we wire an ExchangeRegistry into GUI, keep it explicit.
            exchange_names = ["bybit"]

            self._historical_download = HistoricalDownloadWindow(
                core_bridge,
                exchange_names=exchange_names,
                parent=parent or self._parent,
            )
            self._historical_download.setAttribute(Qt.WA_DeleteOnClose, True)
            self._historical_download.destroyed.connect(self._on_historical_download_destroyed)
            self._safe_submit(self._state.window_open("historical_download", "HistoricalDownloadWindow", where="gui"))

        self._historical_download.show()
        self._historical_download.raise_()
        self._historical_download.activateWindow()
        return self._historical_download

    def close_historical_download_manager(self) -> None:
        if self._historical_download is not None:
            self._historical_download.close()

    def _on_historical_download_destroyed(self) -> None:
        self._historical_download = None
        self._safe_submit(self._state.window_close("historical_download", where="gui"))

    # ---------- Historical Chart ----------

    def get_historical_chart(self) -> Optional[HistoricalChartWindow]:
        return self._historical_chart  # type: ignore[return-value]

    def open_historical_chart(self, *, core_bridge: CoreBridge, parent: Optional[QObject] = None) -> HistoricalChartWindow:
        if self._historical_chart is None:
            self._historical_chart = HistoricalChartWindow(core_bridge=core_bridge, parent=None)
            self._historical_chart.setWindowTitle("Historical Chart")
            self._historical_chart.setAttribute(Qt.WA_DeleteOnClose, True)
            self._historical_chart.destroyed.connect(self._on_historical_chart_destroyed)
            self._safe_submit(self._state.window_open("historical_chart", "HistoricalChartWindow", where="gui"))

        if parent is not None:
            self._historical_chart.move(parent.frameGeometry().topLeft() + parent.rect().center())
        
        self._historical_chart.show()
        self._historical_chart.raise_()
        self._historical_chart.activateWindow()
        return self._historical_chart  # type: ignore[return-value]

    def close_historical_chart(self) -> None:
        if self._historical_chart is not None:
            self._historical_chart.close()

    def _on_historical_chart_destroyed(self) -> None:
        self._historical_chart = None
        self._safe_submit(self._state.window_close("historical_chart", where="gui"))