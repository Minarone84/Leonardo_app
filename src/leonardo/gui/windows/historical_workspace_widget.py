from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QMessageBox,
)

from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.windows.historical_chart_panel import HistoricalChartPanel


class HistoricalWorkspaceWidget(QWidget):
    """
    Managed embedded workspace for up to 4 historical chart panels.

    Layout policy:
    - 1 chart: fills full workspace
    - 2 charts: split 1x2
    - 3 charts: 2x2 with one empty slot
    - 4 charts: 2x2
    """

    MAX_CHARTS = 4

    def __init__(
        self,
        *,
        core_bridge: CoreBridge,
        window_manager=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._core = core_bridge
        self._window_manager = window_manager
        self._charts: List[HistoricalChartPanel] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._empty_state = QLabel(
            "No historical charts loaded.\nUse File → New Chart to load one.",
            self,
        )
        self._empty_state.setAlignment(Qt.AlignCenter)
        self._empty_state.setStyleSheet(
            """
            QLabel {
                border: 1px solid #4A4A4A;
                background-color: #1A1A1A;
                color: #D8D8D8;
                font-size: 14px;
            }
            """
        )

        self._grid_host = QWidget(self)
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(8)

        root.addWidget(self._empty_state, 1)
        root.addWidget(self._grid_host, 1)

        self._grid_host.hide()

    def chart_count(self) -> int:
        return len(self._charts)

    def can_add_chart(self) -> bool:
        return len(self._charts) < self.MAX_CHARTS

    def add_chart(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> bool:
        if not self.can_add_chart():
            return False

        panel = HistoricalChartPanel(core_bridge=self._core, parent=self._grid_host)
        panel.detach_requested.connect(self._on_panel_detach_requested)
        panel.close_requested.connect(self._on_panel_close_requested)
        panel.open_dataset(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
        )
        self._charts.append(panel)
        self._relayout()
        return True

    def add_existing_panel(self, panel: HistoricalChartPanel) -> bool:
        if not self.can_add_chart():
            return False

        try:
            panel.detach_requested.disconnect(self._on_panel_detach_requested)
        except Exception:
            pass

        try:
            panel.close_requested.disconnect(self._on_panel_close_requested)
        except Exception:
            pass

        panel.detach_requested.connect(self._on_panel_detach_requested)
        panel.close_requested.connect(self._on_panel_close_requested)
        panel.setParent(self._grid_host)
        self._charts.append(panel)
        self._relayout()
        return True

    def remove_chart(self, panel: HistoricalChartPanel) -> bool:
        if panel not in self._charts:
            return False

        self._charts.remove(panel)
        self._clear_layout()
        panel.setParent(None)
        self._relayout()
        return True

    def _on_panel_detach_requested(self, panel_obj: object) -> None:
        panel = panel_obj if isinstance(panel_obj, HistoricalChartPanel) else None
        if panel is None:
            return

        if panel not in self._charts:
            return

        if self._window_manager is None:
            QMessageBox.warning(
                self,
                "Historical Workspace",
                "Window manager not available. Cannot float chart.",
            )
            return

        removed = self.remove_chart(panel)
        if not removed:
            return

        self._window_manager.float_historical_chart_panel(panel=panel, parent=self.window())

    def _on_panel_close_requested(self, panel_obj: object) -> None:
        panel = panel_obj if isinstance(panel_obj, HistoricalChartPanel) else None
        if panel is None:
            return

        removed = self.remove_chart(panel)
        if not removed:
            return

        panel.deleteLater()

    def _clear_layout(self) -> None:
        while self._grid.count() > 0:
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self._grid_host)

    def _relayout(self) -> None:
        self._clear_layout()

        count = len(self._charts)
        if count == 0:
            self._grid_host.hide()
            self._empty_state.show()
            return

        self._empty_state.hide()
        self._grid_host.show()

        for row in range(2):
            self._grid.setRowStretch(row, 1)
        for col in range(2):
            self._grid.setColumnStretch(col, 1)

        if count == 1:
            self._grid.addWidget(self._charts[0], 0, 0, 2, 2)
            return

        if count == 2:
            self._grid.addWidget(self._charts[0], 0, 0, 2, 1)
            self._grid.addWidget(self._charts[1], 0, 1, 2, 1)
            return

        if count == 3:
            self._grid.addWidget(self._charts[0], 0, 0, 1, 1)
            self._grid.addWidget(self._charts[1], 0, 1, 1, 1)
            self._grid.addWidget(self._charts[2], 1, 0, 1, 1)
            return

        self._grid.addWidget(self._charts[0], 0, 0, 1, 1)
        self._grid.addWidget(self._charts[1], 0, 1, 1, 1)
        self._grid.addWidget(self._charts[2], 1, 0, 1, 1)
        self._grid.addWidget(self._charts[3], 1, 1, 1, 1)

    def warn_max_charts(self) -> None:
        QMessageBox.information(
            self,
            "Historical Workspace",
            "Maximum of 4 historical charts reached.",
        )