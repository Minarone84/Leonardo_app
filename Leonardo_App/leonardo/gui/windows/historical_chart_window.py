from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import QTimer

from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.chart.workspace import ChartWorkspaceWidget
from leonardo.gui.historical_chart_controller import HistoricalChartController


class HistoricalChartWindow(QWidget):
    def __init__(self, *, core_bridge: CoreBridge, parent=None) -> None:
        super().__init__(parent)
        self._core = core_bridge

        self.setWindowTitle("Historical Chart")
        self.resize(1200, 800)          # sensible default
        self.setMinimumSize(900, 600)   # prevent “microscopic window” syndrome

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._workspace = ChartWorkspaceWidget(parent=self)
        layout.addWidget(self._workspace)

        self._controller = HistoricalChartController(core_bridge=self._core, workspace=self._workspace, parent=self)
        self._controller.error.connect(self._on_error)

        self._autoload_done = False

    def showEvent(self, event) -> None:
        super().showEvent(event)

        if not self._autoload_done:
            self._autoload_done = True
            QTimer.singleShot(
                0,
                lambda: self._controller.open_dataset("bybit", "linear", "BTCUSDT", "1h"),
            )

    def _on_error(self, msg: str) -> None:
        print(f"[HistoricalChartWindow] {msg}")