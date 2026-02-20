from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QWidget, QVBoxLayout

from leonardo.gui.chart.viewport import ChartViewport
from leonardo.gui.chart.dummy_data import (
    Candle,
    make_dummy_candles,
    make_dummy_volume,
    make_dummy_oscillator,
)
from leonardo.gui.chart.model import ChartModel, Series
from leonardo.gui.chart.panes import PricePane, VolumePane, OscillatorPane
from leonardo.gui.chart.crosshair import Crosshair


@dataclass(frozen=True)
class OscillatorSpec:
    key: str    # unique id, e.g. "rsi_14"
    title: str  # e.g. "RSI(14)"


class ChartWorkspaceWidget(QWidget):
    """
    Central chart workspace: price pane + optional volume + optional oscillator panes.
    Shared viewport + shared data owned here (via ChartModel).
    """
    request_start_feed = Signal()
    request_stop_feed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._crosshair = Crosshair()

        # ---- Shared data (owned by the model) ----
        candles: List[Candle] = make_dummy_candles(n=220, seed=7)
        n = len(candles)
        volume: List[float] = make_dummy_volume(n=n, seed=11)

        self._model = ChartModel(candles=candles, volume=volume)

        # Register some default oscillator series in the model (available to add as panes)
        self._model.set_oscillator(Series(
            key="rsi_14",
            title="RSI(14)",
            values=make_dummy_oscillator(n=n, seed=13),
        ))
        self._model.set_oscillator(Series(
            key="macd_12_26_9",
            title="MACD(12,26,9)",
            values=make_dummy_oscillator(n=n, seed=17),
        ))

        # ---- Shared viewport ----
        self._viewport = ChartViewport(total_count=n, visible_count=min(120, n))

        # Default = anchored zoom (current behavior)
        #self._viewport.set_anchor_zoom_enabled(True)

        # ---- Layout ----
        self._splitter = QSplitter(Qt.Vertical, self)
        self._splitter.setChildrenCollapsible(False)

        # IMPORTANT: pass the shared crosshair into PricePane
        self._price = PricePane(
            viewport=self._viewport,
            model=self._model,
            crosshair=self._crosshair,
            parent=self,
        )
        self._splitter.addWidget(self._price)

        # Optional panes (not shown by default)
        self._volume: Optional[VolumePane] = None
        self._oscillators: Dict[str, OscillatorPane] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._splitter)

        self._apply_default_sizes()

    # -------- Public API (MainWindow calls these) --------

    def set_asset_label(self, text: str) -> None:
        self._price.set_asset_label(text)

    def set_studies_labels(self, indicators: List[str], oscillators: List[str]) -> None:
        self._price.set_studies(indicators=indicators, oscillators=oscillators)

    def set_anchor_zoom_enabled(self, enabled: bool) -> None:
        """
        Anchor zoom ON  => current behavior (chart autoscale/anchored).
        Anchor zoom OFF => chart uses free vertical scale mode (to be implemented in ChartRenderSurface).
        Volume/osc panes remain anchored by nature.
        """
        self._viewport.set_anchor_zoom_enabled(bool(enabled))

    def set_volume_enabled(self, enabled: bool) -> None:
        if enabled and self._volume is None:
            self._volume = VolumePane(
                viewport=self._viewport,
                crosshair=self._crosshair,
                volume=self._model.volume,
                parent=self,
            )
            self._splitter.addWidget(self._volume)
            self._apply_default_sizes()
        elif not enabled and self._volume is not None:
            self._remove_widget(self._volume)
            self._volume.deleteLater()
            self._volume = None
            self._apply_default_sizes()

    def add_oscillator(self, spec: OscillatorSpec) -> None:
        if spec.key in self._oscillators:
            return

        series = self._model.oscillator(spec.key)
        if series is None:
            # If unknown oscillator key, create a fallback series and register it
            n = len(self._model.candles)
            series = Series(
                key=spec.key,
                title=spec.title,
                values=make_dummy_oscillator(n=n, seed=99),
            )
            self._model.set_oscillator(series)

        pane = OscillatorPane(
            title=series.title,
            viewport=self._viewport,
            crosshair=self._crosshair,
            values=series.values,
            parent=self,
        )
        self._oscillators[spec.key] = pane
        self._splitter.addWidget(pane)
        self._apply_default_sizes()

    def remove_oscillator(self, key: str) -> None:
        pane = self._oscillators.pop(key, None)
        if pane is None:
            return
        self._remove_widget(pane)
        pane.deleteLater()
        self._apply_default_sizes()

    def clear_oscillators(self) -> None:
        for key in list(self._oscillators.keys()):
            self.remove_oscillator(key)

    @property
    def viewport(self) -> ChartViewport:
        return self._viewport

    @property
    def model(self) -> ChartModel:
        return self._model

    # -------- Internal helpers --------

    def _apply_default_sizes(self) -> None:
        sizes = [800]
        if self._volume:
            sizes.append(200)
        for _ in range(len(self._oscillators)):
            sizes.append(220)

        if len(sizes) == 1:
            sizes = [1000]

        self._splitter.setSizes(sizes)

    def _remove_widget(self, w: QWidget) -> None:
        w.setParent(None)
        w.hide()
