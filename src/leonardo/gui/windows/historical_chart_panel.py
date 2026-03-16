from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QFrame,
)

from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.chart.workspace import ChartWorkspaceWidget
from leonardo.gui.historical_chart_controller import HistoricalChartController


class HistoricalChartPanel(QFrame):
    """
    Reusable historical chart content widget.

    This widget is shell-agnostic:
    - it can live embedded inside HistoricalDataManagerWindow
    - it can be hosted inside a floating HistoricalChartWindow
    """

    detach_requested = Signal(object)
    close_requested = Signal(object)

    def __init__(self, *, core_bridge: CoreBridge, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._core = core_bridge

        self._exchange: str = ""
        self._market_type: str = ""
        self._symbol: str = ""
        self._timeframe: str = ""

        self.setObjectName("historicalChartPanel")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Plain)
        self.setStyleSheet(
            """
            QFrame#historicalChartPanel {
                border: 1px solid rgb(52, 52, 60);
                background-color: rgb(18, 18, 22);
            }
            QWidget#historicalStatusBar {
                background-color: rgb(24, 24, 28);
                border-top: 1px solid rgb(48, 48, 56);
            }
            QLabel {
                color: rgb(190, 190, 205);
                padding-left: 8px;
                padding-right: 8px;
            }
            QToolButton {
                color: rgb(220, 220, 230);
                background-color: rgb(38, 38, 44);
                border: 1px solid rgb(68, 68, 78);
                border-radius: 4px;
                padding: 4px 10px;
            }
            QToolButton:checked {
                background-color: rgb(70, 95, 140);
                border: 1px solid rgb(100, 130, 185);
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._workspace = ChartWorkspaceWidget(parent=self)
        root.addWidget(self._workspace, 1)

        self._status_bar = QWidget(self)
        self._status_bar.setObjectName("historicalStatusBar")
        self._status_bar.setFixedHeight(32)

        status_layout = QHBoxLayout(self._status_bar)
        status_layout.setContentsMargins(6, 4, 6, 4)
        status_layout.setSpacing(6)

        self._status_label = QLabel("Historical Chart", self._status_bar)
        self._status_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        status_layout.addWidget(self._status_label)

        status_layout.addStretch(1)

        self._float_button = QToolButton(self._status_bar)
        self._float_button.setText("Float")
        self._float_button.setToolTip("Detach this chart into a floating window")
        self._float_button.clicked.connect(self._on_float_clicked)
        status_layout.addWidget(self._float_button)

        self._close_button = QToolButton(self._status_bar)
        self._close_button.setText("Close")
        self._close_button.setToolTip("Close this embedded chart")
        self._close_button.clicked.connect(self._on_close_clicked)
        status_layout.addWidget(self._close_button)

        self._anchor_zoom_button = QToolButton(self._status_bar)
        self._anchor_zoom_button.setText("Anchor Zoom")
        self._anchor_zoom_button.setCheckable(True)
        self._anchor_zoom_button.setChecked(True)
        self._anchor_zoom_button.setToolTip("Keep zoom locked to the latest real candle")
        self._anchor_zoom_button.toggled.connect(self._on_anchor_zoom_toggled)
        status_layout.addWidget(self._anchor_zoom_button)

        root.addWidget(self._status_bar, 0)

        self._controller = HistoricalChartController(
            core_bridge=self._core,
            workspace=self._workspace,
            parent=self,
        )
        self._controller.error.connect(self._on_error)

        self._workspace.set_anchor_zoom_enabled(True)

    @property
    def workspace(self) -> ChartWorkspaceWidget:
        return self._workspace

    def open_dataset(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> None:
        self._exchange = exchange
        self._market_type = market_type
        self._symbol = symbol
        self._timeframe = timeframe

        self._set_dataset_identity(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
        )
        self._controller.open_dataset(exchange, market_type, symbol, timeframe)

    def dataset_key(self) -> str:
        if not self._exchange or not self._market_type or not self._symbol or not self._timeframe:
            return ""
        return f"{self._exchange}:{self._market_type}:{self._symbol}:{self._timeframe}"

    def dataset_title(self) -> str:
        return self._build_dataset_title(
            exchange=self._exchange,
            market_type=self._market_type,
            symbol=self._symbol,
            timeframe=self._timeframe,
        )

    def _set_dataset_identity(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> None:
        self._status_label.setText(
            self._build_dataset_status_text(
                exchange=exchange,
                market_type=market_type,
                symbol=symbol,
                timeframe=timeframe,
            )
        )

    def _build_dataset_title(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> str:
        exchange_display = exchange[:1].upper() + exchange[1:] if exchange else exchange
        return f"Historical Chart: {exchange_display}_{market_type}_{symbol}_{timeframe}"

    def _build_dataset_status_text(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> str:
        return self._build_dataset_title(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
        )

    def _on_float_clicked(self) -> None:
        self.detach_requested.emit(self)

    def _on_close_clicked(self) -> None:
        self.close_requested.emit(self)

    def _on_anchor_zoom_toggled(self, checked: bool) -> None:
        self._workspace.set_anchor_zoom_enabled(bool(checked))

    def _on_error(self, msg: str) -> None:
        print(f"[HistoricalChartPanel] {msg}")