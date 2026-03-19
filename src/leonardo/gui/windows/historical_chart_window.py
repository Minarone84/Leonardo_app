from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout

from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.windows.historical_chart_panel import HistoricalChartPanel


class HistoricalChartWindow(QWidget):
    """
    Floating shell window for a single HistoricalChartPanel.
    """

    def __init__(self, *, core_bridge: CoreBridge, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._core = core_bridge

        self.setWindowTitle("Historical Chart")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)

        self._panel: Optional[HistoricalChartPanel] = None

    def panel(self) -> Optional[HistoricalChartPanel]:
        return self._panel

    def set_panel(self, panel: HistoricalChartPanel) -> None:
        if self._panel is panel:
            return

        if self._panel is not None:
            try:
                self._panel.dock_requested.disconnect(self._on_panel_dock_requested)
            except Exception:
                pass
            self._root.removeWidget(self._panel)
            self._panel.setParent(None)
            self._panel.set_floating(False)

        self._panel = panel
        self._panel.setParent(self)
        self._panel.set_floating(True)

        try:
            self._panel.dock_requested.disconnect(self._on_panel_dock_requested)
        except Exception:
            pass
        self._panel.dock_requested.connect(self._on_panel_dock_requested)

        self._root.addWidget(self._panel, 1)
        self._sync_title_from_panel()

    def take_panel(self) -> Optional[HistoricalChartPanel]:
        if self._panel is None:
            return None

        panel = self._panel
        try:
            panel.dock_requested.disconnect(self._on_panel_dock_requested)
        except Exception:
            pass

        self._root.removeWidget(panel)
        panel.setParent(None)
        panel.set_floating(False)

        self._panel = None
        self.setWindowTitle("Historical Chart")
        return panel

    def open_dataset(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> None:
        self._ensure_panel()
        assert self._panel is not None

        self._panel.open_dataset(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
        )
        self._sync_title_from_panel()

    def _set_dataset_identity(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> None:
        self._ensure_panel()
        assert self._panel is not None

        self._panel._set_dataset_identity(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
        )
        self.setWindowTitle(
            self._panel._build_dataset_title(
                exchange=exchange,
                market_type=market_type,
                symbol=symbol,
                timeframe=timeframe,
            )
        )

    def _ensure_panel(self) -> None:
        if self._panel is None:
            self.set_panel(HistoricalChartPanel(core_bridge=self._core, parent=self))

    def _sync_title_from_panel(self) -> None:
        if self._panel is None:
            self.setWindowTitle("Historical Chart")
            return

        title = self._panel.dataset_title()
        self.setWindowTitle(title if title else "Historical Chart")

    def _on_panel_dock_requested(self, panel_obj: object) -> None:
        _ = panel_obj
        manager = getattr(self.window(), "_dock_handler", None)
        if callable(manager):
            manager(self)