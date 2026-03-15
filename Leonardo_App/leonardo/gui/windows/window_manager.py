from __future__ import annotations

from typing import Optional, Awaitable

from PySide6.QtCore import Qt, QObject
from PySide6.QtWidgets import QWidget, QMessageBox

from leonardo.core.context import AppContext
from leonardo.core.state import StateStore
from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.windows.signals_window import SignalsWindow
from leonardo.gui.windows.windows_inspector_window import WindowsInspectorWindow
from leonardo.gui.windows.historical_download_window import HistoricalDownloadWindow
from leonardo.gui.windows.historical_chart_window import HistoricalChartWindow
from leonardo.gui.windows.historical_data_manager_window import HistoricalDataManagerWindow
from leonardo.gui.windows.historical_chart_panel import HistoricalChartPanel


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

        self._historical_download: Optional[HistoricalDownloadWindow] = None
        self._historical_data_manager: Optional[HistoricalDataManagerWindow] = None

        self._floating_historical_charts: dict[str, HistoricalChartWindow] = {}
        self._historical_chart_counter: int = 0

    def _safe_submit(self, coro: Awaitable[object]) -> None:
        try:
            self._core.submit(coro)
        except RuntimeError:
            pass

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

    def get_historical_download_manager(self) -> Optional[HistoricalDownloadWindow]:
        return self._historical_download

    def open_historical_download_manager(
        self,
        *,
        core_bridge: CoreBridge,
        parent: Optional[QObject] = None,
    ) -> HistoricalDownloadWindow:
        if self._historical_download is None:
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

    def get_historical_data_manager(self) -> Optional[HistoricalDataManagerWindow]:
        return self._historical_data_manager

    def open_historical_data_manager(
        self,
        *,
        core_bridge: CoreBridge,
        parent: Optional[QObject] = None,
    ) -> HistoricalDataManagerWindow:
        if self._historical_data_manager is None:
            self._historical_data_manager = HistoricalDataManagerWindow(
                ctx=self._ctx,
                core_bridge=core_bridge,
                window_manager=self,
                parent=parent if isinstance(parent, QWidget) else None,
            )
            self._historical_data_manager.setAttribute(Qt.WA_DeleteOnClose, True)
            self._historical_data_manager.destroyed.connect(self._on_historical_data_manager_destroyed)
            self._safe_submit(
                self._state.window_open(
                    "historical_data_manager",
                    "HistoricalDataManagerWindow",
                    where="gui",
                )
            )

        self._historical_data_manager.show()
        self._historical_data_manager.raise_()
        self._historical_data_manager.activateWindow()
        return self._historical_data_manager

    def close_historical_data_manager(self) -> None:
        if self._historical_data_manager is not None:
            self._historical_data_manager.close()

    def _on_historical_data_manager_destroyed(self) -> None:
        self._historical_data_manager = None
        self._safe_submit(self._state.window_close("historical_data_manager", where="gui"))

    def float_historical_chart_panel(
        self,
        *,
        panel: HistoricalChartPanel,
        parent: Optional[QObject] = None,
    ) -> HistoricalChartWindow:
        self._historical_chart_counter += 1
        window_id = f"historical_chart_{self._historical_chart_counter}"

        win = HistoricalChartWindow(core_bridge=self._core, parent=None)
        win.setAttribute(Qt.WA_DeleteOnClose, True)
        win.setObjectName(window_id)
        win.set_panel(panel)
        win.dock_back_requested.connect(lambda win_obj, wid=window_id: self._on_dock_back_requested(wid, win_obj))
        win.destroyed.connect(lambda _=None, wid=window_id: self._on_floating_historical_chart_destroyed(wid))

        self._floating_historical_charts[window_id] = win
        self._safe_submit(self._state.window_open(window_id, "HistoricalChartWindow", where="gui"))

        if parent is not None and isinstance(parent, QWidget):
            win.move(parent.frameGeometry().topLeft() + parent.rect().center())

        win.show()
        win.raise_()
        win.activateWindow()
        return win

    def get_historical_chart(self) -> Optional[HistoricalChartWindow]:
        if not self._floating_historical_charts:
            return None
        last_key = sorted(self._floating_historical_charts.keys())[-1]
        return self._floating_historical_charts.get(last_key)

    def open_historical_chart(
        self,
        *,
        core_bridge: CoreBridge,
        exchange: str = "bybit",
        market_type: str = "linear",
        symbol: str = "BTCUSDT",
        timeframe: str = "1h",
        parent: Optional[QObject] = None,
    ) -> HistoricalChartWindow:
        panel = HistoricalChartPanel(core_bridge=core_bridge)
        panel.open_dataset(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
        )
        return self.float_historical_chart_panel(panel=panel, parent=parent)

    def close_historical_chart(self) -> None:
        win = self.get_historical_chart()
        if win is not None:
            win.close()

    def dock_historical_chart_window(self, *, window_id: str) -> bool:
        win = self._floating_historical_charts.get(window_id)
        if win is None:
            return False

        hdmw = self.get_historical_data_manager()
        if hdmw is None:
            QMessageBox.warning(
                None,
                "Historical Dock",
                "Historical Data Manager is not open. Cannot dock chart back.",
            )
            return False

        workspace = hdmw.workspace_widget()
        if workspace is None:
            QMessageBox.warning(
                hdmw,
                "Historical Dock",
                "Historical workspace is not available. Cannot dock chart back.",
            )
            return False

        if not workspace.can_add_chart():
            workspace.warn_max_charts()
            return False

        panel = win.take_panel()
        if panel is None:
            return False

        added = workspace.add_existing_panel(panel)
        if not added:
            win.set_panel(panel)
            workspace.warn_max_charts()
            return False

        win.close()
        hdmw.raise_()
        hdmw.activateWindow()
        return True

    def _on_dock_back_requested(self, window_id: str, win_obj: object) -> None:
        _ = win_obj
        self.dock_historical_chart_window(window_id=window_id)

    def _on_floating_historical_chart_destroyed(self, window_id: str) -> None:
        self._floating_historical_charts.pop(window_id, None)
        self._safe_submit(self._state.window_close(window_id, where="gui"))
